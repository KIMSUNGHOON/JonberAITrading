"""
Korean Stock Position Endpoints

Endpoints for position management:
- GET /positions - All positions
- GET /positions/{stk_cd} - Single position
- POST /positions/{stk_cd}/close - Close position
"""

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, status

from app.api.schemas.kr_stocks import (
    KRStockOrderResponse,
    KRStockPosition,
    KRStockPositionListResponse,
)
from app.config import settings
from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
from .helpers import check_kiwoom_api_keys

logger = structlog.get_logger()
router = APIRouter()


@router.get("/positions", response_model=KRStockPositionListResponse)
async def get_positions():
    """
    Get all open positions with real-time P&L.

    Returns:
        List of positions with portfolio summary
    """
    from services.storage_service import get_storage_service

    storage = await get_storage_service()

    # Try to get positions from storage first
    try:
        positions_data = await storage.get_kr_stock_positions()
    except AttributeError:
        # If method doesn't exist yet, return empty
        positions_data = []

    if not positions_data:
        return KRStockPositionListResponse(
            positions=[],
            total_value_krw=0,
            total_pnl=0,
            total_pnl_pct=0,
        )

    # Get current prices
    client = await get_shared_kiwoom_client_async()
    price_map = {}

    try:
        for p in positions_data:
            try:
                info = await client.get_stock_info(p["stk_cd"])
                if info:
                    price_map[p["stk_cd"]] = info.cur_prc
            except Exception:
                pass
    except Exception as e:
        logger.warning("failed_to_fetch_prices_for_positions", error=str(e))

    positions = []
    total_value = 0
    total_pnl = 0
    total_cost = 0

    for p in positions_data:
        stk_cd = p["stk_cd"]
        quantity = p["quantity"]
        avg_entry = p["avg_entry_price"]
        current_price = price_map.get(stk_cd, avg_entry)

        position_value = quantity * current_price
        position_cost = quantity * avg_entry
        unrealized_pnl = position_value - position_cost
        unrealized_pnl_pct = (
            (unrealized_pnl / position_cost * 100) if position_cost > 0 else 0
        )

        total_value += position_value
        total_cost += position_cost
        total_pnl += unrealized_pnl

        positions.append(
            KRStockPosition(
                stk_cd=stk_cd,
                stk_nm=p["stk_nm"],
                quantity=quantity,
                avg_entry_price=avg_entry,
                current_price=current_price,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                stop_loss=p.get("stop_loss"),
                take_profit=p.get("take_profit"),
                session_id=p.get("session_id"),
                created_at=p["created_at"],
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

    Args:
        stk_cd: Stock code

    Returns:
        Position details with current P&L
    """
    from services.storage_service import get_storage_service

    storage = await get_storage_service()

    try:
        position = await storage.get_kr_stock_position(stk_cd)
    except AttributeError:
        position = None

    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{stk_cd} 포지션을 찾을 수 없습니다",
        )

    # Get current price
    current_price = position["avg_entry_price"]
    client = await get_shared_kiwoom_client_async()

    try:
        info = await client.get_stock_info(stk_cd)
        if info:
            current_price = info.cur_prc
    except Exception as e:
        logger.warning("failed_to_fetch_ticker", stk_cd=stk_cd, error=str(e))

    quantity = position["quantity"]
    avg_entry = position["avg_entry_price"]
    position_value = quantity * current_price
    position_cost = quantity * avg_entry
    unrealized_pnl = position_value - position_cost
    unrealized_pnl_pct = (
        (unrealized_pnl / position_cost * 100) if position_cost > 0 else 0
    )

    return KRStockPosition(
        stk_cd=stk_cd,
        stk_nm=position["stk_nm"],
        quantity=quantity,
        avg_entry_price=avg_entry,
        current_price=current_price,
        unrealized_pnl=int(unrealized_pnl),
        unrealized_pnl_pct=unrealized_pnl_pct,
        stop_loss=position.get("stop_loss"),
        take_profit=position.get("take_profit"),
        session_id=position.get("session_id"),
        created_at=position["created_at"],
    )


@router.post("/positions/{stk_cd}/close", response_model=KRStockOrderResponse)
async def close_position(stk_cd: str):
    """
    Close a position by selling all holdings at market price.

    Args:
        stk_cd: Stock code to close

    Returns:
        Order response from the sell order
    """
    from services.storage_service import get_storage_service

    check_kiwoom_api_keys()

    storage = await get_storage_service()

    try:
        position = await storage.get_kr_stock_position(stk_cd)
    except AttributeError:
        position = None

    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{stk_cd} 포지션을 찾을 수 없습니다",
        )

    quantity = position["quantity"]
    if quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{stk_cd} 포지션 수량이 0입니다",
        )

    # Check trading mode
    is_mock = getattr(settings, "KIWOOM_IS_MOCK", True)

    if is_mock:
        logger.info(
            "mock_trade_close_position",
            stk_cd=stk_cd,
            quantity=quantity,
        )

        # Get current price
        client = await get_shared_kiwoom_client_async()
        current_price = position["avg_entry_price"]
        try:
            info = await client.get_stock_info(stk_cd)
            if info:
                current_price = info.cur_prc
        except Exception:
            pass

        # Delete position
        try:
            await storage.delete_kr_stock_position(stk_cd)
        except AttributeError:
            pass

        return KRStockOrderResponse(
            order_id=f"mock-close-{uuid.uuid4()}",
            stk_cd=stk_cd,
            stk_nm=position["stk_nm"],
            side="sell",
            ord_type="market",
            price=current_price,
            quantity=quantity,
            executed_quantity=quantity,
            remaining_quantity=0,
            status="completed",
            created_at=datetime.now(timezone.utc),
        )

    # Live trading
    client = await get_shared_kiwoom_client_async()

    try:
        from services.kiwoom import OrderRequest as KiwoomOrderRequest, OrderType

        kiwoom_request = KiwoomOrderRequest(
            stk_cd=stk_cd,
            order_type=OrderType.MARKET_SELL,
            quantity=quantity,
            price=0,
        )

        order = await client.place_order(kiwoom_request)

        # Delete position on success
        try:
            await storage.delete_kr_stock_position(stk_cd)
        except AttributeError:
            pass

        logger.info("position_closed", stk_cd=stk_cd, order_id=order.order_id)

        return KRStockOrderResponse(
            order_id=order.order_id,
            stk_cd=stk_cd,
            stk_nm=position["stk_nm"],
            side="sell",
            ord_type="market",
            price=None,
            quantity=quantity,
            executed_quantity=0,
            remaining_quantity=quantity,
            status="pending",
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
