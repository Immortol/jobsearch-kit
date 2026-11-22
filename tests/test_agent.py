from datetime import date
from decimal import Decimal

import anthropic
import httpx2 as httpx
import pytest

from app import agent, rules, skills
from app.agent import Progress, build_history, run_reply
from app.claude import ClaudeError, ClaudeFailure, classify
from app.models import User
from app.pricing import call_cost
from tests.conftest import FakeClaude, reply, tool_call


@pytest.fixture
def user(db):
    u = User(email="u@example.com")
    db.add(u)
    db.flush()
    return u


class Recorder(Progress):
    def __init__(self):
        self.texts, self.labels, self.costs = [], [], []

    def text(self, delta):
        self.texts.append(delta)

    def status(self, label):
        self.labels.append(label)

    def call_done(self, model, usage, cost):
        self.costs.append(cost)


def run(db, user, fake, history=None):
    progress = Recorder()
    history = history or [{"role": "user", "content": [{"type": "text", "text": "вакансия"}]}]
    result = run_reply(client=fake, api_key="sk-ant-test", model="claude-sonnet-5-5", db=db,
                       user=user, history=history, progress=progress, today=date(2026, 11, 9))
    return result, progress


def test_vacancy_flow_loads_skill_reads_rules_and_answers(db, user):
    rules.write_rule(db, user, "01_Facts.md", "Факт: 5 лет PM")
    fetch = {
        "content": [
            {"type": "server_tool_use", "id": "srv1", "name": "web_fetch",
             "input": {"url": "https://jobs.example/1"}},
            {"type": "web_fetch_tool_result", "tool_use_id": "srv1",
             "content": {"type": "web_fetch_result", "url": "https://jobs.example/1",
                         "content": {"type": "document",
                                     "source": {"type": "text", "media_type": "text/plain",
                                                "data": "Project Manager"}}}},
            {"type": "text", "text": "4/5 · Acme · PM"},
        ],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 2000, "output_tokens": 200, "cache_read_input_tokens": 10000},
    }
    fake = FakeClaude(
        tool_call(("t1", "load_skill", {"name": "jobsearch-vacancy"}),
                  ("t2", "read_rules", {"names": ["01_Facts.md", "03_Strategy.md"]})),
        fetch,
    )
    result, progress = run(db, user, fake)

    assert result.error is None and not result.hit_step_limit
    assert result.text == "4/5 · Acme · PM"
    assert fake.keys == ["sk-ant-test", "sk-ant-test"]

    first = fake.requests[0]
    assert first["model"] == "claude-sonnet-5-5"
    assert "jobsearch-vacancy" in first["system"][0]["text"]
    assert "01_Facts.md" in first["system"][1]["text"] and "2026-11-09" in first["system"][1]["text"]
    assert {t["name"] for t in first["tools"]} >= {"web_search", "web_fetch", "read_rules"}
    # The conversation is cached up to the last user turn.
    assert first["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}

    results = fake.requests[1]["messages"][-1]["content"]
    assert results[0]["tool_use_id"] == "t1" and "Шаг 4" in results[0]["content"]
    assert "references/letter.md" in results[0]["content"]
    assert "Факт: 5 лет PM" in results[1]["content"]
    assert "03_Strategy.md ===\n(this file does not exist)" in results[1]["content"]

    # Stored turn: assistant tool call, tool results, final assistant message (with server tools).
    assert [m["role"] for m in result.api_messages] == ["assistant", "user", "assistant"]
    assert result.api_messages[2]["content"][1]["type"] == "web_fetch_tool_result"
    assert "Reading the instructions" in progress.labels and "Opening a page" in progress.labels
    assert result.cost == sum(progress.costs) == Decimal("0.0095")


def test_step_limit_stops_the_loop(db, user):
    fake = FakeClaude(*[tool_call((f"t{i}", "read_rules", {})) for i in range(agent.MAX_STEPS)])
    result, _ = run(db, user, fake)
    assert result.hit_step_limit
    assert len(fake.requests) == agent.MAX_STEPS
    # Ends with tool results, so the history stays valid for the next message.
    assert result.api_messages[-1]["role"] == "user"


def test_pause_turn_is_continued(db, user):
    paused = {"content": [{"type": "server_tool_use", "id": "s1", "name": "web_search",
                           "input": {"query": "Acme"}}],
              "stop_reason": "pause_turn", "usage": {"input_tokens": 10, "output_tokens": 5}}
    fake = FakeClaude(paused, reply("готово"))
    result, _ = run(db, user, fake)
    assert result.text == "готово"
    assert fake.requests[1]["messages"][-1]["role"] == "assistant"


def test_api_error_keeps_spend_and_drops_the_broken_turn(db, user):
    fake = FakeClaude(tool_call(("t1", "read_rules", {})),
                      ClaudeError(ClaudeFailure.BILLING, "credit balance is too low"))
    result, progress = run(db, user, fake)
    assert result.error is ClaudeFailure.BILLING
    assert result.api_messages == []
    assert len(progress.costs) == 1 and result.cost > 0


def test_write_rules_logs_changes(db, user):
    fake = FakeClaude(
        tool_call(("t1", "write_rules", {"name": "03_Strategy.md", "content": "Стратегия",
                                         "mode": "replace", "summary": "добавил стратегию"})),
        tool_call(("t2", "write_rules", {"name": "03_Strategy.md", "content": "Ещё",
                                         "mode": "append", "summary": "дописал"})),
        tool_call(("t3", "write_rules", {"name": "CHANGELOG.md", "content": "x",
                                         "mode": "replace", "summary": "x"}),
                  ("t4", "write_rules", {"name": "../evil.md", "content": "x",
                                         "mode": "replace", "summary": "x"})),
        reply("Обновил."),
    )
    run(db, user, fake)
    assert rules.read_rule(db, user, "03_Strategy.md").content == "Стратегия\n\nЕщё"
    log = rules.read_rule(db, user, "CHANGELOG.md").content
    assert "03_Strategy.md: добавил стратегию" in log and "03_Strategy.md: дописал" in log
    errors = fake.requests[3]["messages"][-1]["content"]
    assert all(r["is_error"] for r in errors)
    assert rules.read_rule(db, user, "evil.md") is None


def test_unknown_tool_and_skill_are_errors(db, user):
    fake = FakeClaude(tool_call(("t1", "load_skill", {"name": "jobsearch-scanner"}),
                                ("t2", "rm_rf", {})), reply("ок"))
    run(db, user, fake)
    results = fake.requests[1]["messages"][-1]["content"]
    assert [r.get("is_error") for r in results] == [True, True]


def test_history_merges_consecutive_turns():
    history = build_history([
        [{"role": "user", "content": [{"type": "text", "text": "a"}]}],
        [{"role": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "x",
                                            "input": {}}]},
         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1",
                                       "content": "r"}]}],
        [{"role": "user", "content": [{"type": "text", "text": "b"}]}],
    ])
    assert [m["role"] for m in history] == ["user", "assistant", "user"]
    assert [b["type"] for b in history[2]["content"]] == ["tool_result", "text"]


