"""
Coin Trade History Endpoints

Endpoints for trade history:
- GET /trades - Paginated trade list
- GET /trades/{trade_id} - Single trade
"""

from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.api.schemas.coin import (
    CoinTradeListResponse,
    CoinTradeRecord,
)

logger = structlog.get_logger()
router = APIRouter()


@router.get("/trades", response_model=CoinTradeListResponse)
async def get_trades(
    market: Optional[str] = Query(default=None, description="Filter by market code"),
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(default=20, ge=1, le=100, description="Results per page"),
):
    """
    Get trade history with pagination.

    Args:
        market: Filter by market code (optional)
        page: Page number (1-indexed)
        limit: Results per page (max 100)

    Returns:
        Paginated list of trade records
    """
    from services.storage_service import get_storage_service

    storage = await get_storage_service()
    offset = (page - 1) * limit

    trades_data = await storage.get_coin_trades(
        market=market.upper() if market else None,
        limit=limit,
        offset=offset,
    )

    total = await storage.get_coin_trades_count(
        market=market.upper() if market else None
    )

    trades = [
        CoinTradeRecord(
            id=t["id"],
            session_id=t.get("session_id"),
            market=t["market"],
            side=t["side"],
            order_type=t["order_type"],
            price=t["price"],
            volume=t["volume"],
            executed_volume=t["executed_volume"],
            fee=t.get("fee", 0),
            total_krw=t["total_krw"],
            state=t["state"],
            order_uuid=t.get("order_uuid"),
            created_at=t["created_at"],
        )
        for t in trades_data
    ]

    return CoinTradeListResponse(
        trades=trades,
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/trades/{trade_id}", response_model=CoinTradeRecord)
async def get_trade(trade_id: str):
    """
    Get a single trade by ID.

    Args:
        trade_id: Trade ID

    Returns:
        Trade record details
    """
    from services.storage_service import get_storage_service

    storage = await get_storage_service()
    trade = await storage.get_coin_trade(trade_id)

    if not trade:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trade {trade_id} not found",
        )

    return CoinTradeRecord(
        id=trade["id"],
        session_id=trade.get("session_id"),
        market=trade["market"],
        side=trade["side"],
        order_type=trade["order_type"],
        price=trade["price"],
        volume=trade["volume"],
        executed_volume=trade["executed_volume"],
        fee=trade.get("fee", 0),
        total_krw=trade["total_krw"],
        state=trade["state"],
        order_uuid=trade.get("order_uuid"),
        created_at=trade["created_at"],
    )
