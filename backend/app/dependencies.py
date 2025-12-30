"""
FastAPI Dependency Injection

Provides dependency functions for use in route handlers.
"""

from typing import Annotated, AsyncGenerator

from fastapi import Depends

from agents.llm_provider import LLMProvider, get_llm_provider
from app.config import Settings, get_settings


# -------------------------------------------
# Settings Dependency
# -------------------------------------------


def get_app_settings() -> Settings:
    """
    Dependency to get application settings.

    Usage:
        @router.get("/example")
        async def example(settings: Annotated[Settings, Depends(get_app_settings)]):
            ...
    """
    return get_settings()


# Type alias for cleaner annotations
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


# -------------------------------------------
# LLM Provider Dependency
# -------------------------------------------


def get_llm() -> LLMProvider:
    """
    Dependency to get LLM provider instance.

    Usage:
        @router.post("/analyze")
        async def analyze(llm: Annotated[LLMProvider, Depends(get_llm)]):
            response = await llm.generate(messages)
            ...
    """
    return get_llm_provider()


# Type alias for cleaner annotations
LLMDep = Annotated[LLMProvider, Depends(get_llm)]


# -------------------------------------------
# Storage Service Dependency
# -------------------------------------------


async def get_storage() -> "StorageService":
    """
    Dependency to get SQLite storage service instance.

    Usage:
        @router.post("/example")
        async def example(storage: Annotated[StorageService, Depends(get_storage)]):
            await storage.save_session("session_id", {"key": "value"})
            ...
    """
    from services.storage_service import StorageService, get_storage_service
    return await get_storage_service()


# Type alias for cleaner annotations
StorageDep = Annotated["StorageService", Depends(get_storage)]


# -------------------------------------------
# News Service Dependency
# -------------------------------------------

# Singleton instance for news service
_news_service_instance = None


async def get_news_service() -> "NewsService":
    """
    Dependency to get News service instance.

    Usage:
        @router.get("/news/search")
        async def search(news: Annotated[NewsService, Depends(get_news_service)]):
            result = await news.search("삼성전자 주식")
            ...
    """
    global _news_service_instance

    if _news_service_instance is None:
        from services.news import NewsService, NaverNewsProvider
        from services.news.cache import InMemoryCacheManager, NewsCacheManager

        settings = get_settings()

        # Create cache manager (Redis if available, else in-memory)
        cache_manager = None
        if settings.REDIS_URL:
            try:
                import redis.asyncio as redis
                redis_client = redis.from_url(settings.REDIS_URL)
                cache_manager = NewsCacheManager(redis_client)
            except ImportError:
                pass

        if cache_manager is None:
            cache_manager = InMemoryCacheManager()

        # Create service
        _news_service_instance = NewsService()

        # Register Naver provider if credentials available
        if settings.NAVER_CLIENT_ID and settings.NAVER_CLIENT_SECRET:
            naver_provider = NaverNewsProvider(
                client_id=settings.NAVER_CLIENT_ID,
                client_secret=settings.NAVER_CLIENT_SECRET,
                cache_manager=cache_manager,
            )
            _news_service_instance.register_provider(naver_provider, primary=True)

    return _news_service_instance


# Type alias for cleaner annotations
NewsDep = Annotated["NewsService", Depends(get_news_service)]


# -------------------------------------------
# Trading Coordinator Dependency
# -------------------------------------------

# Singleton instance for trading coordinator
_trading_coordinator_instance = None


async def get_trading_coordinator() -> "ExecutionCoordinator":
    """
    Dependency to get Trading coordinator instance.

    Usage:
        @router.post("/trading/start")
        async def start(coordinator: Annotated[ExecutionCoordinator, Depends(get_trading_coordinator)]):
            await coordinator.start()
            ...
    """
    global _trading_coordinator_instance

    if _trading_coordinator_instance is None:
        from services.trading import ExecutionCoordinator, RiskParameters
        from app.core.kiwoom_singleton import get_shared_kiwoom_client_async

        settings = get_settings()

        # Use shared Kiwoom client singleton (same as kr_stocks routes)
        kiwoom_client = None
        try:
            kiwoom_client = await get_shared_kiwoom_client_async()
            import logging
            logging.getLogger(__name__).info("Trading coordinator using shared Kiwoom client")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to get shared Kiwoom client: {e}")

        # Initialize Redis client if available
        redis_client = None
        if settings.REDIS_URL:
            try:
                import redis.asyncio as redis
                redis_client = redis.from_url(settings.REDIS_URL)
            except ImportError:
                pass

        # Create coordinator
        _trading_coordinator_instance = ExecutionCoordinator(
            kiwoom_client=kiwoom_client,
            redis_client=redis_client,
        )

    return _trading_coordinator_instance


# Type alias for cleaner annotations
TradingDep = Annotated["ExecutionCoordinator", Depends(get_trading_coordinator)]


# -------------------------------------------
# Future Dependencies (placeholders)
# -------------------------------------------

# Market data service dependency
# def get_market_data_service() -> MarketDataService:
#     return MarketDataService()
