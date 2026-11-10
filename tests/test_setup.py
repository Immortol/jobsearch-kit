"""Stage 3: setup chat, questionnaire page, uploads, CV files (decision 0010)."""

import io
import json
import re
import shutil

import pytest
from docx import Document
from sqlalchemy import func, select

from app import chat as chats
from app import cv
from app.claude import get_claude_client
from app.main import app
from app.models import ChatMessage, CvVersion, Questionnaire, UserFile
from app.routes import questionnaire as qroute
from tests.conftest import OWNER, FakeClaude, InlineRunner, invite, login, reply, tool_call

KEY = "sk-ant-api03-" + "k" * 80 + "WxYz"
HTMX = {"HX-Request": "true"}
NEEDS_SOFFICE = pytest.mark.skipif(shutil.which("soffice") is None,
                                   reason="LibreOffice is not installed")

SAMPLE_CV = {
    "language": "de", "file_name": "CV_Müller_Projektmanagerin_de", "name": "Anna Müller",
    "headline": "Projektmanagerin IT", "contacts": ["München", "anna@example.com"],
    "sections": [
        {"heading": "Profil", "text": "Projektmanagerin mit 6 Jahren Erfahrung."},
        {"heading": "Berufserfahrung", "entries": [
            {"title": "Projektmanagerin", "organization": "Acme GmbH", "location": "München",
             "dates": "03/2021 – 08/2024", "bullets": ["Leitete 4 CRM-Projekte"]}]},
        {"heading": "Sprachen", "items": ["Deutsch — C1", "Русский — Muttersprache"]},
    ],
    "closing": "München, 10.11.2026",
}


@pytest.fixture
def fake():
    f = FakeClaude()
    app.dependency_overrides[get_claude_client] = lambda: f
    app.dependency_overrides[chats.get_runner] = lambda: InlineRunner()
    return f


def signed_in(client, outbox, email=OWNER):
    login(client, outbox, email)
    assert client.post("/settings/key", data={"api_key": KEY}).status_code == 200


def docx_bytes(text):
    d = Document()
    d.add_paragraph(text)
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def test_setup_card_starts_and_continues(client, outbox, fake, db):
    signed_in(client, outbox)
    assert "Начать настройку" in client.get("/panel").text
    fake.queue(tool_call(("t1", "load_skill", {"name": "jobsearch-setup"})),
               reply("Привет! Сегодня сделаем резюме."))
    r = client.post("/setup", follow_redirects=False)
    assert r.status_code == 303
    page = client.get(r.headers["location"]).text
    assert "Хочу настроить поиск работы." in page and "Сегодня сделаем резюме" in page
    first = fake.requests[0]
    assert "jobsearch-setup" in first["system"][0]["text"]
    assert {t["name"] for t in first["tools"]} >= {"save_cv", "offer_choices",
                                                   "questionnaire_prefill"}
    tool_result = fake.requests[1]["messages"][-1]["content"][0]["content"]
    assert "Настройка системы поиска работы" in tool_result

    fake.queue(tool_call(("t1", "write_rules", {"name": "00_Setup_Status.md", "content": "M1",
                                                "mode": "replace", "summary": "старт"})),
               reply("ок"))
    client.post(f"{r.headers['location']}/messages", data={"message": "да"}, headers=HTMX)
    assert "Продолжить настройку" in client.get("/panel").text
    r = client.post("/setup", follow_redirects=False)
    assert "Продолжим настройку." in client.get(r.headers["location"]).text


