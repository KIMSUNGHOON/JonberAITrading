"""Broker-agnostic ExecutionService (P5 single execution path).

Every order-placement call site routes an order through place_order(); the service
dispatches to the adapter registered for that market. Per-broker order models live
only in the adapters, so this is the ONE execution path.
"""

from __future__ import annotations

from typing import Optional

from services.execution.adapters import (
    KiwoomExecutionAdapter,
    UpbitExecutionAdapter,
)
from services.execution.models import (
    ExecutionOrderType,
    ExecutionResult,
    ExecutionSide,
    MarketKind,
)


class ExecutionService:
    """Route an order to the right broker adapter. Construct with the adapters
    available (each wraps its already-built broker client)."""

    def __init__(
        self,
        *,
        kr_stock: Optional[KiwoomExecutionAdapter] = None,
        coin: Optional[UpbitExecutionAdapter] = None,
    ):
        self._by_market = {}
        if kr_stock is not None:
            self._by_market[MarketKind.KR_STOCK] = kr_stock
        if coin is not None:
            self._by_market[MarketKind.COIN] = coin

    async def place_order(
        self,
        *,
        market: MarketKind,
        ticker: str,
        side: ExecutionSide,
        qty,
        price=None,
        order_type: ExecutionOrderType = ExecutionOrderType.LIMIT,
    ) -> ExecutionResult:
        adapter = self._by_market.get(market)
        if adapter is None:
            raise ValueError(f"No execution adapter registered for market {market}")
        return await adapter.place(
            ticker=ticker,
            side=side,
            qty=qty,
            price=price,
            order_type=order_type,
        )
