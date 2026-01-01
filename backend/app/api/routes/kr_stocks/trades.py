"""
Korean Stock Trade History Endpoints

Endpoints for trade history:
- GET /trades - Trade list with pagination
- GET /trades/{trade_id} - Single trade details
"""

from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.api.schemas.kr_stocks import (
    KRStockTradeListResponse,
    KRStockTradeRecord,
)

logger = structlog.get_logger()
router = APIRouter()


@router.get("/trades", response_model=KRStockTradeListResponse)
async def get_trades(
    stk_cd: Optional[str] = Query(default=None, description="Filter by stock code"),
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(default=20, ge=1, le=100, description="Results per page"),
):
    """
    Get trade history with pagination.

    Args:
        stk_cd: Filter by stock code (optional)
        page: Page number (1-indexed)
        limit: Results per page (max 100)

    Returns:
        Paginated list of trade records
    """
    from services.storage_service import get_storage_service

    storage = await get_storage_service()
    offset = (page - 1) * limit

    try:
        trades_data = await storage.get_kr_stock_trades(
            stk_cd=stk_cd,
            limit=limit,
            offset=offset,
        )
        total = await storage.get_kr_stock_trades_count(stk_cd=stk_cd)
    except AttributeError:
        trades_data = []
        total = 0

    trades = [
        KRStockTradeRecord(
            id=t["id"],
            session_id=t.get("session_id"),
            stk_cd=t["stk_cd"],
            stk_nm=t.get("stk_nm"),
            side=t["side"],
            order_type=t["order_type"],
            price=t["price"],
            quantity=t["quantity"],
            executed_quantity=t["executed_quantity"],
            fee=t.get("fee", 0),
            total_krw=t["total_krw"],
            status=t["status"],
            order_id=t.get("order_id"),
            created_at=t["created_at"],
        )
        for t in trades_data
    ]

    return KRStockTradeListResponse(
        trades=trades,
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/trades/{trade_id}", response_model=KRStockTradeRecord)
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

    try:
        trade = await storage.get_kr_stock_trade(trade_id)
    except AttributeError:
        trade = None

    if not trade:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"거래 {trade_id}를 찾을 수 없습니다",
        )

    return KRStockTradeRecord(
        id=trade["id"],
        session_id=trade.get("session_id"),
        stk_cd=trade["stk_cd"],
        stk_nm=trade.get("stk_nm"),
        side=trade["side"],
        order_type=trade["order_type"],
        price=trade["price"],
        quantity=trade["quantity"],
        executed_quantity=trade["executed_quantity"],
        fee=trade.get("fee", 0),
        total_krw=trade["total_krw"],
        status=trade["status"],
        order_id=trade.get("order_id"),
        created_at=trade["created_at"],
    )
