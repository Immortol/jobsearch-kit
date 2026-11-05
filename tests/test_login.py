from datetime import timedelta

from sqlalchemy import select, update

from app.models import LoginToken, User
from tests.conftest import OWNER, invite, last_token, login


def test_root_redirects_to_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_panel_requires_login(client):
    r = client.get("/panel", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_owner_logs_in_and_lands_on_key_page(client, outbox):
    r = client.post("/login", data={"email": "  OWNER@example.com "})
    assert r.status_code == 200
    assert len(outbox.outbox) == 1
    assert outbox.outbox[0].to == OWNER
    token = last_token(outbox)

    # The link itself only shows a confirmation button.
    r = client.get(f"/auth?token={token}")
    assert r.status_code == 200 and 'name="token"' in r.text

    r = client.post("/auth", data={"token": token}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/settings/key"
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie

    r = client.get("/panel")
    assert r.status_code == 200 and OWNER in r.text


def test_uninvited_address_gets_same_answer_but_no_email(client, outbox):
    r = client.post("/login", data={"email": "stranger@example.com"})
    assert r.status_code == 200
    assert "stranger@example.com" in r.text
    assert outbox.outbox == []


def test_invited_user_can_log_in(client, outbox):
    invite(client, outbox, "friend@example.com")
    assert outbox.outbox[-1].to == "friend@example.com"  # invitation email
    login(client, outbox, "friend@example.com")
    assert client.get("/panel").status_code == 200


def test_token_is_single_use(client, outbox):
    client.post("/login", data={"email": OWNER})
    token = last_token(outbox)
    assert client.post("/auth", data={"token": token}, follow_redirects=False).status_code == 303
    client.cookies.clear()
    r = client.post("/auth", data={"token": token}, follow_redirects=False)
    assert r.status_code == 400
    assert client.get(f"/auth?token={token}").status_code == 400


def test_expired_token_rejected(client, outbox, db):
    client.post("/login", data={"email": OWNER})
    token = last_token(outbox)
    db.execute(update(LoginToken).values(expires_at=LoginToken.created_at - timedelta(seconds=1)))
    db.commit()
    assert client.post("/auth", data={"token": token}).status_code == 400


def test_garbage_token_rejected(client):
    assert client.get("/auth?token=nope").status_code == 400
    assert client.post("/auth", data={"token": "nope"}).status_code == 400


def test_tokens_are_stored_hashed(client, outbox, db):
    client.post("/login", data={"email": OWNER})
    token = last_token(outbox)
    stored = db.scalars(select(LoginToken.token_hash)).all()
    assert token not in stored and len(stored[0]) == 64


def test_rate_limit_five_links_per_hour(client, outbox):
    for _ in range(7):
        client.post("/login", data={"email": OWNER})
    assert len(outbox.outbox) == 5


def test_bad_email_rejected(client, outbox):
    r = client.post("/login", data={"email": "not-an-email"})
    assert r.status_code == 400 and outbox.outbox == []


def test_logout_ends_session(client, outbox):
    login(client, outbox, OWNER)
    client.post("/logout")
    assert client.get("/panel", follow_redirects=False).status_code == 303


def test_revoked_invite_cannot_use_pending_link(client, outbox, db):
    invite(client, outbox, "friend@example.com")
    client.post("/login", data={"email": "friend@example.com"})
    token = last_token(outbox)
    login(client, outbox, OWNER)
    client.post("/admin/invites/revoke", data={"email": "friend@example.com"})
    client.post("/logout")
    assert client.post("/auth", data={"token": token}).status_code == 400
    assert db.scalar(select(User).where(User.email == "friend@example.com")) is None


def test_cross_origin_post_blocked(client):
    r = client.post("/login", data={"email": OWNER}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_referrer_policy_keeps_origin_header(client):
    # "no-referrer" makes browsers send "Origin: null" on form posts and breaks every form.
    assert client.get("/login").headers["referrer-policy"] == "same-origin"


def test_null_origin_blocked(client):
    r = client.post("/login", data={"email": OWNER}, headers={"Origin": "null"})
    assert r.status_code == 403


def test_same_origin_post_allowed(client, outbox):
    r = client.post("/login", data={"email": OWNER}, headers={"Origin": "http://testserver"})
    assert r.status_code == 200 and len(outbox.outbox) == 1


def test_email_failure_shows_error(client, outbox, monkeypatch):
    from app.email import EmailError

    def boom(email):
        raise EmailError("down")

    monkeypatch.setattr(outbox, "send", boom)
    r = client.post("/login", data={"email": OWNER})
    assert r.status_code == 503
