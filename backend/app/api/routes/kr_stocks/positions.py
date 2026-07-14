"""
Korean Stock Position Endpoints

Endpoints for position management:
- GET /positions - All positions
- GET /positions/{stk_cd} - Single position
- POST /positions/{stk_cd}/close - Close position
"""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, status

from app.api.schemas.kr_stocks import (
    KRStockOrderResponse,
    KRStockPosition,
    KRStockPositionListResponse,
)
from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
from .helpers import check_kiwoom_api_keys

logger = structlog.get_logger()
router = APIRouter()


@router.get("/positions", response_model=KRStockPositionListResponse)
async def get_positions():
    """
    Get all open positions with real-time P&L.

    Source: broker account balance holdings (kt00004, `get_account_balance()`)
    — the SAME source Operations '보유' reads (app/api/routes/trading.py,
    mapping mirrored from kr_stocks/orders.py:63-76), so the two surfaces can
    never diverge on quantity/avg/current price/P&L for the same holding.

    Previously this endpoint called `storage.get_kr_stock_positions()`, a
    method that has never existed on StorageService — there is no KR
    position writer anywhere in the backend. Every call raised
    AttributeError, which was caught and silently turned into an empty list,
    so KR positions were ALWAYS empty regardless of actual broker holdings.

    On broker fetch failure this degrades honestly to an empty portfolio
    (logged, not raised) rather than fabricating positions or non-zero
    totals.

    Returns:
        List of positions with portfolio summary
    """
    try:
        client = await get_shared_kiwoom_client_async()
        balance = await client.get_account_balance()
    except Exception as e:
        logger.error("failed_to_fetch_kr_positions", error=str(e))
        return KRStockPositionListResponse(
            positions=[],
            total_value_krw=0,
            total_pnl=0,
            total_pnl_pct=0,
        )

    positions = []
    total_value = 0
    total_pnl = 0
    total_cost = 0

    for h in balance.holdings:
        quantity = h.hldg_qty
        avg_entry = h.avg_buy_prc

        total_value += h.evlu_amt
        total_pnl += h.evlu_pfls_amt
        total_cost += quantity * avg_entry

        positions.append(
            KRStockPosition(
                stk_cd=h.stk_cd,
                stk_nm=h.stk_nm,
                quantity=quantity,
                avg_entry_price=avg_entry,
                current_price=h.cur_prc,
                # Broker-computed P&L (kt00004) — same fields Operations
                # '보유' reads directly off the Holding model
                # (trading.py:1391-1398). Pass-through, not independently
                # recomputed, so the two surfaces can never disagree.
                unrealized_pnl=h.evlu_pfls_amt,
                unrealized_pnl_pct=h.evlu_pfls_rt,
                # SL/TP for KR positions stays coordinator-managed (Operations
                # '보유' enrichment + PUT .../stop-loss|take-profit, P1-T7) —
                # out of scope here; this list endpoint doesn't own it.
                stop_loss=None,
                take_profit=None,
                session_id=None,
                created_at=datetime.now(timezone.utc),
            )
        )

    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    return KRStockPositionListResponse(
        positions=positions,
        total_value_krw=int(total_value),
        total_pnl=int(total_pnl),
        total_pnl_pct=total_pnl_pct,
    )


