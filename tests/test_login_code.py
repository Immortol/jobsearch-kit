from datetime import timedelta

from sqlalchemy import select, update

from app.models import LoginToken
from tests.conftest import OWNER, invite, last_code, last_token


def _ask(client, email=OWNER):
    r = client.post("/login", data={"email": email})
    assert r.status_code == 200
    assert 'name="code"' in r.text  # the "check your email" page has the code form
    return r


def test_sign_in_with_code(client, outbox):
    _ask(client)
    code = last_code(outbox)
    r = client.post("/auth/code", data={"email": OWNER, "code": code}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/settings/key"
    assert client.get("/panel").status_code == 200


def test_code_tolerates_spaces_and_case_of_email(client, outbox):
    _ask(client)
    code = last_code(outbox)
    r = client.post("/auth/code", data={"email": " Owner@Example.com ",
                                        "code": f"{code[:3]} {code[3:]}"},
                    follow_redirects=False)
    assert r.status_code == 303


def test_code_and_link_are_one_sign_in(client, outbox):
    _ask(client)
    code, token = last_code(outbox), last_token(outbox)
    assert client.post("/auth/code", data={"email": OWNER, "code": code},
                       follow_redirects=False).status_code == 303
    client.cookies.clear()
    assert client.post("/auth", data={"token": token}).status_code == 400
    assert client.post("/auth/code", data={"email": OWNER, "code": code}).status_code == 400


def test_link_uses_up_code(client, outbox):
    _ask(client)
    code, token = last_code(outbox), last_token(outbox)
    assert client.post("/auth", data={"token": token}, follow_redirects=False).status_code == 303
    client.cookies.clear()
    assert client.post("/auth/code", data={"email": OWNER, "code": code}).status_code == 400


def test_wrong_code_rejected_and_counted(client, outbox, db):
    _ask(client)
    code = last_code(outbox)
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    r = client.post("/auth/code", data={"email": OWNER, "code": wrong})
    assert r.status_code == 400 and 'name="code"' in r.text
    assert db.scalar(select(LoginToken.code_attempts)) == 1
    # The right code still works after one mistake.
    assert client.post("/auth/code", data={"email": OWNER, "code": code},
                       follow_redirects=False).status_code == 303


def test_five_wrong_codes_burn_the_email(client, outbox):
    _ask(client)
    code, token = last_code(outbox), last_token(outbox)
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    for _ in range(5):
        assert client.post("/auth/code", data={"email": OWNER, "code": wrong}).status_code == 400
    assert client.post("/auth/code", data={"email": OWNER, "code": code}).status_code == 400
    assert client.post("/auth", data={"token": token}).status_code == 400


def test_code_only_for_its_address(client, outbox):
    invite(client, outbox, "friend@example.com")
    _ask(client, OWNER)
    code = last_code(outbox)
    r = client.post("/auth/code", data={"email": "friend@example.com", "code": code})
    assert r.status_code == 400


def test_expired_code_rejected(client, outbox, db):
    _ask(client)
    code = last_code(outbox)
    db.execute(update(LoginToken).values(expires_at=LoginToken.created_at - timedelta(seconds=1)))
    db.commit()
    assert client.post("/auth/code", data={"email": OWNER, "code": code}).status_code == 400


def test_uninvited_address_gets_code_form_but_cannot_sign_in(client, outbox):
    _ask(client, "stranger@example.com")
    assert outbox.outbox == []
    r = client.post("/auth/code", data={"email": "stranger@example.com", "code": "123456"})
    assert r.status_code == 400


def test_code_stored_hashed(client, outbox, db):
    _ask(client)
    code = last_code(outbox)
    stored = db.scalar(select(LoginToken.code_hash))
    assert stored and code not in stored and len(stored) == 64


def test_garbage_code_rejected(client, outbox):
    _ask(client)
    for bad in ["", "abc", "12345", "1234567"]:
        assert client.post("/auth/code", data={"email": OWNER, "code": bad}).status_code == 400
