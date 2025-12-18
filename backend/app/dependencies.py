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
# Future Dependencies (placeholders)
# -------------------------------------------

# Market data service dependency
# def get_market_data_service() -> MarketDataService:
#     return MarketDataService()

# Portfolio service dependency
# def get_portfolio_service() -> PortfolioService:
#     return PortfolioService()
