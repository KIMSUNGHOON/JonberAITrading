"""
Coin Account & Order Endpoints

Endpoints for account and order management:
- GET /accounts - Account balances
- GET /orders - Order list
- GET /orders/{order_id} - Single order
- POST /orders - Create order
- DELETE /orders/{order_id} - Cancel order
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.api.schemas.coin import (
    AccountBalance,
    AccountListResponse,
    OrderCancelResponse,
    OrderListResponse,
    OrderRequest,
    OrderResponse,
)
from app.config import settings
from .helpers import check_api_keys, get_upbit_client, order_to_response

logger = structlog.get_logger()
router = APIRouter()


@router.get("/accounts", response_model=AccountListResponse)
async def get_accounts():
    """
    Get account balances.

    Requires Upbit API keys to be configured.

    Returns:
        List of account balances for all currencies
    """
    check_api_keys()

    async with get_upbit_client() as client:
        try:
            accounts = await client.get_accounts()

            account_balances = [
                AccountBalance(
                    currency=acc.currency,
                    balance=float(acc.balance),
                    locked=float(acc.locked),
                    avg_buy_price=float(acc.avg_buy_price),
                    avg_buy_price_modified=acc.avg_buy_price_modified,
                    unit_currency=acc.unit_currency,
                )
                for acc in accounts
            ]

            # Calculate total KRW value
            total_krw = None
            krw_account = next(
                (a for a in account_balances if a.currency == "KRW"), None
            )
            if krw_account:
                total_krw = krw_account.balance + krw_account.locked

            return AccountListResponse(
                accounts=account_balances,
                total_krw_value=total_krw,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error("get_accounts_failed", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to fetch accounts: {str(e)}",
            )


@router.get("/orders", response_model=OrderListResponse)
async def get_orders(
    market: Optional[str] = Query(
        default=None,
        description="Filter by market code (e.g., KRW-BTC)",
    ),
    state: Optional[str] = Query(
        default=None,
        description="Filter by state (wait, watch, done, cancel)",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=100,
        description="Maximum number of orders to return",
    ),
):
    """
    Get list of orders.

    Requires Upbit API keys to be configured.
    """
    check_api_keys()

    async with get_upbit_client() as client:
        try:
            orders = await client.get_orders(
                market=market.upper() if market else None,
                state=state,
                limit=limit,
            )

            order_responses = [order_to_response(order) for order in orders]

            return OrderListResponse(
                orders=order_responses,
                total=len(order_responses),
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error("get_orders_failed", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to fetch orders: {str(e)}",
            )


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str):
    """
    Get a single order by UUID.

    Requires Upbit API keys to be configured.
    """
    check_api_keys()

    async with get_upbit_client() as client:
        try:
            order = await client.get_order(uuid=order_id)

            if not order:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Order {order_id} not found",
                )

            return order_to_response(order)

        except HTTPException:
            raise
        except Exception as e:
            logger.error("get_order_failed", order_id=order_id, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to fetch order: {str(e)}",
            )


@router.post("/orders", response_model=OrderResponse)
async def create_order(request: OrderRequest):
    """
    Create a new order.

    Requires Upbit API keys to be configured.
    """
    check_api_keys()

    # Validate order parameters
    if request.ord_type == "limit":
        if not request.price or not request.volume:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Limit orders require both price and volume",
            )
    elif request.ord_type == "price":
        if not request.price:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Market buy orders require price (total KRW amount)",
            )
    elif request.ord_type == "market":
        if not request.volume:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Market sell orders require volume",
            )

    # Check trading mode
    if settings.UPBIT_TRADING_MODE == "paper":
        logger.info(
            "paper_trade_order",
            market=request.market,
            side=request.side,
            ord_type=request.ord_type,
            price=request.price,
            volume=request.volume,
        )
        # Return simulated order for paper trading
        return OrderResponse(
            uuid=f"paper-{uuid.uuid4()}",
            side=request.side,
            ord_type=request.ord_type,
            price=request.price,
            state="done" if request.ord_type in ["price", "market"] else "wait",
            market=request.market.upper(),
            created_at=datetime.now(timezone.utc),
            volume=request.volume,
            remaining_volume=0 if request.ord_type in ["price", "market"] else request.volume,
            executed_volume=request.volume if request.ord_type in ["price", "market"] else 0,
            trades_count=1 if request.ord_type in ["price", "market"] else 0,
        )

    # Live trading
    async with get_upbit_client() as client:
        try:
            order = await client.place_order(
                market=request.market.upper(),
                side=request.side,
                ord_type=request.ord_type,
                price=request.price,
                volume=request.volume,
            )

            logger.info(
                "order_created",
                uuid=order.uuid,
                market=order.market,
                side=order.side,
            )

            return order_to_response(order)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "create_order_failed",
                market=request.market,
                error=str(e),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to create order: {str(e)}",
            )


@router.delete("/orders/{order_id}", response_model=OrderCancelResponse)
async def cancel_order(order_id: str):
    """
    Cancel an order.

    Requires Upbit API keys to be configured.
    Only orders in 'wait' state can be cancelled.
    """
    check_api_keys()

    # Check for paper trading
    if order_id.startswith("paper-"):
        logger.info("paper_trade_cancel", order_id=order_id)
        return OrderCancelResponse(
            uuid=order_id,
            side="bid",
            ord_type="limit",
            state="cancel",
            market="KRW-PAPER",
        )

    async with get_upbit_client() as client:
        try:
            order = await client.cancel_order(uuid=order_id)

            logger.info("order_cancelled", uuid=order.uuid)

            return OrderCancelResponse(
                uuid=order.uuid,
                side=order.side,
                ord_type=order.ord_type,
                price=float(order.price) if order.price else None,
                state=order.state,
                market=order.market,
                volume=float(order.volume) if order.volume else None,
                remaining_volume=float(order.remaining_volume)
                if order.remaining_volume
                else None,
                executed_volume=float(order.executed_volume)
                if order.executed_volume
                else None,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error("cancel_order_failed", order_id=order_id, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to cancel order: {str(e)}",
            )
