"""Market-agnostic state primitives, originally shared by 3 trading stacks
(P4 consolidation) — US (removed R2, 2026-07-11) and coin (removed 2026-08-01
Upbit 제거) are both gone now, leaving only KR stock, but the module is kept
as-is since nothing requires collapsing it into kr_stock_state.py.

Only genuinely-identical pieces live here: SignalType and the append_list
LangGraph reducer. Deliberately NOT here (they differed per market and KR's
7 position-aware TradeAction values are the only enum left): the
market-specific models, the signal parsers, and the consensus math (KR uses
different thresholds and excludes the risk agent). Leaf module — imports
only enum/typing.
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
