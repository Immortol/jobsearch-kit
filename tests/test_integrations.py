import httpx
import pytest

from app import anthropic_keys, email
from app.anthropic_keys import KeyCheck, check_api_key, looks_like_api_key


class FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


@pytest.mark.parametrize("status,expected", [
    (200, KeyCheck.OK), (401, KeyCheck.INVALID), (403, KeyCheck.INVALID),
    (500, KeyCheck.UNAVAILABLE), (529, KeyCheck.UNAVAILABLE),
])
def test_check_api_key_maps_statuses(monkeypatch, status, expected):
    seen = {}

    def fake_get(url, headers, params, timeout):
        seen.update(url=url, headers=headers)
        return FakeResponse(status)

    monkeypatch.setattr(anthropic_keys.httpx, "get", fake_get)
    assert check_api_key("sk-ant-test") is expected
    assert seen["url"].endswith("/v1/models")
    assert seen["headers"]["x-api-key"] == "sk-ant-test"


def test_check_api_key_network_error(monkeypatch):
    def fake_get(*a, **kw):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(anthropic_keys.httpx, "get", fake_get)
    assert check_api_key("sk-ant-test") is KeyCheck.UNAVAILABLE


def test_looks_like_api_key():
    assert looks_like_api_key("sk-ant-api03-" + "a" * 40)
    assert not looks_like_api_key("sk-proj-" + "a" * 40)
    assert not looks_like_api_key("sk-ant-a b" + "a" * 40)


def test_resend_sender_payload(monkeypatch):
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json)
        return FakeResponse(200)

    monkeypatch.setattr(email.httpx, "post", fake_post)
    email.ResendSender("re_key", "Jobsearch Kit <login@mail.almoti.com>").send(
        email.Email(to="a@example.com", subject="S", text="T"))
    assert seen["headers"]["Authorization"] == "Bearer re_key"
    assert seen["json"] == {"from": "Jobsearch Kit <login@mail.almoti.com>",
                            "to": ["a@example.com"], "subject": "S", "text": "T"}


def test_resend_sender_error(monkeypatch):
    monkeypatch.setattr(email.httpx, "post", lambda *a, **kw: FakeResponse(422, "bad domain"))
    with pytest.raises(email.EmailError):
        email.ResendSender("k", "f").send(email.Email(to="a@example.com", subject="S", text="T"))


def test_misconfigured_sender_raises():
    with pytest.raises(email.EmailError):
        email.MisconfiguredSender().send(email.Email(to="a@example.com", subject="S", text="T"))


def test_database_url_gets_driver():
    from app.config import Settings
    assert Settings(database_url="postgresql://u:p@h:5432/d").database_url \
        == "postgresql+psycopg://u:p@h:5432/d"
    assert Settings(database_url="postgres://u:p@h/d").database_url \
        == "postgresql+psycopg://u:p@h/d"
