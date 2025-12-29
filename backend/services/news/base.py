"""
News Provider Base Classes

Abstract interfaces for news providers, enabling easy extension
to support multiple news sources (Naver, Daum, NewsAPI, etc.)
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class NewsArticle(BaseModel):
    """Single news article model"""
    title: str = Field(..., description="Article title")
    description: str = Field(default="", description="Article summary/description")
    link: str = Field(..., description="Article URL")
    original_link: Optional[str] = Field(default=None, description="Original source URL")
    source: str = Field(default="", description="News source/publisher name")
    pub_date: datetime = Field(..., description="Publication date")

    # Sentiment analysis results (filled by sentiment analyzer)
    sentiment: Optional[str] = Field(
        default=None,
        description="Sentiment: positive, neutral, negative"
    )
    sentiment_score: Optional[float] = Field(
        default=None,
        description="Sentiment score: -1.0 (negative) to 1.0 (positive)"
    )
    relevance_score: Optional[float] = Field(
        default=None,
        description="Relevance score: 0.0 to 1.0"
    )

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class NewsSearchResult(BaseModel):
    """News search result container"""
    query: str = Field(..., description="Original search query")
    total: int = Field(default=0, description="Total matching articles")
    articles: List[NewsArticle] = Field(default_factory=list)
    cached: bool = Field(default=False, description="Whether result was from cache")
    provider: str = Field(..., description="News provider name")
    searched_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class QuotaExceededError(Exception):
    """Raised when API quota is exceeded"""
    def __init__(self, provider: str, message: str = "API quota exceeded"):
        self.provider = provider
        self.message = message
        super().__init__(f"[{provider}] {message}")


class NewsProviderError(Exception):
    """Generic news provider error"""
    def __init__(self, provider: str, message: str):
        self.provider = provider
        self.message = message
        super().__init__(f"[{provider}] {message}")


class NewsProvider(ABC):
    """
    Abstract base class for news providers.

    Implement this class to add support for new news sources.

    Example:
        class DaumNewsProvider(NewsProvider):
            @property
            def name(self) -> str:
                return "daum"

            async def search(self, query, count, sort) -> NewsSearchResult:
                # Implementation...
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique identifier for this provider.
        Used in caching, logging, and provider selection.
        """
        pass

    @property
    @abstractmethod
    def daily_limit(self) -> int:
        """
        Daily API call limit for this provider.
        Return -1 if unlimited.
        """
        pass

    @property
    def rate_limit_per_second(self) -> int:
        """
        Per-second rate limit. Override if needed.
        Return -1 if unlimited.
        """
        return -1

    @abstractmethod
    async def search(
        self,
        query: str,
        count: int = 10,
        sort: str = "date"
    ) -> NewsSearchResult:
        """
        Search for news articles.

        Args:
            query: Search query string
            count: Number of results to return (max varies by provider)
            sort: Sort order - "date" (newest first) or "sim" (relevance)

        Returns:
            NewsSearchResult containing matching articles

        Raises:
            QuotaExceededError: When API quota is exhausted
            NewsProviderError: On API or network errors
        """
        pass

    @abstractmethod
    async def get_remaining_quota(self) -> int:
        """
        Get remaining API calls for today.

        Returns:
            Number of remaining calls, or -1 if unlimited
        """
        pass

    async def close(self):
        """
        Clean up resources (HTTP clients, etc.)
        Override if provider needs cleanup.
        """
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name}>"
