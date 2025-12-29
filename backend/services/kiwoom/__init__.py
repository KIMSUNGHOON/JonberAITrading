"""
Kiwoom REST API Service Module

Provides async HTTP client for Kiwoom Securities REST API.
Supports both Mock Trading (mockapi) and Live Trading (api).

Main components:
- KiwoomClient: Main API client for all operations
- KiwoomAuth: OAuth2 token management
- KiwoomRateLimiter: Rate limiting (이용약관 제11조)
- KiwoomWebSocketClient: Real-time data streaming
- Models: Pydantic models for request/response
"""

from .auth import KiwoomAuth
from .cache import KiwoomCache, make_cache_key
from .client import KiwoomClient
from .errors import KiwoomError, KiwoomErrorCode, KiwoomRateLimitError
from .rate_limiter import KiwoomRateLimiter, RequestType
from .models import (
    AccountBalance,
    ChartData,
    Holding,
    KiwoomToken,
    Orderbook,
    OrderRequest,
    OrderResponse,
    OrderType,
    StockBasicInfo,
)
from .websocket import (
    KiwoomWebSocketClient,
    RealTimeType,
    OrderExecutionData,
    BalanceData,
    StockTickData,
    OrderbookData,
    VITriggerData,
)

__all__ = [
    # Client
    "KiwoomClient",
    # Auth
    "KiwoomAuth",
    # Cache
    "KiwoomCache",
    "make_cache_key",
    # Rate Limiter
    "KiwoomRateLimiter",
    "RequestType",
    # WebSocket
    "KiwoomWebSocketClient",
    "RealTimeType",
    "OrderExecutionData",
    "BalanceData",
    "StockTickData",
    "OrderbookData",
    "VITriggerData",
    # Errors
    "KiwoomError",
    "KiwoomErrorCode",
    "KiwoomRateLimitError",
    # Models
    "KiwoomToken",
    "StockBasicInfo",
    "Orderbook",
    "OrderRequest",
    "OrderResponse",
    "OrderType",
    "ChartData",
    "AccountBalance",
    "Holding",
]