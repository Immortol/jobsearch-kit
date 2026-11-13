"""Stage 4b: Google connection, Drive folders, tracker sheet, Gmail drafts (decision 0012)."""

import base64
import email
import email.policy
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import func, select

from app import chat as chats
from app import google, google_sync
from app.claude import get_claude_client
from app.config import get_settings
from app.main import app
from app.models import GoogleAccount, User, Vacancy
from tests.conftest import OWNER, FakeClaude, InlineRunner, login, reply, tool_call
from tests.test_vacancies import LETTER, NEEDS_SOFFICE, assessed

KEY = "sk-ant-api03-" + "k" * 80 + "WxYz"


def id_token(mail):
    payload = base64.urlsafe_b64encode(json.dumps({"email": mail}).encode()).decode().rstrip("=")
    return f"e30.{payload}.sig"


class FakeGoogle:
    """A tiny in-memory Google: OAuth, Drive files, Sheets values, Gmail drafts."""

    def __init__(self):
        self.files: dict[str, dict] = {}
        self.sheets: dict[str, list] = {}
        self.drafts: list[email.message.Message] = []
        self.revoked: list[str] = []
        self.scope = " ".join(google.SCOPES)
        self.n = 0

    def _id(self):
        self.n += 1
        return f"f{self.n}"

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        path = request.url.path
        if url.startswith(google.TOKEN_URL):
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["authorization_code"]:
                assert form["redirect_uri"] == [google.redirect_uri()]
                return httpx.Response(200, json={
                    "access_token": "at", "refresh_token": "rt-secret", "expires_in": 3600,
                    "scope": self.scope, "id_token": id_token("me@gmail.com")})
            return httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
        if url.startswith(google.REVOKE_URL):
            self.revoked.append(parse_qs(request.content.decode())["token"][0])
            return httpx.Response(200)
        assert request.headers["authorization"] == "Bearer at"
        if url.startswith(google.DRIVE_UPLOAD):
            body = request.content
            meta = json.loads(body.split(b"\r\n\r\n", 1)[1].split(b"\r\n", 1)[0])
            data = body.split(b"\r\n\r\n", 2)[2].rsplit(b"\r\n--", 1)[0]
            file_id = path.rsplit("/", 1)[-1] if request.method == "PATCH" else self._id()
            f = self.files.setdefault(file_id, {"parents": meta.get("parents", [])})
            f.update(name=meta["name"], data=data, trashed=False)
            return httpx.Response(200, json={"id": file_id})
        if url.startswith(google.DRIVE_FILES):
            if request.method == "POST":
                meta = json.loads(request.content)
                file_id = self._id()
                self.files[file_id] = {**meta, "trashed": False, "parents": meta.get("parents", [])}
                return httpx.Response(200, json={"id": file_id})
            if path.endswith("/files"):
                parent = request.url.params["q"].split("'")[1]
                return httpx.Response(200, json={"files": [
                    {"id": i, "name": f["name"]} for i, f in self.files.items()
                    if parent in f["parents"] and not f["trashed"]]})
            file_id = path.rsplit("/", 1)[-1]
            if file_id not in self.files:
                return httpx.Response(404)
            return httpx.Response(200, json={"id": file_id, "trashed": self.files[file_id]["trashed"]})
        if url.startswith(google.SHEETS):
            sheet_id = path.split("/")[3]
            if path.endswith(":clear"):
                self.sheets[sheet_id] = []
            else:
                self.sheets[sheet_id] = json.loads(request.content)["values"]
            return httpx.Response(200, json={})
        if url.startswith(google.GMAIL_DRAFTS):
            raw = json.loads(request.content)["message"]["raw"]
            self.drafts.append(email.message_from_bytes(base64.urlsafe_b64decode(raw),
                                                        policy=email.policy.default))
            return httpx.Response(200, json={"id": "d1", "message": {"id": "m1"}})
        raise AssertionError(f"unexpected {request.method} {url}")

    def folder(self, name):
        return next(i for i, f in self.files.items() if f["name"] == name and not f["trashed"])

    def in_folder(self, folder_id):
        return sorted(f["name"] for f in self.files.values() if folder_id in f["parents"])


