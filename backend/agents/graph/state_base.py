"""Market-agnostic state primitives shared by the 3 trading stacks (P4 consolidation).

Only genuinely-identical pieces live here: SignalType (byte-identical across KR/US/coin)
and the append_list LangGraph reducer. Deliberately NOT here (they differ per market):
the 3 TradeAction enums (KR has 7 position-aware actions; US/coin have 3), the
market-specific models, the signal parsers, and the consensus math (KR uses different
thresholds and excludes the risk agent). Leaf module — imports only enum/typing.
"""

from enum import Enum


class SignalType(str, Enum):
    """Trading signal types."""

    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


def append_list(current: list, new: list) -> list:
    """Append new items to existing list (LangGraph list reducer)."""
    if current is None:
        current = []
    if new is None:
        new = []
    return current + new
