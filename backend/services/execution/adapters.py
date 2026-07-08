"""Per-broker execution adapters (P5 single execution path).

Each adapter wraps one broker client and exposes the SAME async `place(...)`
returning an ExecutionResult, isolating the incompatible broker order models:

- Kiwoom: place_buy_order / place_sell_order + OrderResponse; mock-vs-live is
  handled inside the client (KIWOOM_IS_MOCK base URL).
- Upbit: place_order(side="bid"/"ask", ord_type="limit"/"price"/"market") + Order.

Leaf-ish module: imports only the execution models at top level; broker model
imports are local to keep the dependency surface small.
"""

from __future__ import annotations

from services.execution.models import (
    ExecutionOrderType,
    ExecutionResult,
    ExecutionSide,
)


class KiwoomExecutionAdapter:
    """Adapt the Kiwoom client to the broker-agnostic execution interface."""

    def __init__(self, client):
        self.client = client

    async def place(
        self,
        *,
        ticker: str,
        side: ExecutionSide,
        qty: int,
        price=None,
        order_type: ExecutionOrderType = ExecutionOrderType.LIMIT,
    ) -> ExecutionResult:
        from services.kiwoom.models import OrderType as KiwoomOrderType

        kiwoom_type = (
            KiwoomOrderType.MARKET
            if order_type == ExecutionOrderType.MARKET
            else KiwoomOrderType.LIMIT
        )
        # Market orders send no price; limit orders send the (rounded) price.
        price_arg = (
            int(price) if (order_type == ExecutionOrderType.LIMIT and price) else None
        )
        place_fn = (
            self.client.place_buy_order
            if side == ExecutionSide.BUY
            else self.client.place_sell_order
        )
        resp = await place_fn(
            stk_cd=ticker,
            qty=qty,
            price=price_arg,
            order_type=kiwoom_type,
        )
        return ExecutionResult(
            success=resp.is_success,
            order_id=resp.ord_no or "",
            status="pending" if resp.is_success else "rejected",
            message=resp.return_msg or "",
            raw=resp,
        )


class UpbitExecutionAdapter:
    """Adapt the Upbit client to the broker-agnostic execution interface."""

    def __init__(self, client):
        self.client = client

    async def place(
        self,
        *,
        ticker: str,
        side: ExecutionSide,
        qty,
        price=None,
        order_type: ExecutionOrderType = ExecutionOrderType.LIMIT,
    ) -> ExecutionResult:
        upbit_side = "bid" if side == ExecutionSide.BUY else "ask"
        # Upbit ord_type: limit (price+volume); market buy = "price" (KRW total);
        # market sell = "market" (volume).
        if order_type == ExecutionOrderType.MARKET:
            ord_type = "price" if side == ExecutionSide.BUY else "market"
        else:
            ord_type = "limit"

        order = await self.client.place_order(
            market=ticker,
            side=upbit_side,
            volume=qty,
            price=price,
            ord_type=ord_type,
        )
        return ExecutionResult(
            success=True,
            order_id=getattr(order, "uuid", "") or "",
            status=getattr(order, "state", "pending") or "pending",
            raw=order,
        )
