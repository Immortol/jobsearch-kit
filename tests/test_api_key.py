from sqlalchemy import select

from app.anthropic_keys import KeyCheck
from app.models import ApiKey
from app.security import decrypt_secret
from tests.conftest import OWNER, login

KEY = "sk-ant-api03-" + "x" * 80 + "AbCd"


def test_save_key_encrypted(client, outbox, checker, db):
    login(client, outbox, OWNER)
    r = client.post("/settings/key", data={"api_key": f"  {KEY}  "})
    assert r.status_code == 200
    assert "AbCd" in r.text and KEY not in r.text
    assert checker.calls == [KEY]

    row = db.scalar(select(ApiKey))
    assert row.last4 == "AbCd"
    assert KEY.encode() not in row.encrypted_key
    assert decrypt_secret(row.encrypted_key) == KEY

    # After a key is set, login lands on the panel.
    client.post("/logout")
    r = login(client, outbox, OWNER)
    assert r.headers["location"] == "/panel"


def test_invalid_key_not_saved(client, outbox, checker, db):
    login(client, outbox, OWNER)
    checker.result = KeyCheck.INVALID
    r = client.post("/settings/key", data={"api_key": KEY})
    assert r.status_code == 400
    assert db.scalar(select(ApiKey)) is None


def test_unavailable_check_not_saved(client, outbox, checker, db):
    login(client, outbox, OWNER)
    checker.result = KeyCheck.UNAVAILABLE
    assert client.post("/settings/key", data={"api_key": KEY}).status_code == 503
    assert db.scalar(select(ApiKey)) is None


def test_bad_format_not_checked(client, outbox, checker):
    login(client, outbox, OWNER)
    assert client.post("/settings/key", data={"api_key": "hello"}).status_code == 400
    assert checker.calls == []


def test_replace_and_delete_key(client, outbox, db):
    login(client, outbox, OWNER)
    client.post("/settings/key", data={"api_key": KEY})
    client.post("/settings/key", data={"api_key": KEY[:-4] + "WxYz"})
    rows = db.scalars(select(ApiKey)).all()
    assert len(rows) == 1 and rows[0].last4 == "WxYz"
    db.expire_all()
    r = client.post("/settings/key/delete")
    assert r.status_code == 200
    assert db.scalar(select(ApiKey)) is None


def test_htmx_returns_partial(client, outbox):
    login(client, outbox, OWNER)
    r = client.post("/settings/key", data={"api_key": KEY}, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert r.text.lstrip().startswith('<section class="card" id="key-card">')


def test_key_never_logged(client, outbox, caplog):
    login(client, outbox, OWNER)
    with caplog.at_level("DEBUG"):
        client.post("/settings/key", data={"api_key": KEY})
    assert KEY not in caplog.text
