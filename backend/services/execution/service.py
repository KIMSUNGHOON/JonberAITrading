"""Broker-agnostic ExecutionService — currently unused by any production call site.

No production order path routes through place_order() today. All four live order
paths construct KiwoomExecutionAdapter directly instead: kr_stocks/positions.py,
kr_stocks/orders.py, agents/graph/kr_stock_nodes/execution.py, and
services/trading/order_agent.py. This class exists as a broker-agnostic seam for a
future multi-market dispatcher; treat it as unwired scaffolding, not the execution
path an incident responder should trace live orders through.
"""

from __future__ import annotations

from typing import Optional

from services.execution.adapters import KiwoomExecutionAdapter
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
    ):
        self._by_market = {}
        if kr_stock is not None:
            self._by_market[MarketKind.KR_STOCK] = kr_stock

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
