"""
News API Routes

Provides endpoints for news search and quota status.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from services.news import (
    NewsService,
    NewsSearchResult,
    QuotaExceededError,
    NewsProviderError,
)
from app.dependencies import get_news_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news", tags=["news"])


# Response Models
class QuotaInfo(BaseModel):
    """Provider quota information"""
    daily_limit: int
    remaining: int
    used: int
    available: bool


class QuotaResponse(BaseModel):
    """All providers quota status"""
    providers: dict[str, QuotaInfo]
    total_remaining: int


class NewsErrorResponse(BaseModel):
    """Error response"""
    error: str
    provider: Optional[str] = None
    suggestion: Optional[str] = None


# Endpoints
@router.get(
    "/search",
    response_model=NewsSearchResult,
    responses={
        429: {"model": NewsErrorResponse, "description": "Quota exceeded"},
        500: {"model": NewsErrorResponse, "description": "Provider error"},
    },
)
async def search_news(
    query: str = Query(..., min_length=1, description="Search query"),
    count: int = Query(10, ge=1, le=100, description="Number of results"),
    sort: str = Query("date", regex="^(date|sim)$", description="Sort: date or sim"),
    provider: Optional[str] = Query(None, description="Specific provider to use"),
    news_service: NewsService = Depends(get_news_service),
):
    """
    Search news articles.

    - **query**: Search keywords (Korean supported)
    - **count**: Number of results (1-100)
    - **sort**: Sort order - "date" (newest first) or "sim" (relevance)
    - **provider**: Optional specific provider (default: auto-select)
    """
    try:
        result = await news_service.search(
            query=query,
            count=count,
            sort=sort,
            provider=provider,
        )
        return result

    except QuotaExceededError as e:
        logger.warning(f"[News API] Quota exceeded: {e}")
        raise HTTPException(
            status_code=429,
            detail={
                "error": str(e),
                "provider": e.provider,
                "suggestion": "Try again tomorrow or use a different provider",
            },
        )

    except NewsProviderError as e:
        logger.error(f"[News API] Provider error: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "provider": e.provider,
            },
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/stock/{stock_code}",
    response_model=NewsSearchResult,
    responses={
        429: {"model": NewsErrorResponse, "description": "Quota exceeded"},
        500: {"model": NewsErrorResponse, "description": "Provider error"},
    },
)
async def get_stock_news(
    stock_code: str,
    stock_name: Optional[str] = Query(None, description="Stock name for better results"),
    count: int = Query(10, ge=1, le=100, description="Number of results"),
    news_service: NewsService = Depends(get_news_service),
):
    """
    Get news for a specific stock.

    - **stock_code**: Stock code (e.g., "005930")
    - **stock_name**: Stock name (e.g., "삼성전자") - improves search quality
    - **count**: Number of results (1-100)
    """
    try:
        result = await news_service.search_stock_news(
            stock_code=stock_code,
            stock_name=stock_name,
            count=count,
        )
        return result

    except QuotaExceededError as e:
        raise HTTPException(
            status_code=429,
            detail={
                "error": str(e),
                "provider": e.provider,
                "suggestion": "Try again tomorrow or use a different provider",
            },
        )

    except NewsProviderError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "provider": e.provider,
            },
        )


@router.get(
    "/quota",
    response_model=QuotaResponse,
)
async def get_quota_status(
    news_service: NewsService = Depends(get_news_service),
):
    """
    Get API quota status for all news providers.

    Returns daily limits, current usage, and remaining quota.
    """
    status = await news_service.get_quota_status()
    total_remaining = await news_service.get_total_remaining()

    return QuotaResponse(
        providers={
            name: QuotaInfo(**info)
            for name, info in status.items()
        },
        total_remaining=total_remaining,
    )


@router.get("/providers")
async def list_providers(
    news_service: NewsService = Depends(get_news_service),
):
    """
    List available news providers.
    """
    providers = []
    for name, provider in news_service.providers.items():
        remaining = await provider.get_remaining_quota()
        providers.append({
            "name": name,
            "daily_limit": provider.daily_limit,
            "remaining": remaining,
            "is_primary": name == news_service.primary_provider,
        })

    return {
        "providers": providers,
        "primary": news_service.primary_provider,
    }