@router.get("/positions/{stk_cd}", response_model=KRStockPosition)
async def get_position(stk_cd: str):
    """
    Get a single position by stock code with real-time P&L.

    Source: broker account balance holdings (kt00004, `get_account_balance()`)
    — the SAME lookup and field mapping as GET /positions (list, above), just
    filtered to one ticker. Previously this called
    `storage.get_kr_stock_position()`, a method that has never existed on
    StorageService, so every lookup 404'd even for a ticker the list endpoint
    (and Operations '보유') showed as held. Not held in the broker balance ->
    honest 404, never a fabricated position.

    Args:
        stk_cd: Stock code

    Returns:
        Position details with current P&L
    """
    try:
        client = await get_shared_kiwoom_client_async()
        balance = await client.get_account_balance()
    except Exception as e:
        logger.error("failed_to_fetch_kr_position", stk_cd=stk_cd, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"포지션 조회 실패: {str(e)}",
        )

    holding = next((h for h in balance.holdings if h.stk_cd == stk_cd), None)
    if holding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{stk_cd} 포지션을 찾을 수 없습니다",
        )

    return KRStockPosition(
        stk_cd=holding.stk_cd,
        stk_nm=holding.stk_nm,
        quantity=holding.hldg_qty,
        avg_entry_price=holding.avg_buy_prc,
        current_price=holding.cur_prc,
        # Broker-computed P&L (kt00004), pass-through like the list handler
        # — same reasoning as get_positions() above.
        unrealized_pnl=holding.evlu_pfls_amt,
        unrealized_pnl_pct=holding.evlu_pfls_rt,
        stop_loss=None,
        take_profit=None,
        session_id=None,
        created_at=datetime.now(timezone.utc),
    )


@router.post("/positions/{stk_cd}/close", response_model=KRStockOrderResponse)
async def close_position(stk_cd: str):
    """
    Close a position by selling the full held quantity at market price.

    A KR "position" is broker balance (kt00004 `get_account_balance()`), NOT
    a storage row — there is no KR position writer anywhere in the backend,
    so deleting a storage row here was architecturally wrong (and dead code:
    `storage.get_kr_stock_position` / `delete_kr_stock_position` don't exist,
    always AttributeError'd). Closing = looking up the held quantity from the
    same broker balance the list/single-GET handlers use, then placing a
    full-quantity market SELL through the single execution path
    (`KiwoomExecutionAdapter`, the exact primitive `orders.py` create_order's
    live branch uses) — never a locally fabricated success response.
    Mock-vs-live is handled inside the Kiwoom client itself (KIWOOM_IS_MOCK
    base URL, see services/execution/adapters.py), so paper mode hits
    Kiwoom's mock server like every other order.

    Args:
        stk_cd: Stock code to close

    Returns:
        Order response from the sell order
    """
    check_kiwoom_api_keys()

    client = await get_shared_kiwoom_client_async()

    try:
        balance = await client.get_account_balance()
    except Exception as e:
        logger.error(
            "failed_to_fetch_kr_position_for_close", stk_cd=stk_cd, error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"포지션 조회 실패: {str(e)}",
        )

    holding = next((h for h in balance.holdings if h.stk_cd == stk_cd), None)
    if holding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{stk_cd} 포지션을 찾을 수 없습니다",
        )

    quantity = holding.hldg_qty
    if quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{stk_cd} 포지션 수량이 0입니다",
        )

    try:
        from services.execution import (
            KiwoomExecutionAdapter,
            ExecutionSide,
            ExecutionOrderType,
        )

        result = await KiwoomExecutionAdapter(client).place(
            ticker=stk_cd,
            side=ExecutionSide.SELL,
            qty=quantity,
            price=None,
            order_type=ExecutionOrderType.MARKET,
        )

        logger.info("position_closed", stk_cd=stk_cd, order_id=result.order_id)

        return KRStockOrderResponse(
            order_id=result.order_id,
            stk_cd=stk_cd,
            stk_nm=holding.stk_nm,
            side="sell",
            ord_type="market",
            price=None,
            quantity=quantity,
            executed_quantity=0,
            remaining_quantity=quantity,
            # KRStockOrderResponse.status has no "rejected" literal (only
            # pending/partial/completed/cancelled) — "cancelled" is the
            # honest fit for "the broker did not accept this order",
            # never a fabricated "pending"/"completed" success.
            status="pending" if result.success else "cancelled",
            created_at=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("close_position_failed", stk_cd=stk_cd, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"포지션 청산 실패: {str(e)}",
        )
