"""
Korean Stock Account & Order Endpoints

Endpoints for account and order management:
- GET /accounts - Account balances
- GET /orders - Order list
- POST /orders - Create order
- DELETE /orders/{order_id} - Cancel order
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.api.schemas.kr_stocks import (
    KRStockAccountResponse,
    KRStockCashBalance,
    KRStockHolding,
    KRStockOrderCancelResponse,
    KRStockOrderListResponse,
    KRStockOrderRequest,
    KRStockOrderResponse,
)
from app.config import settings
from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
from .helpers import check_kiwoom_api_keys

logger = structlog.get_logger()
router = APIRouter()


@router.get("/accounts", response_model=KRStockAccountResponse)
async def get_accounts():
    """
    Get account information including cash balance and holdings.

    Requires Kiwoom API keys to be configured.

    Returns:
        Account balances and stock holdings
    """
    check_kiwoom_api_keys()

    client = await get_shared_kiwoom_client_async()

    try:
        # Get cash balance
        cash_balance = await client.get_cash_balance()

        # Get account balance (holdings)
        account_balance = await client.get_account_balance()

        # Map CashBalance model attributes to schema
        cash = KRStockCashBalance(
            deposit=cash_balance.dnca_tot_amt,
            orderable_amount=cash_balance.ord_psbl_amt,
            withdrawable_amount=cash_balance.sttl_psbk_amt,
        )

        # Map Holding model attributes to schema
        holdings = [
            KRStockHolding(
                stk_cd=h.stk_cd,
                stk_nm=h.stk_nm,
                quantity=h.hldg_qty,
                avg_buy_price=h.avg_buy_prc,
                current_price=h.cur_prc,
                eval_amount=h.evlu_amt,
                profit_loss=h.evlu_pfls_amt,
                profit_loss_rate=h.evlu_pfls_rt,
            )
            for h in account_balance.holdings
        ]

        # Calculate stock evaluation from individual holdings
        stock_eval_amount = sum(h.evlu_amt for h in account_balance.holdings)

        return KRStockAccountResponse(
            cash=cash,
            holdings=holdings,
            total_eval_amount=stock_eval_amount,
            total_profit_loss=account_balance.evlu_pfls_amt,
            total_profit_loss_rate=account_balance.evlu_pfls_rt,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_accounts_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"계좌 조회 실패: {str(e)}",
        )


@router.get("/orders", response_model=KRStockOrderListResponse)
async def get_orders(
    stk_cd: Optional[str] = Query(
        default=None,
        description="Filter by stock code",
    ),
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by status (pending, partial, completed, cancelled)",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of orders to return",
    ),
):
    """
    Get list of orders.

    Requires Kiwoom API keys to be configured.

    Args:
        stk_cd: Filter by stock code
        status_filter: Filter by order status
        limit: Maximum number of orders (default 50)

    Returns:
        List of orders
    """
    check_kiwoom_api_keys()

    client = await get_shared_kiwoom_client_async()

    try:
        # Use get_pending_orders for pending/partial orders
        pending_orders = await client.get_pending_orders()

        orders = []
        for order in pending_orders[:limit]:
            # Apply stock code filter
            if stk_cd and order.stk_cd != stk_cd:
                continue

            # Determine order status
            order_status = "pending"
            if order.ccld_qty > 0 and order.rmn_qty > 0:
                order_status = "partial"
            elif order.rmn_qty == 0:
                order_status = "completed"

            # Apply status filter
            if status_filter and order_status != status_filter:
                continue

            # Determine side from buy_sell_tp (1: buy, 2: sell)
            side = "buy" if order.buy_sell_tp in ["1", "01", "매수"] else "sell"

            # Parse datetime from ord_dt + ord_tm
            try:
                created_at = datetime.strptime(
                    f"{order.ord_dt}{order.ord_tm}",
                    "%Y%m%d%H%M%S"
                )
            except (ValueError, TypeError):
                created_at = datetime.now(timezone.utc)

            orders.append(
                KRStockOrderResponse(
                    order_id=order.ord_no,
                    stk_cd=order.stk_cd,
                    stk_nm=order.stk_nm,
                    side=side,
                    ord_type="limit",  # Pending orders are typically limit orders
                    price=order.ord_uv,
                    quantity=order.ord_qty,
                    executed_quantity=order.ccld_qty,
                    remaining_quantity=order.rmn_qty,
                    status=order_status,
                    created_at=created_at,
                )
            )

        return KRStockOrderListResponse(orders=orders, total=len(orders))

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_orders_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"주문 조회 실패: {str(e)}",
        )


@router.post("/orders", response_model=KRStockOrderResponse)
async def create_order(request: KRStockOrderRequest):
    """
    Create a new order.

    Requires Kiwoom API keys to be configured.

    Order types:
    - limit: Limit order (지정가) - requires price
    - market: Market order (시장가)

    Args:
        request: Order request

    Returns:
        Created order details
    """
    check_kiwoom_api_keys()

    # Validate order parameters
    if request.ord_type == "limit" and not request.price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="지정가 주문은 가격이 필요합니다",
        )

    # Check trading mode
    is_mock = getattr(settings, "KIWOOM_IS_MOCK", True)

    if is_mock:
        logger.info(
            "mock_trade_order",
            stk_cd=request.stk_cd,
            side=request.side,
            ord_type=request.ord_type,
            price=request.price,
            quantity=request.quantity,
        )
        # Return simulated order for mock trading
        return KRStockOrderResponse(
            order_id=f"mock-{uuid.uuid4()}",
            stk_cd=request.stk_cd,
            stk_nm=None,
            side=request.side,
            ord_type=request.ord_type,
            price=request.price,
            quantity=request.quantity,
            executed_quantity=request.quantity if request.ord_type == "market" else 0,
            remaining_quantity=0 if request.ord_type == "market" else request.quantity,
            status="completed" if request.ord_type == "market" else "pending",
            created_at=datetime.now(timezone.utc),
        )

    # Live trading
    client = await get_shared_kiwoom_client_async()

    try:
        from services.kiwoom import OrderRequest as KiwoomOrderRequest, OrderType

        order_type = OrderType.BUY if request.side == "buy" else OrderType.SELL
        if request.ord_type == "market":
            order_type = (
                OrderType.MARKET_BUY
                if request.side == "buy"
                else OrderType.MARKET_SELL
            )

        kiwoom_request = KiwoomOrderRequest(
            stk_cd=request.stk_cd,
            order_type=order_type,
            quantity=request.quantity,
            price=request.price or 0,
        )

        order = await client.place_order(kiwoom_request)

        logger.info(
            "order_created",
            order_id=order.order_id,
            stk_cd=request.stk_cd,
            side=request.side,
        )

        return KRStockOrderResponse(
            order_id=order.order_id,
            stk_cd=request.stk_cd,
            stk_nm=order.stk_nm if hasattr(order, "stk_nm") else None,
            side=request.side,
            ord_type=request.ord_type,
            price=request.price,
            quantity=request.quantity,
            executed_quantity=0,
            remaining_quantity=request.quantity,
            status="pending",
            created_at=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "create_order_failed",
            stk_cd=request.stk_cd,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"주문 생성 실패: {str(e)}",
        )


@router.delete("/orders/{order_id}", response_model=KRStockOrderCancelResponse)
async def cancel_order(order_id: str):
    """
    Cancel an order.

    Requires Kiwoom API keys to be configured.
    Only orders in 'pending' or 'partial' status can be cancelled.

    Args:
        order_id: Order ID to cancel

    Returns:
        Cancelled order details
    """
    check_kiwoom_api_keys()

    # Check for mock trading
    if order_id.startswith("mock-"):
        logger.info("mock_trade_cancel", order_id=order_id)
        return KRStockOrderCancelResponse(
            order_id=order_id,
            stk_cd="000000",
            status="cancelled",
            cancelled_quantity=0,
        )

    client = await get_shared_kiwoom_client_async()

    try:
        result = await client.cancel_order(order_id)

        logger.info("order_cancelled", order_id=order_id)

        return KRStockOrderCancelResponse(
            order_id=order_id,
            stk_cd=result.stk_cd if hasattr(result, "stk_cd") else "000000",
            status="cancelled",
            cancelled_quantity=result.cancelled_quantity
            if hasattr(result, "cancelled_quantity")
            else 0,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("cancel_order_failed", order_id=order_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"주문 취소 실패: {str(e)}",
        )
