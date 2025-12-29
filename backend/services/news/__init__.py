"""
News Service Module

Provides extensible news search and sentiment analysis capabilities.
Currently supports Naver News API with caching layer.
"""

from .base import NewsProvider, NewsArticle, NewsSearchResult, QuotaExceededError, NewsProviderError
from .naver import NaverNewsProvider
from .service import NewsService
from .sentiment import NewsSentimentAnalyzer, NewsSentimentResult, analyze_stock_news_sentiment

__all__ = [
    "NewsProvider",
    "NewsArticle",
    "NewsSearchResult",
    "QuotaExceededError",
    "NewsProviderError",
    "NaverNewsProvider",
    "NewsService",
    "NewsSentimentAnalyzer",
    "NewsSentimentResult",
    "analyze_stock_news_sentiment",
]