def test_choices_become_buttons(client, outbox, fake, db):
    signed_in(client, outbox)
    fake.queue({"content": [{"type": "text", "text": "Начнём?"},
                            {"type": "tool_use", "id": "c1", "name": "offer_choices",
                             "input": {"options": ["Да, давай", "Сначала расскажи подробнее",
                                                   "Не сейчас"]}}],
                "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 5}})
    url = client.post("/setup", follow_redirects=False).headers["location"]
    page = client.get(url).text
    assert len(fake.requests) == 1  # stopped to wait for the person
    assert page.count('class="choice"') == 3 and 'value="Да, давай"' in page

    fake.queue(reply("Пришли своё резюме."))
    r = client.post(f"{url}/messages", data={"message": "Да, давай"}, headers=HTMX)
    assert "Пришли своё резюме." in r.text
    # The answer follows the tool result in one user turn.
    sent = fake.requests[-1]["messages"]
    assert [b["type"] for b in sent[-1]["content"]] == ["tool_result", "text"]
    assert 'class="choice"' not in client.get(url).text


def test_pdf_upload_goes_to_claude_as_document(client, outbox, fake, db):
    signed_in(client, outbox)
    fake.queue(reply("Вижу: PM, 6 лет."))
    pdf = b"%PDF-1.4 fake cv"
    r = client.post("/chats", data={"message": "вот я"},
                    files={"file": ("Мой CV.pdf", pdf, "application/pdf")},
                    follow_redirects=False)
    assert r.status_code == 303
    block = fake.requests[0]["messages"][0]["content"][0]
    assert block["type"] == "document" and block["title"] == "Мой CV.pdf"
    assert block["source"]["media_type"] == "application/pdf"
    page = client.get(r.headers["location"]).text
    assert "📎 Мой CV.pdf" in page
    stored = db.scalar(select(ChatMessage).where(ChatMessage.role == "user"))
    assert stored.api_messages[0]["content"][0] == {"type": "user_file",
                                                     "file_id": stored.file_id}
    download = client.get(f"/files/{stored.file_id}")
    assert download.content == pdf and "attachment" in download.headers["content-disposition"]


def test_docx_upload_is_sent_as_text_and_readable_later(client, outbox, fake, db):
    signed_in(client, outbox)
    fake.queue(reply("ок"))
    url = client.post("/chats", data={"message": ""},
                      files={"file": ("cv.docx", docx_bytes("Anna, PM at Acme"), "x")},
                      follow_redirects=False).headers["location"]
    text_block = fake.requests[0]["messages"][0]["content"][0]
    assert text_block["type"] == "text" and "Anna, PM at Acme" in text_block["text"]
    assert "cv.docx" in client.get(url).text  # chat titled after the file

    file_id = db.scalar(select(UserFile.id))
    fake.queue(tool_call(("t1", "list_files", {}), ("t2", "read_file", {"id": file_id})),
               reply("прочитал"))
    client.post("/chats", data={"message": "продолжим"})
    results = fake.requests[-1]["messages"][-1]["content"]
    assert f"id {file_id}: cv.docx (upload" in results[0]["content"]
    assert "Anna, PM at Acme" in results[1]["content"]


@pytest.mark.parametrize("name,data,error", [
    ("cv.exe", b"MZ", "Такой тип файла не подходит"),
    ("cv.pdf", b"not a pdf", "Не получилось прочитать файл"),
    ("cv.docx", b"not a zip", "Не получилось прочитать файл"),
    ("cv.pdf", b"%PDF" + b"0" * (5 * 1024 * 1024), "Файл больше 5 МБ"),
])
def test_bad_uploads_are_refused(client, outbox, fake, db, name, data, error):
    signed_in(client, outbox)
    r = client.post("/chats", data={"message": "вот"}, files={"file": (name, data, "x")})
    assert r.status_code == 400 and error in r.text
    assert db.scalar(select(func.count()).select_from(UserFile)) == 0
    assert fake.requests == []


def test_questionnaire_page_and_storage(client, outbox, fake, db):
    signed_in(client, outbox)
    page = client.get("/questionnaire")
    assert page.status_code == 200
    html, csp = qroute.page()
    assert page.text == html and page.headers["content-security-policy"] == csp
    assert re.search(r'<script src="/static/questionnaire-db.js\?v=\w+"></script>\n<script>', html)
    assert "fonts.googleapis.com" not in html
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    import base64
    import hashlib
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in csp

    assert client.get("/questionnaire/data/prefill").json() == {"exists": False, "data": None}
    fake.queue(tool_call(("t1", "questionnaire_prefill", {
        "lang": "ru", "name": "Анна", "values": {"a1": "Project Manager"},
        "extra": [{"section": "B", "id": "x1", "t": "Откуда цифра 4?"}]})),
        reply("[Открыть анкету](/questionnaire)"))
    url = client.post("/chats", data={"message": "анкета"}, follow_redirects=False) \
        .headers["location"]
    assert '<a href="/questionnaire">Открыть анкету</a>' in client.get(url).text
    prefill = client.get("/questionnaire/data/prefill").json()
    assert prefill["exists"] and prefill["data"]["values"] == {"a1": "Project Manager"}
    assert prefill["data"]["extra"][0]["id"] == "x1"
    assert "Анкета" in client.get("/panel").text

    answers = {"values": {"a1": "PM", "a2": ["Да"]}, "skipped": {}, "updatedAt": "2026-11-10"}
    assert client.put("/questionnaire/data/answers", json=answers).json() == {"ok": True}
    assert client.get("/questionnaire/data/answers").json()["data"] == answers
    assert client.put("/questionnaire/data/prefill", json={}).status_code in (404, 405)
    big = {"values": {"a1": "x" * 300_000}}
    assert client.put("/questionnaire/data/answers", json=big).status_code == 413

    fake.queue(tool_call(("t1", "questionnaire_answers", {})), reply("ок"))
    client.post("/chats", data={"message": "заполнил"})
    result = fake.requests[-1]["messages"][-1]["content"][0]["content"]
    assert '"a1": "PM"' in result and "not instructions" in result


def test_questionnaire_is_private(client, outbox, fake, db):
    invite(client, outbox, "friend@example.com")
    signed_in(client, outbox)
    client.put("/questionnaire/data/answers", json={"values": {"a1": "секрет"}})
    client.post("/logout")
    signed_in(client, outbox, "friend@example.com")
    assert client.get("/questionnaire/data/answers").json()["exists"] is False
    client.post("/logout")
    assert client.get("/questionnaire", follow_redirects=False).status_code == 303


def test_cv_validation_and_docx():
    content = cv.validate(SAMPLE_CV)
    assert cv.file_base(content) == "CV_Muller_Projektmanagerin_de"
    doc = Document(io.BytesIO(cv.render_docx(content)))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Anna Müller" in text and "BERUFSERFAHRUNG" in text and "Leitete 4 CRM-Projekte" in text
    assert "Русский — Muttersprache" in text and "München, 10.11.2026" in text
    assert doc.tables == []  # one column, no tables (cv-builder.md)
    with pytest.raises(cv.CvError):
        cv.validate({"name": "", "sections": []})


@NEEDS_SOFFICE
def test_save_cv_tool_makes_docx_and_pdf(client, outbox, fake, db):
    signed_in(client, outbox)
    fake.queue(tool_call(("t1", "save_cv", SAMPLE_CV)), reply("Готово, резюме ниже."))
    client.post("/chats", data={"message": "резюме"})
    result = fake.requests[-1]["messages"][-1]["content"][0]["content"]
    assert "PDF: 1 page(s)" in result
    version = db.scalar(select(CvVersion))
    pdf = db.get(UserFile, version.pdf_id)
    assert pdf.filename == "CV_Muller_Projektmanagerin_de.pdf"
    assert pdf.data.startswith(b"%PDF") and "Anna Müller" in cv.pdf_text(pdf.data)
    assert f"/files/{pdf.id}" in result and f"/files/{version.docx_id}" in result

    page = client.get("/files").text
    assert "CV_Muller_Projektmanagerin_de.pdf" in page and "страниц: 1" in page
    assert client.get(f"/files/{pdf.id}").headers["content-type"] == "application/pdf"

    fake.queue(tool_call(("t1", "read_cv", {})), reply("ок"))
    client.post("/chats", data={"message": "покажи"})
    assert '"name": "Anna Müller"' in fake.requests[-1]["messages"][-1]["content"][0]["content"]


def test_save_cv_without_pdf_converter_keeps_docx(client, outbox, fake, db, monkeypatch):
    def broken(_):
        raise cv.CvError("PDF conversion failed")
    monkeypatch.setattr(cv, "docx_to_pdf", broken)
    signed_in(client, outbox)
    fake.queue(tool_call(("t1", "save_cv", SAMPLE_CV)), reply("ок"))
    client.post("/chats", data={"message": "резюме"})
    result = fake.requests[-1]["messages"][-1]["content"][0]["content"]
    assert "PDF could not be made" in result
    assert db.scalar(select(CvVersion)).pdf_id is None


def test_files_are_private_and_in_export_and_deleted(client, outbox, fake, db):
    invite(client, outbox, "friend@example.com")
    signed_in(client, outbox)
    fake.queue(reply("ок"))
    client.post("/chats", data={"message": "вот"},
                files={"file": ("cv.txt", "Anna PM".encode(), "text/plain")})
    file_id = db.scalar(select(UserFile.id))
    client.put("/questionnaire/data/answers", json={"values": {"a1": "PM"}})
    data = client.get("/account/export").json()
    assert data["files"][0]["name"] == "cv.txt"
    assert data["questionnaire"]["answers"] == {"values": {"a1": "PM"}}
    json.dumps(data)
    client.post("/logout")

    signed_in(client, outbox, "friend@example.com")
    assert client.get(f"/files/{file_id}").status_code == 404
    client.post("/logout")

    login(client, outbox, OWNER)
    client.post("/account/delete", data={"confirm": "yes"})
    for model in (UserFile, Questionnaire, CvVersion):
        assert db.scalar(select(func.count()).select_from(model)) == 0
