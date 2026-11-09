import json

from sqlalchemy import func, select

from app.models import ApiKey, Invite, RuleFile, User, UserSession
from tests.conftest import OWNER, invite, login


def test_rules_crud(client, outbox):
    login(client, outbox, OWNER)
    r = client.post("/rules", data={"name": "01_Facts.md"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/rules/01_Facts.md"

    r = client.post("/rules/01_Facts.md", data={"content": "Факты\r\nстрока"},
                    headers={"HX-Request": "true"})
    assert r.status_code == 200
    page = client.get("/rules/01_Facts.md")
    assert "Факты\nстрока" in page.text
    assert "01_Facts.md" in client.get("/rules").text

    r = client.post("/rules/01_Facts.md/delete", follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/rules/01_Facts.md").status_code == 404


def test_rule_name_validated(client, outbox):
    login(client, outbox, OWNER)
    for bad in ["../x.md", "facts.txt", "a b.md", ""]:
        assert client.post("/rules", data={"name": bad}).status_code == 400


def test_rules_are_private(client, outbox):
    invite(client, outbox, "friend@example.com")
    login(client, outbox, OWNER)
    client.post("/rules", data={"name": "01_Facts.md"})
    client.post("/rules/01_Facts.md", data={"content": "owner secret"})
    client.post("/logout")
    login(client, outbox, "friend@example.com")
    assert client.get("/rules/01_Facts.md").status_code == 404
    assert client.post("/rules/01_Facts.md", data={"content": "x"}).status_code == 404


def test_export(client, outbox):
    login(client, outbox, OWNER)
    client.post("/rules", data={"name": "03_Strategy.md"})
    client.post("/rules/03_Strategy.md", data={"content": "план"})
    r = client.get("/account/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    data = json.loads(r.content)
    assert data["email"] == OWNER
    assert data["rules"][0]["content"] == "план"


def test_delete_account_removes_everything(client, outbox, db):
    login(client, outbox, OWNER)
    client.post("/settings/key", data={"api_key": "sk-ant-api03-" + "y" * 60})
    client.post("/rules", data={"name": "01_Facts.md"})
    assert client.post("/account/delete", data={}).status_code == 400
    r = client.post("/account/delete", data={"confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303
    for model in (User, UserSession, ApiKey, RuleFile):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert client.get("/panel", follow_redirects=False).status_code == 303


def test_invites_owner_only(client, outbox):
    invite(client, outbox, "friend@example.com")
    login(client, outbox, "friend@example.com")
    assert client.get("/admin/invites").status_code == 404
    assert client.post("/admin/invites", data={"email": "x@example.com"}).status_code == 404
    assert "/admin/invites" not in client.get("/panel").text


def test_invite_list_and_revoke(client, outbox, db):
    invite(client, outbox, "Friend@Example.com")
    assert db.get(Invite, "friend@example.com") is not None
    login(client, outbox, "friend@example.com")
    client.post("/logout")

    login(client, outbox, OWNER)
    page = client.get("/admin/invites").text
    assert "friend@example.com" in page

    r = client.post("/admin/invites", data={"email": "friend@example.com"})
    assert r.status_code == 200  # already invited: no duplicate
    assert db.scalar(select(func.count()).select_from(Invite)) == 1

    client.post("/admin/invites/revoke", data={"email": "friend@example.com"})
    db.expire_all()
    assert db.get(Invite, "friend@example.com") is None
    assert db.scalar(select(User).where(User.email == "friend@example.com")) is None


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}
