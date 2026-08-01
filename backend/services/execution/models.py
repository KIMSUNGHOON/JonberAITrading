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
    """(2026-08-01 Upbit 제거: `COIN` 멤버를 제거했다. `MarketType`(session_manager)
    ·`MarketType`(market_hours)와 같은 원칙 — 열거형과 `market` 파라미터는 남기고
    멤버만 줄인다. 라우트/서비스 시그니처를 붕괴시키지 않기 위함.)"""

    KR_STOCK = "kr_stock"


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
