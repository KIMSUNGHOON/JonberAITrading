"""
News Service Module

Provides extensible news search and sentiment analysis capabilities.
Currently supports Naver News API with caching layer.
"""

from .base import NewsProvider, NewsArticle, NewsSearchResult, QuotaExceededError, NewsProviderError
from .naver import NaverNewsProvider
from .service import NewsService

__all__ = [
    "NewsProvider",
    "NewsArticle",
    "NewsSearchResult",
    "QuotaExceededError",
    "NewsProviderError",
    "NaverNewsProvider",
    "NewsService",
]