@pytest.fixture
def g(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(google, "client_factory",
                        lambda: google.Google(httpx.Client(transport=httpx.MockTransport(
                            fake.handler))))
    monkeypatch.setattr(google, "_token_cache", {})
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")
    get_settings.cache_clear()
    jobs = []
    monkeypatch.setattr(google_sync, "submit", jobs.append)
    monkeypatch.setattr(google_sync, "SYNC_DELAY", 0)
    fake.jobs = jobs
    yield fake
    get_settings.cache_clear()


@pytest.fixture
def fake_claude():
    f = FakeClaude()
    app.dependency_overrides[get_claude_client] = lambda: f
    app.dependency_overrides[chats.get_runner] = lambda: InlineRunner()
    return f


def run_jobs(g):
    while g.jobs:
        g.jobs.pop(0)()


def connect(client, outbox):
    login(client, outbox, OWNER)
    client.post("/settings/key", data={"api_key": KEY})
    r = client.get("/google/connect", follow_redirects=False)
    target = urlsplit(r.headers["location"])
    params = parse_qs(target.query)
    assert target.netloc == "accounts.google.com"
    assert set(params["scope"][0].split()) == set(google.SCOPES)
    assert params["access_type"] == ["offline"] and params["prompt"] == ["consent"]
    assert "gmail.send" not in params["scope"][0] and "gmail.readonly" not in params["scope"][0]
    return client.get(f"/google/callback?code=c1&state={params['state'][0]}",
                      follow_redirects=False)


def test_connect_stores_encrypted_token_and_makes_the_layout(client, outbox, g, db):
    r = connect(client, outbox)
    assert r.headers["location"] == "/settings/google?connected=1"
    acc = db.scalar(select(GoogleAccount))
    assert acc.email == "me@gmail.com" and b"rt-secret" not in acc.encrypted_refresh_token
    root = g.folder("Jobsearch")
    assert g.in_folder(root) == ["Applications", "Jobsearch — tracker"]
    assert g.sheets[acc.sheet_id][1][:3] == ["Date", "Company", "Role"]
    page = client.get("/settings/google").text
    assert "Подключено: me@gmail.com" in page and acc.sheet_id in page
    assert "Подключено: me@gmail.com" in client.get("/panel").text


def test_callback_checks_state_and_scopes(client, outbox, g, db):
    login(client, outbox, OWNER)
    client.get("/google/connect")
    r = client.get("/google/callback?code=c1&state=forged", follow_redirects=False)
    assert r.headers["location"] == "/settings/google?error=state"
    g.scope = "openid email https://www.googleapis.com/auth/drive.file"  # Gmail unticked
    r = connect(client, outbox)
    assert r.headers["location"] == "/settings/google?error=scopes"
    assert g.revoked == ["rt-secret"]
    assert db.scalar(select(func.count()).select_from(GoogleAccount)) == 0
    assert "обе галочки" in client.get("/settings/google?error=scopes").text


def test_disconnect_and_account_deletion_revoke(client, outbox, g, db):
    connect(client, outbox)
    client.post("/google/disconnect")
    assert g.revoked == ["rt-secret"]
    assert db.scalar(select(func.count()).select_from(GoogleAccount)) == 0
    connect(client, outbox)
    client.post("/account/delete", data={"confirm": "yes"})
    assert g.revoked == ["rt-secret", "rt-secret"]


@NEEDS_SOFFICE
def test_card_package_goes_to_drive_and_tracker_to_sheet(client, outbox, g, fake_claude, db):
    connect(client, outbox)
    client.post("/files", data={"in_package": "1"},
                files={"file": ("Zeugnis.pdf", b"%PDF-1.4 z", "application/pdf")})
    fake_claude.queue(assessed("Acme", "PM", 5, "prepared", "5/5"),
                      tool_call(("l1", "make_letter", LETTER)), reply("Пакет готов"))
    client.post("/vacancies", data={"text": "https://jobs.example/acme"})
    assert "Google (Gmail drafts, Drive folder): connected" in \
        fake_claude.requests[0]["system"][-1]["text"]
    run_jobs(g)
    v = db.scalar(select(Vacancy))
    db.refresh(v)
    assert g.in_folder(v.drive_folder_id) == ["Muller_Letter.pdf", "Zeugnis.pdf"]
    assert g.files[v.drive_folder_id]["name"] == "Acme – PM"
    assert g.files[v.drive_folder_id]["parents"] == [g.folder("Applications")]
    acc = db.scalar(select(GoogleAccount))
    assert g.sheets[acc.sheet_id][2][1:3] == ["Acme", "PM"]

    # Syncing again updates the files in place, no duplicates.
    client.post(f"/vacancies/{v.id}/drive")
    assert g.in_folder(v.drive_folder_id) == ["Muller_Letter.pdf", "Zeugnis.pdf"]
    assert "Обновить папку в Drive" in client.get(f"/vacancies/{v.id}").text

    client.post(f"/vacancies/{v.id}/status", data={"status": "applied"})
    run_jobs(g)
    assert g.sheets[acc.sheet_id][2][6] == "applied"


@NEEDS_SOFFICE
def test_gmail_draft_has_the_package_attached(client, outbox, g, fake_claude, db):
    connect(client, outbox)
    fake_claude.queue(
        assessed("Acme", "PM", 5, "prepared", "5/5"),
        tool_call(("l1", "make_letter", LETTER)),
        tool_call(("d1", "gmail_draft", {"to": "jobs@acme.example",
                                         "subject": "Bewerbung als PM",
                                         "body": "Guten Tag,\nanbei meine Unterlagen."})),
        reply("Черновик в Gmail"))
    client.post("/vacancies", data={"text": "https://jobs.example/acme"})
    result = fake_claude.requests[-1]["messages"][-1]["content"][0]["content"]
    assert "Draft created in Gmail (not sent)" in result
    msg = g.drafts[0]
    assert msg["To"] == "jobs@acme.example" and msg["Subject"] == "Bewerbung als PM"
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert names == ["Muller_Letter.pdf"]
    v = db.scalar(select(Vacancy))
    db.refresh(v)
    assert v.draft_url.endswith("compose=m1")
    assert "Черновик в Gmail" in client.get(f"/vacancies/{v.id}").text


def test_gmail_draft_without_google_falls_back(client, outbox, fake_claude, db):
    login(client, outbox, OWNER)
    client.post("/settings/key", data={"api_key": KEY})
    fake_claude.queue(tool_call(("d1", "gmail_draft", {"subject": "S", "body": "B"})),
                      reply("Текст письма ниже"))
    client.post("/vacancies", data={"text": "https://jobs.example/acme"})
    result = fake_claude.requests[-1]["messages"][-1]["content"][0]
    assert result["is_error"] and "not connected" in result["content"]
    assert "Google (Gmail drafts, Drive folder): not connected" in \
        fake_claude.requests[0]["system"][-1]["text"]


def test_revoked_access_is_shown(client, outbox, g, db, monkeypatch):
    connect(client, outbox)
    user = db.scalar(select(User).where(User.email == OWNER))

    def refused(request):
        return httpx.Response(400, json={"error": "invalid_grant"})
    monkeypatch.setattr(google, "client_factory",
                        lambda: google.Google(httpx.Client(transport=httpx.MockTransport(refused))))
    monkeypatch.setattr(google, "_token_cache", {})
    assert google_sync.sync_tracker(db, user) is False
    db.commit()
    assert "Google отозвал доступ" in client.get("/settings/google").text
