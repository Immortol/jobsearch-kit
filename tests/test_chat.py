from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import chat as chats
from app.claude import ClaudeError, ClaudeFailure, get_claude_client
from app.main import app
from app.models import ChatMessage, UsageRecord, User
from tests.conftest import (
    OWNER, FakeClaude, HeldRunner, InlineRunner, invite, login, reply, tool_call,
)

KEY = "sk-ant-api03-" + "k" * 80 + "WxYz"
HTMX = {"HX-Request": "true"}


@pytest.fixture
def fake():
    f = FakeClaude()
    app.dependency_overrides[get_claude_client] = lambda: f
    return f


@pytest.fixture
def runner(client):
    r = InlineRunner()
    app.dependency_overrides[chats.get_runner] = lambda: r
    return r


def signed_in_with_key(client, outbox, email=OWNER):
    login(client, outbox, email)
    assert client.post("/settings/key", data={"api_key": KEY}).status_code == 200


def test_chat_needs_a_key(client, outbox, fake, runner):
    login(client, outbox, OWNER)
    page = client.get("/chats")
    assert "/settings/key" in page.text and 'name="message"' not in page.text
    assert client.post("/chats", data={"message": "привет"}).status_code == 400
    assert fake.requests == []


def test_vacancy_message_gets_an_assessment(client, outbox, fake, runner, db):
    signed_in_with_key(client, outbox)
    fake.queue(tool_call(("t1", "load_skill", {"name": "jobsearch-vacancy"})),
               reply("**4/5** · Acme · PM\nПочему: задачи совпадают"))

    r = client.post("/chats", data={"message": "вот вакансия https://jobs.example/1"},
                    follow_redirects=False)
    assert r.status_code == 303
    page = client.get(r.headers["location"])
    assert page.status_code == 200
    assert "<strong>4/5</strong> · Acme · PM" in page.text
    assert "вот вакансия https://jobs.example/1" in page.text
    assert fake.keys == [KEY, KEY]  # the user's own key

    # Cost: (1000*2 + 50*10) / 1M + (1000*2 + 100*10) / 1M = 0.0055
    assert "Этот ответ: $0.006" in page.text
    assert "Потрачено: $0.006 в этом месяце · $0.006 всего" in page.text
    assert db.scalar(select(func.count()).select_from(UsageRecord)) == 2

    chat_title = page.text.split('<h1 class="chat-title">')[1].split("</h1>")[0]
    assert chat_title == "вот вакансия https://jobs.example/1"
    assert chat_title in client.get("/chats").text


def test_follow_up_sends_the_whole_history(client, outbox, fake, runner, db):
    signed_in_with_key(client, outbox)
    fake.queue(reply("первый ответ"))
    chat_url = client.post("/chats", data={"message": "раз"}, follow_redirects=False) \
        .headers["location"]
    fake.queue(reply("второй ответ"))
    r = client.post(f"{chat_url}/messages", data={"message": "два"}, headers=HTMX)
    assert r.status_code == 200
    assert "два" in r.text and "второй ответ" in r.text
    sent = fake.requests[-1]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[1]["content"][0]["text"] == "первый ответ"


def test_running_reply_is_polled_until_done(client, outbox, fake, db):
    held = HeldRunner()
    app.dependency_overrides[chats.get_runner] = lambda: held
    signed_in_with_key(client, outbox)
    chat_url = client.post("/chats", data={"message": "оцени"}, follow_redirects=False) \
        .headers["location"]
    reply_msg = db.scalar(select(ChatMessage).where(ChatMessage.role == "assistant"))
    poll = f"{chat_url}/messages/{reply_msg.id}"

    page = client.get(chat_url)
    assert f'hx-get="{poll}"' in page.text and "Думаю" in page.text
    # A second message while the reply runs is refused.
    r = client.post(f"{chat_url}/messages", data={"message": "ещё"}, headers=HTMX)
    assert r.status_code == 409 and "Подожди" in r.text

    fake.queue(reply("готово"))
    held.run_all()
    r = client.get(poll)
    assert "готово" in r.text and "hx-get" not in r.text
    assert '<p id="spend" class="spend" hx-swap-oob="true">' in r.text


