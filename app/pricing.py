"""What a Claude call costs, computed from the usage the API returns (decision 0009).

The panel shows users their spend from these numbers. It is an estimate: the authoritative figure is
in the user's Anthropic console (the Usage & Cost API needs an organization admin key, which our
users do not have). Prices: https://platform.claude.com/docs/en/about-claude/pricing (2026-11-09).
"""

from dataclasses import dataclass
from decimal import Decimal

PER_MTOK = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelPrice:
    input: Decimal         # USD per million input tokens
    output: Decimal        # USD per million output tokens
    cache_write: Decimal   # 5-minute cache write
    cache_read: Decimal    # cache hit


PRICES: dict[str, ModelPrice] = {
    "claude-sonnet-5-5": ModelPrice(Decimal("2"), Decimal("10"), Decimal("2.5"), Decimal("0.10")),
    # Prompts up to 100k tokens; our chat prompts stay well below that.
    "claude-haiku-5-5": ModelPrice(Decimal("0.10"), Decimal("0.50"), Decimal("0.125"),
                                   Decimal("0.01")),
}
DEFAULT_PRICE = PRICES["claude-sonnet-5-5"]

WEB_SEARCH_PER_USE = Decimal("0.01")  # $10 per 1,000 searches; web fetch costs only its tokens


def price_for(model: str) -> ModelPrice:
    for name, price in PRICES.items():
        if model.startswith(name):
            return price
    return DEFAULT_PRICE


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


def call_cost(model: str, usage: dict) -> Decimal:
    """Cost of one Messages API response, from its `usage` object (as a dict)."""
    p = price_for(model)
    server = usage.get("server_tool_use") or {}
    total = (
        _int(usage.get("input_tokens")) * p.input
        + _int(usage.get("output_tokens")) * p.output
        + _int(usage.get("cache_creation_input_tokens")) * p.cache_write
        + _int(usage.get("cache_read_input_tokens")) * p.cache_read
    ) / PER_MTOK
    total += _int(server.get("web_search_requests")) * WEB_SEARCH_PER_USE
    return total.quantize(Decimal("0.000001"))
