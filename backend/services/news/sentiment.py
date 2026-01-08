"""
News Sentiment Analyzer

LLM-based sentiment analysis for news articles.
Provides structured sentiment output for integration with trading agents.
"""

import json
import re
from typing import List, Optional
from pydantic import BaseModel, Field

import structlog
from langchain_core.messages import SystemMessage, HumanMessage

from .base import NewsArticle

logger = structlog.get_logger()


class NewsSentimentResult(BaseModel):
    """Structured sentiment analysis result."""
    sentiment: str = Field(
        description="Overall sentiment: positive, neutral, or negative"
    )
    score: int = Field(
        ge=-100, le=100,
        description="Sentiment score from -100 (very negative) to 100 (very positive)"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence level of the analysis"
    )
    summary: str = Field(
        description="2-3 sentence summary of the news sentiment"
    )
    key_topics: List[str] = Field(
        default_factory=list,
        description="Key topics mentioned in the news"
    )
    risk_factors: List[str] = Field(
        default_factory=list,
        description="Identified risk factors from the news"
    )
    positive_factors: List[str] = Field(
        default_factory=list,
        description="Identified positive factors from the news"
    )
    recommendation: str = Field(
        default="HOLD",
        description="Trading recommendation based on sentiment: BUY, SELL, or HOLD"
    )


