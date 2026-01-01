"""
Coin Constants and Cache

Contains:
- coin_sessions: In-memory session store
- Market cache variables
"""

from datetime import datetime
from typing import Optional

from app.api.schemas.coin import MarketInfo

# In-memory session store for coin analysis
coin_sessions: dict[str, dict] = {}

# Cached market list
_cached_markets: list[MarketInfo] = []
_markets_cache_time: Optional[datetime] = None
CACHE_TTL_SECONDS = 300  # 5 minutes


def get_cached_markets() -> list[MarketInfo]:
    """Get cached markets list."""
    return _cached_markets


def set_cached_markets(markets: list[MarketInfo], cache_time: datetime) -> None:
    """Set cached markets list."""
    global _cached_markets, _markets_cache_time
    _cached_markets = markets
    _markets_cache_time = cache_time


def get_markets_cache_time() -> Optional[datetime]:
    """Get cache timestamp."""
    return _markets_cache_time