def test_call_cost():
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000,
             "cache_creation_input_tokens": 200_000, "cache_read_input_tokens": 1_000_000,
             "server_tool_use": {"web_search_requests": 3}}
    # 2 + 1 + 0.5 + 0.1 + 0.03
    assert call_cost("claude-sonnet-5-5", usage) == Decimal("3.63")
    assert call_cost("claude-haiku-5-5", {"input_tokens": 1_000_000}) == Decimal("0.1")
    assert call_cost("claude-sonnet-5-5", {}) == 0


def test_skills_catalog_and_files():
    names = [s.name for s in skills.catalog()]
    assert names == ["jobsearch-setup", "jobsearch-vacancy"]
    assert skills.load_skill("jobsearch-scanner") is None
    assert skills.read_skill_file("jobsearch-vacancy", "references/letter.md").strip()
    for bad in ["../jobsearch-setup/SKILL.md", "/etc/passwd", "references/../../../CLAUDE.md"]:
        assert skills.read_skill_file("jobsearch-vacancy", bad) is None


def _status_error(cls, status, body):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.anthropic.com"))
    return cls("error", response=response, body=body)


def test_classify_api_errors():
    assert classify(_status_error(anthropic.AuthenticationError, 401, {})) \
        is ClaudeFailure.INVALID_KEY
    assert classify(_status_error(anthropic.BadRequestError, 400, {"error": {
        "type": "invalid_request_error",
        "message": "Your credit balance is too low to access the Anthropic API."}})) \
        is ClaudeFailure.BILLING
    assert classify(_status_error(anthropic.RateLimitError, 429, {})) is ClaudeFailure.RATE_LIMIT
    assert classify(_status_error(anthropic.InternalServerError, 529, {})) \
        is ClaudeFailure.UNAVAILABLE
    assert classify(_status_error(anthropic.PermissionDeniedError, 403, {})) \
        is ClaudeFailure.NO_PERMISSION
    assert classify(anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))) \
        is ClaudeFailure.UNAVAILABLE


def test_history_drops_earlier_web_results_and_citations():
    history = build_history([
        [{"role": "user", "content": [{"type": "text", "text": "найди"}]}],
        [{"role": "assistant", "content": [
            {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "x"}},
            {"type": "web_search_tool_result", "tool_use_id": "s1", "content": [
                {"type": "web_search_result", "url": "https://x", "title": "t",
                 "encrypted_content": "e"}]},
            {"type": "text", "text": "Нашёл", "citations": [
                {"type": "web_search_result_location", "url": "https://x", "title": "t",
                 "encrypted_index": "i", "cited_text": "c"}]},
            {"type": "tool_use", "id": "t1", "name": "save_cv", "input": {}},
        ]},
         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                       "content": "ok"}]},
         {"role": "assistant", "content": [
             {"type": "server_tool_use", "id": "s2", "name": "web_fetch", "input": {}},
             {"type": "web_fetch_tool_result", "tool_use_id": "s2", "content": {}},
             {"type": "code_execution_tool_result", "tool_use_id": "s3", "content": {}}]}],
        [{"role": "user", "content": [{"type": "text", "text": "заполнил"}]}],
    ])
    assert history[1]["content"] == [
        {"type": "text", "text": "Нашёл"},
        {"type": "tool_use", "id": "t1", "name": "save_cv", "input": {}},
    ]
    assert history[3] == {"role": "assistant",
                          "content": [{"type": "text", "text": "(looked things up on the web)"}]}
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant", "user"]