class NewsSentimentAnalyzer:
    """
    LLM-based news sentiment analyzer.

    Analyzes news articles to extract:
    - Overall sentiment (positive/neutral/negative)
    - Sentiment score (-100 to 100)
    - Key topics and risk factors
    - Trading recommendation
    """

    SENTIMENT_PROMPT = """당신은 금융 뉴스 감성 분석 전문가입니다.
주어진 뉴스 기사들을 분석하여 해당 종목에 대한 시장 심리를 평가하세요.

분석 시 고려사항:
1. 뉴스의 전반적인 톤 (긍정적/중립적/부정적)
2. 주요 이슈 및 테마
3. 잠재적 리스크 요인
4. 긍정적 요인 (실적, 신규 계약, 시장 확대 등)
5. 부정적 요인 (소송, 규제, 실적 악화 등)

반드시 다음 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{
    "sentiment": "positive" | "neutral" | "negative",
    "score": -100에서 100 사이의 정수 (부정 ~ 긍정),
    "confidence": 0.0에서 1.0 사이의 실수,
    "summary": "2-3문장 요약",
    "key_topics": ["주요 토픽1", "주요 토픽2"],
    "risk_factors": ["리스크 요인1"] (있는 경우만),
    "positive_factors": ["긍정 요인1"] (있는 경우만),
    "recommendation": "BUY" | "SELL" | "HOLD"
}"""

    def __init__(self, llm_provider):
        """
        Initialize the sentiment analyzer.

        Args:
            llm_provider: LLM provider instance for generating analysis
        """
        self.llm = llm_provider

    async def analyze(
        self,
        articles: List[NewsArticle],
        stock_name: str,
        stock_code: Optional[str] = None,
    ) -> NewsSentimentResult:
        """
        Analyze news articles for sentiment.

        Args:
            articles: List of news articles to analyze
            stock_name: Name of the stock for context
            stock_code: Optional stock code

        Returns:
            NewsSentimentResult with structured sentiment data
        """
        if not articles:
            logger.info("no_articles_for_sentiment", stock_name=stock_name)
            return NewsSentimentResult(
                sentiment="neutral",
                score=0,
                confidence=0.3,
                summary=f"{stock_name} 관련 최근 뉴스가 없습니다.",
                key_topics=[],
                risk_factors=[],
                positive_factors=[],
                recommendation="HOLD",
            )

        # Format articles for LLM
        articles_text = self._format_articles(articles[:15])  # Limit to 15 articles

        user_prompt = f"""종목: {stock_name}"""
        if stock_code:
            user_prompt += f" ({stock_code})"
        user_prompt += f"\n\n최근 뉴스 ({len(articles)}건):\n{articles_text}"

        messages = [
            SystemMessage(content=self.SENTIMENT_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        try:
            logger.debug("sentiment_analysis_request", stock_name=stock_name, article_count=len(articles))
            response = await self.llm.generate(messages)
            result = self._parse_response(response, stock_name)
            logger.info(
                "sentiment_analysis_complete",
                stock_name=stock_name,
                sentiment=result.sentiment,
                score=result.score,
            )
            return result

        except Exception as e:
            logger.error("sentiment_analysis_failed", stock_name=stock_name, error=str(e))
            return NewsSentimentResult(
                sentiment="neutral",
                score=0,
                confidence=0.2,
                summary=f"{stock_name} 뉴스 분석 중 오류가 발생했습니다.",
                key_topics=[],
                risk_factors=[],
                positive_factors=[],
                recommendation="HOLD",
            )

    def _format_articles(self, articles: List[NewsArticle]) -> str:
        """Format articles for LLM input."""
        lines = []
        for i, article in enumerate(articles, 1):
            # Clean title
            title = article.title.strip()
            # Add source if available
            source = f" [{article.source}]" if article.source else ""
            # Add date
            date_str = article.pub_date.strftime("%Y-%m-%d") if article.pub_date else ""
            date_part = f" ({date_str})" if date_str else ""

            lines.append(f"{i}. {title}{source}{date_part}")

            # Add description if available (truncated)
            if article.description:
                desc = article.description.strip()[:150]
                if len(article.description) > 150:
                    desc += "..."
                lines.append(f"   {desc}")

        return "\n".join(lines)

    def _parse_response(self, response: str, stock_name: str) -> NewsSentimentResult:
        """Parse LLM response into structured result."""
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            logger.warning("no_json_in_response", response_preview=response[:200])
            return self._create_fallback_result(response, stock_name)

        try:
            data = json.loads(json_match.group())

            # Validate and extract fields with defaults
            sentiment = data.get("sentiment", "neutral")
            if sentiment not in ("positive", "neutral", "negative"):
                sentiment = "neutral"

            score = data.get("score", 0)
            if not isinstance(score, (int, float)):
                score = 0
            score = max(-100, min(100, int(score)))

            confidence = data.get("confidence", 0.5)
            if not isinstance(confidence, (int, float)):
                confidence = 0.5
            confidence = max(0.0, min(1.0, float(confidence)))

            recommendation = data.get("recommendation", "HOLD")
            if recommendation not in ("BUY", "SELL", "HOLD"):
                recommendation = "HOLD"

            return NewsSentimentResult(
                sentiment=sentiment,
                score=score,
                confidence=confidence,
                summary=data.get("summary", f"{stock_name} 뉴스 분석 완료"),
                key_topics=data.get("key_topics", [])[:5],
                risk_factors=data.get("risk_factors", [])[:5],
                positive_factors=data.get("positive_factors", [])[:5],
                recommendation=recommendation,
            )

        except json.JSONDecodeError as e:
            logger.warning("json_parse_failed", error=str(e), response_preview=response[:200])
            return self._create_fallback_result(response, stock_name)

    def _create_fallback_result(self, response: str, stock_name: str) -> NewsSentimentResult:
        """Create fallback result when JSON parsing fails."""
        # Try to infer sentiment from keywords
        response_lower = response.lower()
        if any(word in response_lower for word in ["긍정", "positive", "상승", "호재", "매수"]):
            sentiment = "positive"
            score = 30
            recommendation = "BUY"
        elif any(word in response_lower for word in ["부정", "negative", "하락", "악재", "매도"]):
            sentiment = "negative"
            score = -30
            recommendation = "SELL"
        else:
            sentiment = "neutral"
            score = 0
            recommendation = "HOLD"

        return NewsSentimentResult(
            sentiment=sentiment,
            score=score,
            confidence=0.4,
            summary=response[:300] if len(response) > 300 else response,
            key_topics=[],
            risk_factors=[],
            positive_factors=[],
            recommendation=recommendation,
        )


async def analyze_stock_news_sentiment(
    stock_name: str,
    stock_code: str,
    news_service,
    llm_provider,
    article_count: int = 10,
) -> NewsSentimentResult:
    """
    Convenience function to fetch news and analyze sentiment.

    Args:
        stock_name: Name of the stock
        stock_code: Stock code
        news_service: NewsService instance
        llm_provider: LLM provider instance
        article_count: Number of articles to fetch

    Returns:
        NewsSentimentResult with structured sentiment data
    """
    try:
        # Search for news
        query = f"{stock_name} 주식"
        result = await news_service.search_stock_news(
            stock_code=stock_code,
            stock_name=stock_name,
            count=article_count,
        )

        # Analyze sentiment
        analyzer = NewsSentimentAnalyzer(llm_provider)
        return await analyzer.analyze(
            articles=result.articles,
            stock_name=stock_name,
            stock_code=stock_code,
        )

    except Exception as e:
        logger.error(
            "stock_news_sentiment_failed",
            stock_name=stock_name,
            stock_code=stock_code,
            error=str(e),
        )
        return NewsSentimentResult(
            sentiment="neutral",
            score=0,
            confidence=0.2,
            summary=f"{stock_name} 뉴스 조회 실패",
            key_topics=[],
            risk_factors=[],
            positive_factors=[],
            recommendation="HOLD",
        )
