"""
Korean Stock (Kiwoom) Analysis API Routes Package

This package contains modularized routes for:
- Market Data: /stocks, /ticker, /candles, /orderbook
- Analysis: /analysis/start, /analysis/status, /analysis/cancel
- Orders: /accounts, /orders
- Positions: /positions
- Trades: /trades
- Settings: /settings

The main router aggregates all sub-routers.
"""

from fastapi import APIRouter

from .market_data import router as market_data_router
from .analysis import router as analysis_router
from .orders import router as orders_router
from .positions import router as positions_router
from .trades import router as trades_router
from .kr_settings import router as settings_router

# Re-export for backwards compatibility
from .constants import (
    KOREAN_STOCKS,
    POPULAR_STOCKS,
    kr_stock_sessions,
)
from .helpers import (
    get_kr_stock_session,
    get_kr_stock_sessions,
    check_kiwoom_api_keys,
)

# Re-export endpoint functions for test compatibility
from .market_data import get_candles, _generate_mock_candles

# Create main router that includes all sub-routers
router = APIRouter()

# Include all sub-routers (order matters for overlapping paths)
router.include_router(market_data_router)
router.include_router(analysis_router)
router.include_router(orders_router)
router.include_router(positions_router)
router.include_router(trades_router)
router.include_router(settings_router)

__all__ = [
    "router",
    "KOREAN_STOCKS",
    "POPULAR_STOCKS",
    "kr_stock_sessions",
    "get_kr_stock_session",
    "get_kr_stock_sessions",
    "check_kiwoom_api_keys",
    # Test compatibility
    "get_candles",
    "_generate_mock_candles",
]
