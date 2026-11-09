"""The real client against a mocked HTTP transport: request shape and streaming parsing."""

import json
from datetime import date

import httpx2 as httpx

from app import agent
from app.claude import AnthropicClient, ClaudeError, ClaudeFailure


def sse(*events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)


STREAM = sse(
    {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
        "content": [], "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 1, "cache_read_input_tokens": 0}}},
    {"type": "content_block_start", "index": 0, "content_block": {
        "type": "server_tool_use", "id": "srvtoolu_1", "name": "web_fetch", "input": {}}},
    {"type": "content_block_delta", "index": 0, "delta": {
        "type": "input_json_delta", "partial_json": "{\"url\": \"https://jobs.example/1\"}"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1, "content_block": {
        "type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "4/5 "}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Acme"}},
    {"type": "content_block_stop", "index": 1},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
     "usage": {"output_tokens": 42, "server_tool_use": {"web_search_requests": 0}}},
    {"type": "message_stop"},
)


def test_streams_text_and_returns_plain_dict():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-api-key") or request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=STREAM.encode())

    events = []
    client = AnthropicClient(httpx.Client(transport=httpx.MockTransport(handler)))
    params = {"model": "claude-sonnet-5-5", "max_tokens": 100,
              "system": agent.system_prompt([], date(2026, 11, 9)),
              "tools": agent.TOOLS,
              "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]}
    msg = client.create("sk-ant-test", params, lambda k, v: events.append((k, v)))

    assert seen["url"].endswith("/v1/messages") and seen["key"] in ("sk-ant-test", "Bearer sk-ant-test")
    assert seen["body"]["stream"] is True
    assert {t.get("type") for t in seen["body"]["tools"]} >= {"web_fetch_20260318",
                                                              "web_search_20260318"}
    assert events == [("tool", "web_fetch"), ("text", "4/5 "), ("text", "Acme")]
    assert msg["stop_reason"] == "end_turn"
    assert msg["usage"]["input_tokens"] == 1200 and msg["usage"]["output_tokens"] == 42
    assert msg["content"][0] == {"type": "server_tool_use", "id": "srvtoolu_1",
                                 "name": "web_fetch", "input": {"url": "https://jobs.example/1"}}
    assert msg["content"][1]["text"] == "4/5 Acme"
    json.dumps(msg)  # storable as is


def test_api_errors_become_claude_errors():
    def handler(request):
        return httpx.Response(400, json={"type": "error", "error": {
            "type": "invalid_request_error",
            "message": "Your credit balance is too low to access the Anthropic API."}})

    client = AnthropicClient(httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        client.create("sk-ant-test", {"model": "m", "max_tokens": 1, "messages": []},
                      lambda k, v: None)
    except ClaudeError as exc:
        assert exc.failure is ClaudeFailure.BILLING
        assert "sk-ant-test" not in str(exc)
    else:
        raise AssertionError("expected ClaudeError")
