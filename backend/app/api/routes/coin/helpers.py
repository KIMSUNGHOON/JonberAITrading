"""
Coin Route Helpers

Helper functions for coin routes including:
- Client management
- Session management
- Data conversion utilities
"""

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status

from app.api.routes.settings import get_upbit_access_key, get_upbit_secret_key
from app.api.schemas.coin import (
    CoinPosition,
    OrderResponse,
    TickerResponse,
)
from services.upbit import UpbitClient
from .constants import coin_sessions


# =============================================================================
# Client & Session Management
# =============================================================================


def get_upbit_client() -> UpbitClient:
    """Get Upbit client instance using runtime keys or environment variables."""
    return UpbitClient(
        access_key=get_upbit_access_key(),
        secret_key=get_upbit_secret_key(),
    )


def get_coin_session(session_id: str) -> dict:
    """Get session or raise 404."""
    session = coin_sessions.get(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Coin session {session_id} not found",
        )
    return session


def check_api_keys() -> None:
    """Check if Upbit API keys are configured (runtime or environment)."""
    if not get_upbit_access_key() or not get_upbit_secret_key():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Upbit API keys not configured. Set UPBIT_ACCESS_KEY and UPBIT_SECRET_KEY.",
        )


def get_coin_sessions() -> dict:
    """Get reference to coin sessions (for WebSocket, approval routes)."""
    return coin_sessions


# =============================================================================
# Data Conversion Utilities
# =============================================================================


def order_to_response(order: Any) -> OrderResponse:
    """
    Convert Upbit Order object to OrderResponse schema.

    Centralizes the order-to-response conversion logic to avoid duplication.

    Args:
        order: Upbit Order object with uuid, side, ord_type, price, etc.

    Returns:
        OrderResponse schema object
    """
    return OrderResponse(
        uuid=order.uuid,
        side=order.side,
        ord_type=order.ord_type,
        price=float(order.price) if order.price else None,
        state=order.state,
        market=order.market,
        created_at=order.created_at,
        volume=float(order.volume) if order.volume else None,
        remaining_volume=float(order.remaining_volume) if order.remaining_volume else None,
        reserved_fee=float(order.reserved_fee) if order.reserved_fee else None,
        remaining_fee=float(order.remaining_fee) if order.remaining_fee else None,
        paid_fee=float(order.paid_fee) if order.paid_fee else None,
        locked=float(order.locked) if order.locked else None,
        executed_volume=float(order.executed_volume) if order.executed_volume else None,
        trades_count=order.trades_count,
    )


def ticker_to_response(ticker: Any) -> TickerResponse:
    """
    Convert Upbit Ticker object to TickerResponse schema.

    Args:
        ticker: Upbit Ticker object with market, trade_price, change, etc.

    Returns:
        TickerResponse schema object
    """
    return TickerResponse(
        market=ticker.market,
        trade_price=ticker.trade_price,
        change=ticker.change,
        change_rate=ticker.signed_change_rate * 100,
        change_price=ticker.signed_change_price,
        high_price=ticker.high_price,
        low_price=ticker.low_price,
        trade_volume=ticker.acc_trade_volume_24h,
        acc_trade_price_24h=ticker.acc_trade_price_24h,
        timestamp=datetime.now(timezone.utc),
    )


def calculate_position_pnl(
    quantity: float,
    avg_entry_price: float,
    current_price: float,
) -> tuple[float, float, float]:
    """
    Calculate position P&L metrics.

    Args:
        quantity: Position quantity
        avg_entry_price: Average entry price
        current_price: Current market price

    Returns:
        Tuple of (position_value, unrealized_pnl, unrealized_pnl_pct)
    """
    position_value = quantity * current_price
    position_cost = quantity * avg_entry_price
    unrealized_pnl = position_value - position_cost
    unrealized_pnl_pct = (unrealized_pnl / position_cost * 100) if position_cost > 0 else 0

    return position_value, unrealized_pnl, unrealized_pnl_pct


def position_to_response(
    position_data: dict,
    current_price: float,
) -> CoinPosition:
    """
    Convert position data dict to CoinPosition schema with P&L calculation.

    Args:
        position_data: Position data dictionary from storage
        current_price: Current market price for P&L calculation

    Returns:
        CoinPosition schema object
    """
    quantity = position_data["quantity"]
    avg_entry = position_data["avg_entry_price"]

    _, unrealized_pnl, unrealized_pnl_pct = calculate_position_pnl(
        quantity, avg_entry, current_price
    )

    return CoinPosition(
        market=position_data["market"],
        currency=position_data["currency"],
        quantity=quantity,
        avg_entry_price=avg_entry,
        current_price=current_price,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        stop_loss=position_data.get("stop_loss"),
        take_profit=position_data.get("take_profit"),
        session_id=position_data.get("session_id"),
        created_at=position_data["created_at"],
    )
