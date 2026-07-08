"""Broker-agnostic execution models (P5 single execution path).

One result shape + one side/order-type vocabulary across every broker, so all
order-placement call sites speak the same language and the per-broker differences
live only in the adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class MarketKind(str, Enum):
    KR_STOCK = "kr_stock"
    COIN = "coin"


class ExecutionSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class ExecutionOrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


@dataclass
class ExecutionResult:
    """Broker-agnostic result of a single order placement."""

    success: bool
    order_id: str = ""
    status: str = "pending"  # pending | filled | rejected | simulated
    message: str = ""
    raw: Any = None  # the broker-native response object, for callers that need it
