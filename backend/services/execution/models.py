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
    """(2026-08-01 Upbit 제거: `COIN` 멤버를 제거했다. 모양은 `MarketType`
    (session_manager·market_hours)과 같게 유지했지만 — 열거형과 `market`
    파라미터를 남기고 멤버만 줄인다 — 근거는 다르다: `MarketType`은 살아있는
    라우트·스토어·컴포넌트 다수를 관통해 붕괴 시 그 블라스트 반경이 위험을
    키운다는 이유였다. `ExecutionService`는 프로덕션 호출부가 0개다(실 주문
    4곳이 전부 `KiwoomExecutionAdapter`를 직접 생성해 이 라우팅 계층 자체를
    우회한다) — 그 블라스트 반경 논리가 여기엔 적용되지 않는다. 남긴 이유는
    이 계층이 애초에 여러 브로커를 겨냥해 설계된 범용 라우팅 추상화이고,
    지금 붕괴시키면 향후 두 번째 브로커가 다시 생길 때 다시 만들어야
    하기 때문 — 재사용성 판단이지 블라스트 반경 판단이 아니다.)"""

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