def test_interrupted_reply_is_marked(client, outbox, fake, db):
    held = HeldRunner()
    app.dependency_overrides[chats.get_runner] = lambda: held
    signed_in_with_key(client, outbox)
    chat_url = client.post("/chats", data={"message": "оцени"}, follow_redirects=False) \
        .headers["location"]
    held.jobs.clear()
    chats.LIVE.clear()  # what a server restart leaves behind
    page = client.get(chat_url)
    assert "перезапуска сервера" in page.text
    assert 'name="message"' in page.text and "disabled" not in page.text.split("composer")[-1] \
        .split("</form>")[0]


def test_billing_error_is_explained(client, outbox, fake, runner):
    signed_in_with_key(client, outbox)
    fake.queue(ClaudeError(ClaudeFailure.BILLING, "credit balance is too low"))
    chat_url = client.post("/chats", data={"message": "оцени"}, follow_redirects=False) \
        .headers["location"]
    assert "Пополни баланс" in client.get(chat_url).text


def test_chats_are_private(client, outbox, fake, runner, db):
    invite(client, outbox, "friend@example.com")
    signed_in_with_key(client, outbox)
    fake.queue(reply("секрет владельца"))
    chat_url = client.post("/chats", data={"message": "оцени"}, follow_redirects=False) \
        .headers["location"]
    reply_id = db.scalar(select(ChatMessage.id).where(ChatMessage.role == "assistant"))
    client.post("/logout")

    signed_in_with_key(client, outbox, "friend@example.com")
    assert client.get(chat_url).status_code == 404
    assert client.get(f"{chat_url}/messages/{reply_id}").status_code == 404
    assert client.post(f"{chat_url}/messages", data={"message": "x"}).status_code == 404
    assert "секрет" not in client.get("/chats").text
    assert "Потрачено: $0.00 в этом месяце · $0.00 всего" in client.get("/panel").text


def test_spend_survives_chat_deletion_and_counts_months(client, outbox, fake, runner, db):
    signed_in_with_key(client, outbox)
    owner = db.scalar(select(User).where(User.email == OWNER))
    db.add(UsageRecord(user_id=owner.id, model="claude-sonnet-5-5", usage={},
                       cost_usd=Decimal("1.5"), created_at=datetime(2026, 1, 15, tzinfo=UTC)))
    db.commit()
    fake.queue(reply("ок", usage={"input_tokens": 100_000, "output_tokens": 10_000}))
    chat_url = client.post("/chats", data={"message": "оцени"}, follow_redirects=False) \
        .headers["location"]
    assert client.post(f"{chat_url}/delete", follow_redirects=False).status_code == 303
    assert client.get(chat_url).status_code == 404
    # 0.2 + 0.1 = 0.30 this month; 1.80 in total.
    assert "Потрачено: $0.30 в этом месяце · $1.80 всего" in client.get("/chats").text

    s = chats.spend(db, owner, now=datetime(2026, 1, 20, tzinfo=UTC))
    assert s.month == Decimal("1.5")


def test_export_includes_chats_and_spend(client, outbox, fake, runner):
    signed_in_with_key(client, outbox)
    fake.queue(reply("оценка 4/5"))
    client.post("/chats", data={"message": "оцени"})
    data = client.get("/account/export").json()
    assert data["chats"][0]["messages"][1]["text"] == "оценка 4/5"
    assert Decimal(data["spend_usd"]["total"]) > 0


def test_assistant_markdown_is_escaped(client, outbox, fake, runner):
    signed_in_with_key(client, outbox)
    fake.queue(reply('<script>alert(1)</script> [x](javascript:alert(1))'))
    chat_url = client.post("/chats", data={"message": "оцени"}, follow_redirects=False) \
        .headers["location"]
    page = client.get(chat_url).text
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page
    assert 'href="javascript' not in page


def test_account_deletion_removes_chats_and_usage(client, outbox, fake, runner, db):
    signed_in_with_key(client, outbox)
    fake.queue(reply("ок"))
    client.post("/chats", data={"message": "оцени"})
    client.post("/account/delete", data={"confirm": "yes"})
    for model in (ChatMessage, UsageRecord):
        assert db.scalar(select(func.count()).select_from(model)) == 0
