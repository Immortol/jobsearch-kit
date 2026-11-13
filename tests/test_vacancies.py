"""Stage 4a: vacancies feed, cards, documents, tracker, stories (decision 0011)."""

import shutil

import pytest
from sqlalchemy import func, select

from app import chat as chats
from app import rules
from app import vacancies as vac
from app.claude import get_claude_client
from app.main import app
from app.models import Chat, User, UserFile, Vacancy
from tests.conftest import OWNER, FakeClaude, InlineRunner, invite, login, reply, tool_call
from tests.test_setup import SAMPLE_CV

KEY = "sk-ant-api03-" + "k" * 80 + "WxYz"
HTMX = {"HX-Request": "true"}
NEEDS_SOFFICE = pytest.mark.skipif(shutil.which("soffice") is None,
                                   reason="LibreOffice is not installed")

LETTER = {
    "lang": "de", "sender": {"name": "Anna Müller", "lines": ["anna@example.com"]},
    "date": "München, 10.11.2026", "subject": "Bewerbung als Projektmanagerin",
    "salutation": "Sehr geehrte Damen und Herren,",
    "paragraphs": ["Mit Interesse habe ich Ihre Anzeige gelesen.", "Ich leitete 4 Projekte."],
    "closing": "Mit freundlichen Grüßen",
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


def assessed(company, role, score, status, summary):
    return tool_call(("u1", "vacancy_update", {
        "company": company, "role": role, "location": "München", "score": score,
        "status": status, "summary": summary, "next_step": "Bewerben bis 30.11"}))


def test_url_key_and_extraction():
    a = vac.url_key("https://www.Example.com/jobs/123/?utm_source=x&gclid=1&id=7#apply")
    assert a == vac.url_key("http://example.com/jobs/123?id=7")
    assert a != vac.url_key("https://example.com/jobs/124?id=7")
    text = "две: https://a.example/1, и https://b.example/2. и снова https://a.example/1"
    assert vac.extract_urls(text) == ["https://a.example/1", "https://b.example/2"]


def test_paste_two_links_makes_two_isolated_cards(client, outbox, fake, db):
    signed_in(client, outbox)
    owner = db.scalar(select(User).where(User.email == OWNER))
    rules.write_rule(db, owner, "03_Strategy.md", "Ищу PM в Мюнхене")
    db.commit()
    fake.queue(assessed("Acme", "PM", 4, "prepared", "**4/5** · Acme · PM"), reply("4/5 Acme"),
               assessed("Beta", "Sales", 2, "assessed", "**2/5** · Beta · Sales"),
               reply("2/5 Beta"))
    r = client.post("/vacancies", data={"text": "https://jobs.example/acme https://jobs.example/beta"},
                    follow_redirects=False)
    assert r.status_code == 303 and "added=2" in r.headers["location"]

    # Each card is its own conversation: only its own link, the skill and rules in the system.
    first, third = fake.requests[0], fake.requests[2]
    assert first["messages"] == [{"role": "user", "content": [
        {"type": "text", "text": "https://jobs.example/acme",
         "cache_control": {"type": "ephemeral"}}]}]
    assert "https://jobs.example/acme" not in str(third["messages"])
    assert "https://jobs.example/beta" in str(third["messages"])
    assert "Вакансия → оценка → документы" in first["system"][0]["text"]
    assert "Ищу PM в Мюнхене" in first["system"][1]["text"]
    assert {t["name"] for t in first["tools"]} >= {"vacancy_update", "make_letter", "web_fetch"}
    assert "questionnaire_prefill" not in {t["name"] for t in first["tools"]}

    feed = client.get("/vacancies").text
    assert "Acme · PM" in feed and "Beta · Sales" in feed
    assert '<span class="score s4">4/5</span>' in feed and "Документы готовы" in feed
    # Card threads are not chats of their own.
    assert "Acme" not in client.get("/chats").text

    tracker = client.get("/tracker").text
    assert "Acme · PM" in tracker and "Beta · Sales" not in tracker
    assert "Beta · Sales" in client.get("/tracker?f=all").text
    assert "Beta" in client.get("/vacancies?f=all&q=beta").text
    assert "Acme" not in client.get("/vacancies?q=beta").text
    assert "Acme" in client.get("/vacancies?f=good").text and \
        "Beta" not in client.get("/vacancies?f=good").text


def test_repeated_link_opens_the_existing_card(client, outbox, fake, db):
    signed_in(client, outbox)
    fake.queue(reply("оценка"))
    client.post("/vacancies", data={"text": "https://jobs.example/acme?utm_source=li"})
    v = db.scalar(select(Vacancy))
    r = client.post("/vacancies", data={"text": "https://www.jobs.example/acme/"},
                    follow_redirects=False)
    assert r.headers["location"] == f"/vacancies/{v.id}?repeat=1"
    assert "уже есть в ленте" in client.get(r.headers["location"]).text
    assert len(fake.requests) == 1
    assert db.scalar(select(func.count()).select_from(Vacancy)) == 1


def test_card_without_update_still_settles(client, outbox, fake, db):
    signed_in(client, outbox)
    fake.queue(reply("Не открылась страница, пришли текст."))
    client.post("/vacancies", data={"text": "https://jobs.example/x"})
    v = db.scalar(select(Vacancy))
    db.refresh(v)
    assert v.status == "assessed" and "пришли текст" in v.summary


def test_pasted_text_and_follow_up_stay_in_the_card(client, outbox, fake, db):
    signed_in(client, outbox)
    fake.queue(assessed("Acme", "PM", 3, "assessed", "3/5"), reply("3/5"))
    client.post("/vacancies", data={"text": "Acme sucht PM in München. Aufgaben: …"})
    fake.queue(reply("Другой вопрос"))
    client.post("/vacancies", data={"text": "https://jobs.example/other"})
    v = db.scalar(select(Vacancy).where(Vacancy.company == "Acme"))
    card = vac.card_chat(db, v)

    page = client.get(f"/vacancies/{v.id}").text
    assert "Acme sucht PM" in page and f'hx-post="/chats/{card.id}/messages"' in page
    assert client.get(f"/chats/{card.id}", follow_redirects=False).headers["location"] == \
        f"/vacancies/{v.id}"

    fake.queue(reply("Сделал бы, но 3/5."))
    r = client.post(f"/chats/{card.id}/messages", data={"message": "сделай документы"},
                    headers=HTMX)
    assert "Сделал бы" in r.text
    sent = fake.requests[-1]["messages"]
    assert "Acme sucht PM" in str(sent) and "jobs.example/other" not in str(sent)


@NEEDS_SOFFICE
def test_documents_are_attached_to_the_card(client, outbox, fake, db):
    signed_in(client, outbox)
    fake.queue(
        assessed("Acme", "PM", 5, "prepared", "5/5"),
        tool_call(("l1", "make_letter", LETTER), ("c1", "save_vacancy_cv", SAMPLE_CV)),
        reply("Пакет готов"))
    client.post("/vacancies", data={"text": "https://jobs.example/acme"})
    results = fake.requests[-1]["messages"][-1]["content"]
    assert "PDF: 1 page(s)" in results[0]["content"]
    v = db.scalar(select(Vacancy))
    kinds = {f.kind for f in db.scalars(select(UserFile).where(UserFile.vacancy_id == v.id))}
    assert kinds == {"letter_docx", "letter_pdf", "vcv_docx", "vcv_pdf"}
    feed = client.get("/vacancies").text
    assert "Сопроводительное письмо, PDF" in feed and "Резюме под вакансию, PDF" in feed
    letter_pdf = db.scalar(select(UserFile).where(UserFile.kind == "letter_pdf"))
    assert letter_pdf.filename == "Muller_Letter.pdf"
    assert client.get(f"/files/{letter_pdf.id}").content.startswith(b"%PDF")

    client.post(f"/vacancies/{v.id}/delete")
    assert db.scalar(select(func.count()).select_from(UserFile)
                     .where(UserFile.kind.like("letter%"))) == 0


def test_interview_status_opens_a_story(client, outbox, fake, db):
    signed_in(client, outbox)
    fake.queue(assessed("Acme", "PM", 4, "prepared", "4/5 · Acme"), reply("4/5"))
    client.post("/vacancies", data={"text": "https://jobs.example/acme"})
    v = db.scalar(select(Vacancy))
    r = client.post(f"/vacancies/{v.id}/status", data={"status": "interview"},
                    follow_redirects=False)
    story = db.scalar(select(Chat).where(Chat.kind == "story"))
    assert r.headers["location"] == f"/chats/{story.id}"
    page = client.get(f"/chats/{story.id}").text
    assert "Это история вакансии Acme · PM" in page
    assert "Acme · PM" in client.get("/chats").text
    assert f'href="/chats/{story.id}"' in client.get(f"/vacancies/{v.id}").text

    fake.queue(tool_call(("u1", "vacancy_update", {"status": "offer", "next_step": "Ответить"})),
               reply("Поздравляю!"))
    client.post(f"/chats/{story.id}/messages", data={"message": "мне сделали оффер"},
                headers=HTMX)
    request = fake.requests[-2]
    assert "The vacancy card" in request["system"][-1]["text"]
    assert "4/5 · Acme" in request["system"][-1]["text"]
    db.refresh(v)
    assert v.status == "offer" and v.next_step == "Ответить"
    # The greeting written by the panel is not sent to Claude.
    assert "Это история вакансии" not in str(request["messages"])
    assert db.scalar(select(func.count()).select_from(Chat).where(Chat.kind == "story")) == 1


def test_vacancies_are_private(client, outbox, fake, db):
    invite(client, outbox, "friend@example.com")
    signed_in(client, outbox)
    fake.queue(assessed("Secret", "PM", 4, "prepared", "4/5"), reply("4/5"))
    client.post("/vacancies", data={"text": "https://jobs.example/secret"})
    v = db.scalar(select(Vacancy))
    client.post("/logout")
    signed_in(client, outbox, "friend@example.com")
    assert client.get(f"/vacancies/{v.id}").status_code == 404
    assert client.get(f"/vacancies/{v.id}/card").status_code == 404
    assert client.post(f"/vacancies/{v.id}/status", data={"status": "not_fit"}).status_code == 404
    assert "Secret" not in client.get("/vacancies?f=all").text
    assert "Secret" not in client.get("/tracker.csv").text
    db.refresh(v)
    assert v.status == "prepared"


def test_tracker_csv_and_status_change(client, outbox, fake, db):
    signed_in(client, outbox)
    fake.queue(assessed("Acme", "PM", 4, "prepared", "4/5"), reply("4/5"))
    client.post("/vacancies", data={"text": "https://jobs.example/acme"})
    v = db.scalar(select(Vacancy))
    r = client.post(f"/vacancies/{v.id}/status", data={"status": "applied"},
                    headers={"Referer": "http://testserver/tracker"}, follow_redirects=False)
    assert r.headers["location"] == "/tracker"
    csv_text = client.get("/tracker.csv").text
    assert csv_text.startswith("﻿created,company,role")
    assert "Acme,PM,München,,4,applied,Bewerben bis 30.11" in csv_text
    assert "Подался" in client.get("/tracker").text


def test_export_includes_vacancies(client, outbox, fake, db):
    signed_in(client, outbox)
    fake.queue(assessed("Acme", "PM", 4, "prepared", "4/5"), reply("4/5"))
    client.post("/vacancies", data={"text": "https://jobs.example/acme"})
    data = client.get("/account/export").json()
    assert data["vacancies"][0]["company"] == "Acme" and data["vacancies"][0]["score"] == 4


@NEEDS_SOFFICE
def test_package_folder_has_letter_cv_and_attachments(client, outbox, fake, db):
    import io
    import zipfile
    signed_in(client, outbox)
    r = client.post("/files", data={"in_package": "1"},
                    files={"file": ("Zeugnis.pdf", b"%PDF-1.4 zeugnis", "application/pdf")},
                    follow_redirects=False)
    assert r.status_code == 303
    client.post("/files", files=[("file", ("private.pdf", b"%PDF-1.4 x", "application/pdf")),
                                 ("file", ("scan.png", b"\x89PNG data", "image/png"))])
    assert db.scalar(select(func.count()).select_from(UserFile)) == 3
    assert client.post("/files", files={"file": ("x.exe", b"MZ", "x")},
                       follow_redirects=False).headers["location"] == "/files?error=type"
    assert "✓ в каждый пакет" in client.get("/files").text

    fake.queue(tool_call(("m", "save_cv", SAMPLE_CV)), reply("мастер"))
    client.post("/chats", data={"message": "резюме"})
    fake.queue(assessed("Acme GmbH", "IT-Projektleiter", 5, "prepared", "5/5"),
               tool_call(("l1", "make_letter", LETTER)), reply("Пакет готов"))
    client.post("/vacancies", data={"text": "https://jobs.example/acme"})
    assert "Zeugnis.pdf" in fake.requests[-1]["system"][-1]["text"]
    v = db.scalar(select(Vacancy))
    assert "Скачать пакет папкой" in client.get("/vacancies").text

    r = client.get(f"/vacancies/{v.id}/package.zip")
    assert r.headers["content-type"] == "application/zip"
    assert 'filename="Acme_GmbH_IT-Projektleiter.zip"' in r.headers["content-disposition"]
    names = sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert names == ["Acme_GmbH_IT-Projektleiter/CV_Muller_Projektmanagerin_de.pdf",
                     "Acme_GmbH_IT-Projektleiter/Muller_Letter.pdf",
                     "Acme_GmbH_IT-Projektleiter/Zeugnis.pdf"]


def test_package_needs_documents_and_owner(client, outbox, fake, db):
    invite(client, outbox, "friend@example.com")
    signed_in(client, outbox)
    fake.queue(reply("2/5"))
    client.post("/vacancies", data={"text": "https://jobs.example/x"})
    v = db.scalar(select(Vacancy))
    assert client.get(f"/vacancies/{v.id}/package.zip").status_code == 404
    client.post("/logout")
    signed_in(client, outbox, "friend@example.com")
    assert client.get(f"/vacancies/{v.id}/package.zip").status_code == 404
