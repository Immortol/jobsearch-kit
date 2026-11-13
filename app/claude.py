"""The one place that talks to the Claude Messages API (decision 0009).

The agent works with plain dicts (the JSON the API speaks), so tests can replace this client with a
scripted fake and every message can be stored in the database as is.
"""

import enum
import logging
from collections.abc import Callable
from typing import Protocol

import anthropic
import httpx2

from app.config import get_settings

log = logging.getLogger("app.claude")


class ClaudeFailure(enum.Enum):
    INVALID_KEY = "invalid_key"
    NO_PERMISSION = "no_permission"
    BILLING = "billing"          # no credit left, or the workspace spend limit is reached
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"  # network problems, Anthropic overloaded or down
    TOO_LARGE = "too_large"
    OTHER = "other"


class ClaudeError(Exception):
    def __init__(self, failure: ClaudeFailure, detail: str = ""):
        super().__init__(f"{failure.value}: {detail}")
        self.failure = failure
        self.detail = detail


# on_event("text", delta) for streamed answer text, on_event("tool", name) when a tool call starts.
EventCallback = Callable[[str, str], None]


class ClaudeClient(Protocol):
    def create(self, api_key: str, params: dict, on_event: EventCallback) -> dict:
        """Sends one Messages API request, streaming progress through `on_event`; returns the
        final message as a dict (`content`, `stop_reason`, `usage`, `model`)."""
        ...


_BILLING_WORDS = ("credit balance", "spend limit", "usage limit", "billing")


def classify(exc: Exception) -> ClaudeFailure:
    if isinstance(exc, anthropic.AuthenticationError):
        return ClaudeFailure.INVALID_KEY
    if isinstance(exc, anthropic.APIStatusError):
        body = exc.body if isinstance(exc.body, dict) else {}
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        kind = str(error.get("type", ""))
        message = str(error.get("message", exc.message)).lower()
        if kind == "billing_error" or any(w in message for w in _BILLING_WORDS):
            return ClaudeFailure.BILLING
        if isinstance(exc, anthropic.PermissionDeniedError):
            return ClaudeFailure.NO_PERMISSION
        if isinstance(exc, anthropic.RateLimitError):
            return ClaudeFailure.RATE_LIMIT
        if exc.status_code == 413 or "prompt is too long" in message:
            return ClaudeFailure.TOO_LARGE
        if exc.status_code >= 500:
            return ClaudeFailure.UNAVAILABLE
        return ClaudeFailure.OTHER
    if isinstance(exc, anthropic.APIConnectionError):  # includes timeouts
        return ClaudeFailure.UNAVAILABLE
    return ClaudeFailure.OTHER


class AnthropicClient:
    def __init__(self, http_client: "httpx2.Client | None" = None):
        self.http_client = http_client  # tests pass a mock transport

    def create(self, api_key: str, params: dict, on_event: EventCallback) -> dict:
        client = anthropic.Anthropic(
            api_key=api_key, base_url=get_settings().anthropic_api_url, max_retries=2,
            timeout=300, http_client=self.http_client,
        )
        try:
            with client.messages.stream(**params) as stream:
                for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        on_event("text", event.delta.text)
                    elif event.type == "content_block_start" and event.content_block.type in (
                            "tool_use", "server_tool_use"):
                        on_event("tool", event.content_block.name)
                message = stream.get_final_message()
        except anthropic.APIError as exc:
            # The exception text never contains the key; keep only status and message.
            log.warning("Claude API error %s: %s", getattr(exc, "status_code", "-"),
                        str(getattr(exc, "message", ""))[:500])
            raise ClaudeError(classify(exc), getattr(exc, "message", "")[:300]) from None
        return message.model_dump(mode="json", exclude_none=True)


def get_claude_client() -> ClaudeClient:
    return AnthropicClient()
