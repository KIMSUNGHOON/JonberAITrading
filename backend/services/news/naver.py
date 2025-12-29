"""
Naver News API Provider

Implements news search using Naver Open API.
https://developers.naver.com/docs/serviceapi/search/news/news.md

Rate Limits:
- Daily: 25,000 requests
- Per second: 10 requests (estimated)
"""

import re
import httpx
import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import quote

from .base import (
    NewsProvider,
    NewsArticle,
    NewsSearchResult,
    QuotaExceededError,
    NewsProviderError,
)

logger = logging.getLogger(__name__)


class NaverNewsProvider(NewsProvider):
    """
    Naver News Search API Provider.

    Requires:
        - NAVER_CLIENT_ID: API client ID
        - NAVER_CLIENT_SECRET: API client secret

    Get credentials at: https://developers.naver.com/apps
    """

    BASE_URL = "https://openapi.naver.com/v1/search/news.json"
    DAILY_LIMIT = 25000
    MAX_DISPLAY = 100  # Max results per request

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        cache_manager: Optional["NewsCacheManager"] = None,
    ):
        """
        Initialize Naver News Provider.

        Args:
            client_id: Naver API client ID
            client_secret: Naver API client secret
            cache_manager: Optional cache manager for quota tracking and caching
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.cache = cache_manager
        self._http = httpx.AsyncClient(timeout=30.0)

    @property
    def name(self) -> str:
        return "naver"

    @property
    def daily_limit(self) -> int:
        return self.DAILY_LIMIT

    @property
    def rate_limit_per_second(self) -> int:
        return 10

    async def search(
        self,
        query: str,
        count: int = 10,
        sort: str = "date"
    ) -> NewsSearchResult:
        """
        Search Naver News.

        Args:
            query: Search query (Korean supported)
            count: Number of results (1-100)
            sort: "date" (newest) or "sim" (relevance)

        Returns:
            NewsSearchResult with matching articles
        """
        # Validate parameters
        count = min(max(1, count), self.MAX_DISPLAY)
        sort = "date" if sort == "date" else "sim"

        # Check cache first
        if self.cache:
            cache_key = f"news:{self.name}:{query}:{count}:{sort}"
            cached = await self.cache.get(cache_key)
            if cached:
                logger.debug(f"[Naver] Cache hit for query: {query}")
                result = NewsSearchResult.model_validate_json(cached)
                result.cached = True
                return result

        # Check quota
        remaining = await self.get_remaining_quota()
        if remaining == 0:
            raise QuotaExceededError(
                self.name,
                f"Daily limit of {self.DAILY_LIMIT} requests exceeded"
            )

        # Make API request
        try:
            response = await self._make_request(query, count, sort)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise QuotaExceededError(self.name, "Rate limit exceeded")
            raise NewsProviderError(
                self.name,
                f"HTTP error {e.response.status_code}: {e.response.text}"
            )
        except httpx.RequestError as e:
            raise NewsProviderError(self.name, f"Request failed: {str(e)}")

        # Parse response
        data = response.json()

        if "errorCode" in data:
            raise NewsProviderError(
                self.name,
                f"API error {data.get('errorCode')}: {data.get('errorMessage')}"
            )

        # Increment usage counter
        if self.cache:
            await self.cache.increment_usage(self.name)

        # Parse articles
        articles = []
        for item in data.get("items", []):
            try:
                article = NewsArticle(
                    title=self._clean_html(item.get("title", "")),
                    description=self._clean_html(item.get("description", "")),
                    link=item.get("link", ""),
                    original_link=item.get("originallink"),
                    source=self._extract_source(item.get("originallink", "")),
                    pub_date=self._parse_date(item.get("pubDate", "")),
                )
                articles.append(article)
            except Exception as e:
                logger.warning(f"[Naver] Failed to parse article: {e}")
                continue

        result = NewsSearchResult(
            query=query,
            total=data.get("total", len(articles)),
            articles=articles,
            cached=False,
            provider=self.name,
        )

        # Cache result
        if self.cache:
            await self.cache.set(
                cache_key,
                result.model_dump_json(),
                ttl=1800  # 30 minutes
            )

        logger.info(
            f"[Naver] Search '{query}' returned {len(articles)} articles "
            f"(total: {result.total})"
        )

        return result

    async def get_remaining_quota(self) -> int:
        """Get remaining API calls for today."""
        if not self.cache:
            # Without cache, we can't track usage - assume unlimited
            return self.DAILY_LIMIT

        usage = await self.cache.get_usage(self.name)
        remaining = max(0, self.DAILY_LIMIT - usage)
        return remaining

    async def _make_request(
        self,
        query: str,
        count: int,
        sort: str
    ) -> httpx.Response:
        """Make HTTP request to Naver API."""
        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }

        params = {
            "query": query,
            "display": count,
            "start": 1,
            "sort": sort,
        }

        response = await self._http.get(
            self.BASE_URL,
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        return response

    @staticmethod
    def _clean_html(text: str) -> str:
        """Remove HTML tags and entities from text."""
        if not text:
            return ""
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        # Decode common HTML entities
        text = text.replace("&quot;", '"')
        text = text.replace("&amp;", "&")
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&apos;", "'")
        text = text.replace("&nbsp;", " ")
        return text.strip()

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        """Parse Naver date format (RFC 2822)."""
        if not date_str:
            return datetime.now()
        try:
            return parsedate_to_datetime(date_str)
        except (ValueError, TypeError):
            return datetime.now()

    @staticmethod
    def _extract_source(url: str) -> str:
        """Extract source name from URL."""
        if not url:
            return ""
        try:
            # Extract domain from URL
            match = re.search(r"https?://(?:www\.)?([^/]+)", url)
            if match:
                domain = match.group(1)
                # Clean up common news domains
                domain = domain.replace(".co.kr", "")
                domain = domain.replace(".com", "")
                return domain
        except Exception:
            pass
        return ""

    async def close(self):
        """Close HTTP client."""
        await self._http.aclose()

    def __repr__(self) -> str:
        return f"<NaverNewsProvider remaining={self.DAILY_LIMIT}>"
