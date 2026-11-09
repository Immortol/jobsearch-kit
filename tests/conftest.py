import os
import re

from cryptography.fernet import Fernet

# Settings are read from the environment on first use, so configure before importing the app.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://jsk:jsk@localhost:5432/jsk_test"
)
if os.environ["DATABASE_URL"].rsplit("/", 1)[-1] == "jsk_dev":
    raise RuntimeError("tests must not run against the dev database")
os.environ["APP_ENV"] = "test"
os.environ["APP_BASE_URL"] = "http://testserver"
os.environ["APP_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["OWNER_EMAIL"] = "Owner@Example.com"
os.environ["RESEND_API_KEY"] = ""
os.environ["UI_LOCALE"] = "ru"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.anthropic_keys import KeyCheck, get_key_checker  # noqa: E402
from app.db import get_engine, get_sessionmaker  # noqa: E402
from app.email import MemorySender, get_email_sender  # noqa: E402
from app.main import app  # noqa: E402

OWNER = "owner@example.com"
TOKEN_RE = re.compile(r"/auth\?token=([A-Za-z0-9_\-]+)")
CODE_RE = re.compile(r"\b(\d{6})\b")


def last_code(outbox) -> str:
    m = CODE_RE.search(outbox.outbox[-1].subject)
    assert m, outbox.outbox[-1].subject
    assert m.group(1) in outbox.outbox[-1].text
    return m.group(1)


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    with get_engine().begin() as conn:
        conn.execute(text(
            "TRUNCATE invites, login_tokens, users, sessions, api_keys, rule_files "
            "RESTART IDENTITY CASCADE"
        ))


class FakeChecker:
    def __init__(self):
        self.result = KeyCheck.OK
        self.calls: list[str] = []

    def __call__(self, api_key: str) -> KeyCheck:
        self.calls.append(api_key)
        return self.result


@pytest.fixture
def outbox() -> MemorySender:
    return MemorySender()


@pytest.fixture
def checker() -> FakeChecker:
    return FakeChecker()


@pytest.fixture
def client(outbox, checker):
    app.dependency_overrides[get_email_sender] = lambda: outbox
    app.dependency_overrides[get_key_checker] = lambda: checker
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def db():
    s = get_sessionmaker()()
    yield s
    s.close()


def last_token(outbox: MemorySender) -> str:
    m = TOKEN_RE.search(outbox.outbox[-1].text)
    assert m, outbox.outbox[-1].text
    return m.group(1)


def login(client: TestClient, outbox: MemorySender, email: str):
    r = client.post("/login", data={"email": email})
    assert r.status_code == 200
    r = client.post("/auth", data={"token": last_token(outbox)}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return r


def invite(client: TestClient, outbox: MemorySender, email: str):
    """Logs in as the owner, invites `email`, logs out."""
    login(client, outbox, OWNER)
    r = client.post("/admin/invites", data={"email": email})
    assert r.status_code == 200
    client.post("/logout")
