"""
News Service

Aggregates multiple news providers with automatic fallback support.
Provides unified interface for news search across all providers.
"""

import logging
from typing import Dict, List, Optional

from .base import (
    NewsProvider,
    NewsSearchResult,
    QuotaExceededError,
    NewsProviderError,
)

logger = logging.getLogger(__name__)


class NewsService:
    """
    News aggregation service with fallback support.

    Features:
    - Multiple provider support
    - Automatic fallback on quota exhaustion
    - Provider prioritization
    - Usage statistics

    Example:
        service = NewsService()
        service.register_provider(NaverNewsProvider(...), primary=True)

        # Search with automatic fallback
        result = await service.search("삼성전자 주식", count=10)

        # Get quota info
        quotas = await service.get_quota_status()
    """

    def __init__(self):
        self.providers: Dict[str, NewsProvider] = {}
        self.primary_provider: Optional[str] = None
        self._fallback_order: List[str] = []

    def register_provider(
        self,
        provider: NewsProvider,
        primary: bool = False
    ) -> None:
        """
        Register a news provider.

        Args:
            provider: NewsProvider instance
            primary: Set as primary provider
        """
        self.providers[provider.name] = provider
        self._fallback_order.append(provider.name)

        if primary or self.primary_provider is None:
            self.primary_provider = provider.name

        logger.info(
            f"[NewsService] Registered provider: {provider.name} "
            f"(primary={primary})"
        )

    def set_fallback_order(self, order: List[str]) -> None:
        """
        Set custom fallback order for providers.

        Args:
            order: List of provider names in fallback order
        """
        # Validate all providers exist
        for name in order:
            if name not in self.providers:
                raise ValueError(f"Unknown provider: {name}")

        self._fallback_order = order
        logger.info(f"[NewsService] Fallback order set: {order}")

    async def search(
        self,
        query: str,
        count: int = 10,
        sort: str = "date",
        provider: Optional[str] = None
    ) -> NewsSearchResult:
        """
        Search news with automatic fallback.

        Args:
            query: Search query
            count: Number of results
            sort: Sort order ("date" or "sim")
            provider: Specific provider to use (skips fallback)

        Returns:
            NewsSearchResult from first available provider

        Raises:
            NewsProviderError: If all providers fail
        """
        if not self.providers:
            raise NewsProviderError("none", "No providers registered")

        # Use specific provider if requested
        if provider:
            if provider not in self.providers:
                raise ValueError(f"Unknown provider: {provider}")
            return await self.providers[provider].search(query, count, sort)

        # Try providers in fallback order
        errors = []

        for provider_name in self._get_fallback_order():
            news_provider = self.providers[provider_name]

            try:
                # Check quota before attempting
                remaining = await news_provider.get_remaining_quota()
                if remaining == 0:
                    logger.warning(
                        f"[NewsService] {provider_name} quota exhausted, "
                        "trying next provider"
                    )
                    continue

                result = await news_provider.search(query, count, sort)
                return result

            except QuotaExceededError as e:
                logger.warning(f"[NewsService] {provider_name}: {e}")
                errors.append(str(e))
                continue

            except NewsProviderError as e:
                logger.error(f"[NewsService] {provider_name}: {e}")
                errors.append(str(e))
                continue

            except Exception as e:
                logger.exception(f"[NewsService] {provider_name} unexpected error")
                errors.append(f"{provider_name}: {str(e)}")
                continue

        # All providers failed
        error_msg = "All news providers failed:\n" + "\n".join(errors)
        raise NewsProviderError("all", error_msg)

    async def search_stock_news(
        self,
        stock_code: str,
        stock_name: Optional[str] = None,
        count: int = 10
    ) -> NewsSearchResult:
        """
        Search news for a specific stock.

        Args:
            stock_code: Stock code (e.g., "005930")
            stock_name: Stock name (e.g., "삼성전자")
            count: Number of results

        Returns:
            NewsSearchResult with stock-related news
        """
        # Build query: prefer stock name, fallback to code
        if stock_name:
            query = f"{stock_name} 주식"
        else:
            query = f"{stock_code} 주식"

        return await self.search(query, count, sort="date")

    async def get_quota_status(self) -> Dict[str, dict]:
        """
        Get quota status for all providers.

        Returns:
            Dict mapping provider name to quota info
        """
        status = {}

        for name, provider in self.providers.items():
            remaining = await provider.get_remaining_quota()
            status[name] = {
                "daily_limit": provider.daily_limit,
                "remaining": remaining,
                "used": provider.daily_limit - remaining if remaining >= 0 else 0,
                "available": remaining > 0 if remaining >= 0 else True,
            }

        return status

    async def get_total_remaining(self) -> int:
        """
        Get total remaining quota across all providers.

        Returns:
            Total remaining API calls
        """
        total = 0
        for provider in self.providers.values():
            remaining = await provider.get_remaining_quota()
            if remaining > 0:
                total += remaining
        return total

    def _get_fallback_order(self) -> List[str]:
        """Get provider fallback order with primary first."""
        order = []

        # Primary first
        if self.primary_provider:
            order.append(self.primary_provider)

        # Then others in fallback order
        for name in self._fallback_order:
            if name not in order:
                order.append(name)

        return order

    async def close(self) -> None:
        """Close all providers and release resources."""
        for provider in self.providers.values():
            try:
                await provider.close()
            except Exception as e:
                logger.warning(f"[NewsService] Error closing {provider.name}: {e}")

    def __repr__(self) -> str:
        providers = list(self.providers.keys())
        return f"<NewsService providers={providers} primary={self.primary_provider}>"


# Factory function for creating configured service
async def create_news_service(
    naver_client_id: Optional[str] = None,
    naver_client_secret: Optional[str] = None,
    cache_manager=None,
) -> NewsService:
    """
    Factory function to create a configured NewsService.

    Args:
        naver_client_id: Naver API client ID
        naver_client_secret: Naver API client secret
        cache_manager: Optional cache manager

    Returns:
        Configured NewsService instance
    """
    from .naver import NaverNewsProvider

    service = NewsService()

    # Register Naver if credentials provided
    if naver_client_id and naver_client_secret:
        naver_provider = NaverNewsProvider(
            client_id=naver_client_id,
            client_secret=naver_client_secret,
            cache_manager=cache_manager,
        )
        service.register_provider(naver_provider, primary=True)

    # Future: Add more providers here
    # if daum_api_key:
    #     service.register_provider(DaumNewsProvider(...))

    return service
