"""US 신호 T4: sentiment 토론에 US AI 신호를 프롬프트 넛지로 주입.

- MarketContext.us_market_context: Optional[str] = None (strategy_directive와
  동일한 optional-field 패턴).
- coordinator._fetch_market_context가 AI밸류체인 종목 + 당일 캐시 신호가 있을
  때만 채운다(비-AI밸류체인/off/결측 -> None, 주입 안 함).
- sentiment_agent의 analysis/vote 프롬프트에 값이 있으면 그대로 노출되고,
  없으면 빈 문자열(불변) — 투표/confidence 로직은 절대 건드리지 않는다(실
  LLM/네트워크 금지, LLM 호출은 항상 목).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from services.agent_chat.models import MarketContext


def _context(**kw):
    return MarketContext(
        ticker="005930", stock_name="삼성전자",
        current_price=70000, price_change_pct=1.0, **kw,
    )


# ---------- MarketContext field ----------


def test_market_context_has_us_field_default_none():
    ctx = _context()
    assert getattr(ctx, "us_market_context", "MISSING") is None


def test_market_context_us_field_settable():
    ctx = _context(us_market_context="간밤 미 AI 반도체 강세(SMH +4.5%)")
    assert ctx.us_market_context == "간밤 미 AI 반도체 강세(SMH +4.5%)"


# ---------- sentiment agent prompt injection (LLM 항상 목) ----------


class TestSentimentPromptInjection:
    """analyze()/vote()가 실제로 만드는 프롬프트를 self.llm.generate(_structured)
    를 목킹해 캡처하고 검증한다 — 템플릿 상수만 보는 게 아니라 .format(...)
    호출부까지 왕복 검증(회귀 시 실제로 값을 안 넘겨도 템플릿-only 테스트는
    못 잡는다)."""

    async def test_analysis_prompt_includes_us_context_when_set(self):
        from services.agent_chat.agents.sentiment_agent import (
            SentimentDiscussionAgent,
        )

        agent = SentimentDiscussionAgent()
        ctx = _context(us_market_context="간밤 미 AI 반도체 강세(SMH +4.5%)")

        captured = {}

        async def fake_generate(messages):
            captured["prompt"] = messages[-1].content
            return "신뢰도: 70%"

        agent.llm.generate = AsyncMock(side_effect=fake_generate)

        await agent.analyze(ctx)

        assert "prompt" in captured
        assert "간밤 미 AI 반도체 강세(SMH +4.5%)" in captured["prompt"]

    async def test_analysis_prompt_empty_when_us_context_none(self):
        from services.agent_chat.agents.sentiment_agent import (
            SentimentDiscussionAgent,
        )

        agent = SentimentDiscussionAgent()
        ctx = _context()  # us_market_context defaults None

        captured = {}

        async def fake_generate(messages):
            captured["prompt"] = messages[-1].content
            return "신뢰도: 70%"

        agent.llm.generate = AsyncMock(side_effect=fake_generate)

        await agent.analyze(ctx)

        assert "prompt" in captured
        # 빈 문자열로 치환 — 리터럴 "None"이 새어나오면 안 된다(포맷 버그).
        assert "None" not in captured["prompt"]
        assert "간밤" not in captured["prompt"]

    async def test_vote_prompt_includes_us_context_when_set(self):
        from services.agent_chat.agents.sentiment_agent import (
            SentimentDiscussionAgent,
        )

        agent = SentimentDiscussionAgent()
        ctx = _context(us_market_context="간밤 미 AI 반도체 강세(SMH +4.5%)")

        # 구조화 투표 경로를 실패시켜 regex 폴백(=_call_llm)으로 강제 — 그
        # 경로가 실제 vote_prompt_template.format(...)을 호출한다.
        agent.llm.generate_structured = AsyncMock(side_effect=RuntimeError("force fallback"))

        captured = {}

        async def fake_generate(messages):
            captured["prompt"] = messages[-1].content
            return "투표: BUY\n신뢰도: 70%"

        agent.llm.generate = AsyncMock(side_effect=fake_generate)

        await agent.vote(ctx, [])

        assert "prompt" in captured
        assert "간밤 미 AI 반도체 강세(SMH +4.5%)" in captured["prompt"]

    async def test_vote_prompt_empty_when_us_context_none(self):
        from services.agent_chat.agents.sentiment_agent import (
            SentimentDiscussionAgent,
        )

        agent = SentimentDiscussionAgent()
        ctx = _context()

        agent.llm.generate_structured = AsyncMock(side_effect=RuntimeError("force fallback"))

        captured = {}

        async def fake_generate(messages):
            captured["prompt"] = messages[-1].content
            return "투표: BUY\n신뢰도: 70%"

        agent.llm.generate = AsyncMock(side_effect=fake_generate)

        await agent.vote(ctx, [])

        assert "prompt" in captured
        assert "None" not in captured["prompt"]
        assert "간밤" not in captured["prompt"]

    async def test_confidence_and_vote_logic_unchanged_by_us_context(self):
        """넛지가 순수 프롬프트 노출만이라는 CRITICAL 제약의 회귀 가드 —
        뉴스 데이터 없음 confidence 캡(<=0.5)이 us_market_context 유무와
        무관하게 그대로 적용돼야 한다(하드코딩 투표 밀기 금지)."""
        from services.agent_chat.agents.sentiment_agent import (
            SentimentDiscussionAgent,
        )

        agent = SentimentDiscussionAgent()
        # news_sentiment/news_count 없음 -> confidence 캡 발동 조건
        ctx = _context(us_market_context="간밤 미 AI 반도체 강세(SMH +4.5%)")

        agent.llm.generate = AsyncMock(return_value="신뢰도: 90%")

        result = await agent.analyze(ctx)

        assert result.confidence <= 0.5


# ---------- coordinator._fetch_market_context wiring ----------


def _mock_empty_news_service():
    news_service = MagicMock()
    news_service.providers = []
    return news_service


def _stock_info(ticker="005930", name="삼성전자"):
    return {
        "stk_cd": ticker,
        "stk_nm": name,
        "cur_prc": 72500,
        "prdy_ctrt": 0.5,
    }


class TestUsMarketContextWiring:
    """coordinator._fetch_market_context가 AI밸류체인 종목+당일 캐시 신호
    존재 시에만 us_market_context를 채우는지 확인. 실 네트워크/실 LLM 금지 —
    get_cached_us_ai_signal은 항상 목."""

    @pytest.fixture
    def coordinator(self):
        from services.agent_chat.coordinator import ChatCoordinator
        return ChatCoordinator(
            check_interval_minutes=5,
            max_concurrent_discussions=3,
            min_discussion_interval_minutes=30,
        )

    async def test_ai_valuechain_with_cached_signal_fills_context(self, coordinator):
        cached_signal = {
            "signal": 0.6,
            "signal_pct": 1.8,
            "components": {"SMH": 4.5, "MU": 3.0, "NVDA": 2.0},
            "as_of": "2026-07-22",
        }
        with (
            patch(
                "agents.tools.kr_market_data.get_kr_stock_info",
                AsyncMock(return_value=_stock_info()),
            ),
            patch(
                "agents.tools.kr_market_data.get_kr_daily_chart",
                AsyncMock(return_value=pd.DataFrame()),
            ),
            patch(
                "app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
                AsyncMock(side_effect=RuntimeError("no account access")),
            ),
            patch(
                "app.dependencies.get_news_service",
                AsyncMock(return_value=_mock_empty_news_service()),
            ),
            patch(
                "services.trading.us_market_data.get_cached_us_ai_signal",
                AsyncMock(return_value=cached_signal),
            ),
        ):
            context = await coordinator._fetch_market_context("005930", "삼성전자")

        assert context.us_market_context is not None
        assert "SMH" in context.us_market_context

    async def test_non_ai_valuechain_ticker_leaves_context_none(self, coordinator):
        with (
            patch(
                "agents.tools.kr_market_data.get_kr_stock_info",
                AsyncMock(return_value=_stock_info(ticker="035720", name="카카오")),
            ),
            patch(
                "agents.tools.kr_market_data.get_kr_daily_chart",
                AsyncMock(return_value=pd.DataFrame()),
            ),
            patch(
                "app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
                AsyncMock(side_effect=RuntimeError("no account access")),
            ),
            patch(
                "app.dependencies.get_news_service",
                AsyncMock(return_value=_mock_empty_news_service()),
            ),
            patch(
                "services.trading.us_market_data.get_cached_us_ai_signal",
                AsyncMock(return_value={
                    "signal": 0.6, "signal_pct": 1.8,
                    "components": {"SMH": 4.5}, "as_of": "2026-07-22",
                }),
            ) as mock_signal,
        ):
            context = await coordinator._fetch_market_context("035720", "카카오")

        assert context.us_market_context is None
        mock_signal.assert_not_called()

    async def test_ai_valuechain_no_cached_signal_leaves_context_none(self, coordinator):
        with (
            patch(
                "agents.tools.kr_market_data.get_kr_stock_info",
                AsyncMock(return_value=_stock_info()),
            ),
            patch(
                "agents.tools.kr_market_data.get_kr_daily_chart",
                AsyncMock(return_value=pd.DataFrame()),
            ),
            patch(
                "app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
                AsyncMock(side_effect=RuntimeError("no account access")),
            ),
            patch(
                "app.dependencies.get_news_service",
                AsyncMock(return_value=_mock_empty_news_service()),
            ),
            patch(
                "services.trading.us_market_data.get_cached_us_ai_signal",
                AsyncMock(return_value=None),  # off/미존재/stale
            ),
        ):
            context = await coordinator._fetch_market_context("005930", "삼성전자")

        assert context.us_market_context is None

    async def test_us_signal_build_failure_is_none_not_raised(self, coordinator):
        """never-raise: get_cached_us_ai_signal 예외는 로그만, 토론을 막지
        않는다(is_stale 승격 없이 context는 정상 반환)."""
        with (
            patch(
                "agents.tools.kr_market_data.get_kr_stock_info",
                AsyncMock(return_value=_stock_info()),
            ),
            patch(
                "agents.tools.kr_market_data.get_kr_daily_chart",
                AsyncMock(return_value=pd.DataFrame()),
            ),
            patch(
                "app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
                AsyncMock(side_effect=RuntimeError("no account access")),
            ),
            patch(
                "app.dependencies.get_news_service",
                AsyncMock(return_value=_mock_empty_news_service()),
            ),
            patch(
                "services.trading.us_market_data.get_cached_us_ai_signal",
                AsyncMock(side_effect=RuntimeError("storage down")),
            ),
        ):
            context = await coordinator._fetch_market_context("005930", "삼성전자")

        assert context.us_market_context is None
        assert context.is_stale is False
