"""
Coin API Routes Package

This package provides cryptocurrency trading endpoints for Upbit exchange.

Modules:
- constants: Cache variables and session store
- helpers: Helper functions (client, session lookup)
- market_data: Market data endpoints (/markets, /ticker, /candles, /orderbook)
- analysis: Analysis endpoints (/analysis/*)
- orders: Account and order endpoints (/accounts, /orders/*)
- positions: Position endpoints (/positions/*)
- trades: Trade history endpoints (/trades/*)
"""

from fastapi import APIRouter

from .market_data import router as market_data_router
from .analysis import router as analysis_router
from .orders import router as orders_router
from .positions import router as positions_router
from .trades import router as trades_router

# Create main router and include all sub-routers
router = APIRouter()
router.include_router(market_data_router)
router.include_router(analysis_router)
router.include_router(orders_router)
router.include_router(positions_router)
router.include_router(trades_router)

# Re-export for backwards compatibility
from .constants import (
    coin_sessions,
    CACHE_TTL_SECONDS,
    get_cached_markets,
    set_cached_markets,
    get_markets_cache_time,
)
from .helpers import (
    get_upbit_client,
    get_coin_session,
    check_api_keys,
    get_coin_sessions,
)

__all__ = [
    # Router
    "router",
    # Constants
    "coin_sessions",
    "CACHE_TTL_SECONDS",
    "get_cached_markets",
    "set_cached_markets",
    "get_markets_cache_time",
    # Helpers
    "get_upbit_client",
    "get_coin_session",
    "check_api_keys",
    "get_coin_sessions",
]
