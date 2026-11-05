"""Checking a user's Anthropic API key with a free request before storing it."""

import enum
from typing import Protocol

import httpx

from app.config import get_settings


class KeyCheck(enum.Enum):
    OK = "ok"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


class KeyChecker(Protocol):
    def __call__(self, api_key: str) -> KeyCheck: ...


def check_api_key(api_key: str) -> KeyCheck:
    """GET /v1/models costs nothing and fails with 401 for a bad key."""
    try:
        r = httpx.get(
            f"{get_settings().anthropic_api_url}/v1/models",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            params={"limit": 1},
            timeout=10,
        )
    except httpx.HTTPError:
        return KeyCheck.UNAVAILABLE
    if r.status_code == 200:
        return KeyCheck.OK
    if r.status_code in (401, 403):
        return KeyCheck.INVALID
    return KeyCheck.UNAVAILABLE


def get_key_checker() -> KeyChecker:
    return check_api_key


def looks_like_api_key(value: str) -> bool:
    return value.startswith("sk-ant-") and 20 <= len(value) <= 300 and value.isascii() \
        and " " not in value
