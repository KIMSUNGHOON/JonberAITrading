"""Per-broker execution adapters (P5 single execution path).

Each adapter wraps one broker client and exposes the SAME async `place(...)`
returning an ExecutionResult, isolating the incompatible broker order models:

- Kiwoom: place_buy_order / place_sell_order + OrderResponse; mock-vs-live is
  handled inside the client (KIWOOM_IS_MOCK base URL).

Leaf-ish module: imports only the execution models at top level; broker model
imports are local to keep the dependency surface small.

(2026-08-01 Upbit 제거: `UpbitExecutionAdapter`를 제거했다 — UpbitClient가
더 이상 존재하지 않고, 실제 주문 4개 호출부는 전부 KiwoomExecutionAdapter를
직접 생성해 ExecutionService의 market-분기 자체가 프로덕션에서 도달 불가능했다.)
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
