"""
Coin Position Endpoints

Endpoints for position management:
- GET /positions - All positions with P&L
- GET /positions/{market} - Single position
- POST /positions/{market}/close - Close position
"""

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, status

from app.api.schemas.coin import (
    CoinPosition,
    CoinPositionListResponse,
    OrderResponse,
)
from app.config import settings
from .helpers import (
    check_api_keys,
    get_upbit_client,
    order_to_response,
    calculate_position_pnl,
    position_to_response,
)

logger = structlog.get_logger()
router = APIRouter()


@router.get("/positions", response_model=CoinPositionListResponse)
async def get_positions():
    """
    Get all open positions with real-time P&L.

    Combines stored positions with live ticker data to calculate
    unrealized profit/loss.

    Returns:
        List of positions with portfolio summary
    """
    from services.storage_service import get_storage_service

    storage = await get_storage_service()
    positions_data = await storage.get_coin_positions()

    if not positions_data:
        return CoinPositionListResponse(
            positions=[],
            total_value_krw=0,
            total_pnl=0,
            total_pnl_pct=0,
        )

    # Get current prices for all position markets
    markets = [p["market"] for p in positions_data]

    async with get_upbit_client() as client:
        try:
            tickers = await client.get_ticker(markets)
            price_map = {t.market: t.trade_price for t in tickers}
        except Exception as e:
            logger.warning("failed_to_fetch_tickers_for_positions", error=str(e))
            price_map = {}

    positions = []
    total_value = 0
    total_pnl = 0
    total_cost = 0

    for p in positions_data:
        market = p["market"]
        current_price = price_map.get(market, p["avg_entry_price"])

        # Calculate P&L metrics
        position_value, unrealized_pnl, _ = calculate_position_pnl(
            p["quantity"], p["avg_entry_price"], current_price
        )
        position_cost = p["quantity"] * p["avg_entry_price"]

        total_value += position_value
        total_cost += position_cost
        total_pnl += unrealized_pnl

        positions.append(position_to_response(p, current_price))

    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    return CoinPositionListResponse(
        positions=positions,
        total_value_krw=total_value,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
    )


@router.get("/positions/{market}", response_model=CoinPosition)
async def get_position(market: str):
    """
    Get a single position by market with real-time P&L.

    Args:
        market: Market code (e.g., KRW-BTC)

    Returns:
        Position details with current P&L
    """
    from services.storage_service import get_storage_service

    market = market.upper()
    storage = await get_storage_service()
    position = await storage.get_coin_position(market)

    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No position found for {market}",
        )

    # Get current price
    current_price = position["avg_entry_price"]
    async with get_upbit_client() as client:
        try:
            tickers = await client.get_ticker([market])
            if tickers:
                current_price = tickers[0].trade_price
        except Exception as e:
            logger.warning("failed_to_fetch_ticker", market=market, error=str(e))

    return position_to_response(position, current_price)


@router.post("/positions/{market}/close", response_model=OrderResponse)
async def close_position(market: str):
    """
    Close a position by selling all holdings at market price.

    Args:
        market: Market code to close

    Returns:
        Order response from the sell order
    """
    from services.storage_service import get_storage_service

    check_api_keys()
    market = market.upper()

    storage = await get_storage_service()
    position = await storage.get_coin_position(market)

    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No position found for {market}",
        )

    quantity = position["quantity"]
    if quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Position quantity is zero for {market}",
        )

    # Check trading mode
    if settings.UPBIT_TRADING_MODE == "paper":
        logger.info(
            "paper_trade_close_position",
            market=market,
            quantity=quantity,
        )

        # Get current price for paper trade
        async with get_upbit_client() as client:
            tickers = await client.get_ticker([market])
            current_price = tickers[0].trade_price if tickers else position["avg_entry_price"]

        # Save closing trade
        trade_id = f"paper-close-{uuid.uuid4()}"
        await storage.save_coin_trade({
            "id": trade_id,
            "session_id": position.get("session_id"),
            "market": market,
            "side": "ask",
            "order_type": "market",
            "price": current_price,
            "volume": quantity,
            "executed_volume": quantity,
            "fee": 0,
            "total_krw": quantity * current_price,
            "state": "done",
            "order_uuid": trade_id,
        })

        # Delete position
        await storage.delete_coin_position(market)

        return OrderResponse(
            uuid=trade_id,
            side="ask",
            ord_type="market",
            price=current_price,
            state="done",
            market=market,
            created_at=datetime.now(timezone.utc),
            volume=quantity,
            remaining_volume=0,
            executed_volume=quantity,
            trades_count=1,
        )

    # Live trading
    async with get_upbit_client() as client:
        try:
            order = await client.place_order(
                market=market,
                side="ask",
                ord_type="market",
                volume=quantity,
            )

            # Save closing trade
            await storage.save_coin_trade({
                "id": f"close-{order.uuid}",
                "session_id": position.get("session_id"),
                "market": market,
                "side": "ask",
                "order_type": "market",
                "price": float(order.price) if order.price else 0,
                "volume": quantity,
                "executed_volume": float(order.executed_volume) if order.executed_volume else quantity,
                "fee": float(order.paid_fee) if order.paid_fee else 0,
                "total_krw": quantity * (float(order.price) if order.price else 0),
                "state": order.state,
                "order_uuid": order.uuid,
            })

            # Delete position if order is done
            if order.state == "done":
                await storage.delete_coin_position(market)

            logger.info("position_closed", market=market, order_uuid=order.uuid)

            return order_to_response(order)

        except HTTPException:
            raise
        except Exception as e:
            logger.error("close_position_failed", market=market, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to close position: {str(e)}",
            )
