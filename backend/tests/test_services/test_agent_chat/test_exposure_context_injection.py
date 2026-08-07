"""레짐 인지 노출도(Task 8, 2026-08-07) — 초과분 토론 주입 배선 회귀 핀.

패턴은 C2(test_liquidity_context_injection.py)/US신호
(test_us_signal_injection.py)와 동일하다: `format_exposure_context`가 순수
함수로만 테스트되고 coordinator 배선이 검증 안 되면, "이 문자열을 기존
토론 프롬프트 구성부에 한 줄로 덧붙인다"는 문장이 실제로는 아무 데도 안
닿아도 스위트가 그린일 수 있다.

주입 경로는 `strategy_directive`다 -- `ChatRoom.__init__`이 이미 5개
에이전트(technical/fundamental/sentiment/risk/moderator) 전원의 시스템
프롬프트에 배포하는 broadcast 경로를 그대로 탄다
(`base_agent._effective_system_prompt`). 새 필드·새 배선을 추가하지
않는다 -- 투표 파싱·합의 문턱·실행 경로는 한 글자도 바뀌지 않는다.

실 네트워크·실 LLM·실 DB 금지.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest


def _chart_df(n: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2026-06-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": [50_000] * n, "high": [50_000] * n, "low": [50_000] * n,
            "close": [50_000] * n, "volume": [1_000] * n,
        },
        index=idx,
    )


def _stock_info():
    return {"stk_cd": "005930", "stk_nm": "삼성전자", "cur_prc": 50_000, "prdy_ctrt": 0.5}


def _account(stock_value=400_000_000, cash=100_000_000):
    """총자산 5억, 주식비중 80% -- 목표(예: 30%)를 크게 넘는 시나리오."""
    account = MagicMock()
    account.d2_ord_psbl_amt = cash
    account.evlu_amt = stock_value
    account.holdings = []
    return account


def _mock_empty_news_service():
    news_service = MagicMock()
    news_service.providers = []
    return news_service


def _patches(account_or_error, judgment_row=None, target=0.30, enabled=True):
    client = MagicMock()
    if isinstance(account_or_error, Exception):
        client_getter = AsyncMock(side_effect=account_or_error)
    else:
        client.get_account_balance = AsyncMock(return_value=account_or_error)
        client_getter = AsyncMock(return_value=client)

    storage = MagicMock()
    storage.get_latest_regime_judgment = AsyncMock(return_value=judgment_row)

    settings = MagicMock()
    settings.REGIME_EXPOSURE_ENABLED = enabled

    return (
        patch("agents.tools.kr_market_data.get_kr_stock_info",
              AsyncMock(return_value=_stock_info())),
        patch("agents.tools.kr_market_data.get_kr_daily_chart",
              AsyncMock(return_value=_chart_df())),
        patch("agents.tools.kr_market_data.calculate_kr_technical_indicators",
              MagicMock(return_value={})),
        patch("app.core.kiwoom_singleton.get_shared_kiwoom_client_async", client_getter),
        patch("app.dependencies.get_news_service",
              AsyncMock(return_value=_mock_empty_news_service())),
        patch("services.agent_chat.coordinator.get_settings",
              MagicMock(return_value=settings)),
        patch("services.trading.regime_judge.get_effective_target",
              AsyncMock(return_value=target)),
        # coordinator.py는 `from services.storage_service import
        # get_storage_service`로 모듈 상단에서 바인딩한다 -- 패치 대상은
        # 원본(`services.storage_service.get_storage_service`)이 아니라
        # 이미 바인딩된 이 모듈의 속성이어야 한다.
        patch("services.agent_chat.coordinator.get_storage_service",
              AsyncMock(return_value=storage)),
    )


class TestExposureContextWiring:
    @pytest.fixture
    def coordinator(self):
        from services.agent_chat.coordinator import ChatCoordinator

        return ChatCoordinator(
            check_interval_minutes=5,
            max_concurrent_discussions=3,
            min_discussion_interval_minutes=30,
        )

    async def test_over_target_line_reaches_strategy_directive(self, coordinator):
        """목표 30%, 실제 80% -- 초과 사실이 strategy_directive에 실제로
        얹혀야 한다. 이게 없으면 5개 에이전트 중 누구도 이 정보를 못 본다."""
        patches = _patches(
            _account(stock_value=400_000_000, cash=100_000_000),
            judgment_row={"regime": "bear"},
            target=0.30,
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7]:
            ctx = await coordinator._fetch_market_context("005930", "삼성전자")

        assert ctx.strategy_directive is not None
        assert "목표 주식비중 30.0%" in ctx.strategy_directive
        assert "현재 80.0%" in ctx.strategy_directive
        assert "초과" in ctx.strategy_directive
        assert "(레짐 bear)" in ctx.strategy_directive

    async def test_broadcasts_to_all_five_agents_via_strategy_directive(self, coordinator):
        """새 필드·새 배선 없음 계약: ChatRoom이 기존 strategy_directive
        broadcast 경로로 5개 에이전트 전원에 뿌린다는 것을 직접 확인한다."""
        from services.agent_chat.chat_room import ChatRoom
        from services.agent_chat.models import AgentType

        patches = _patches(
            _account(stock_value=400_000_000, cash=100_000_000),
            judgment_row={"regime": "bear"},
            target=0.30,
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7]:
            ctx = await coordinator._fetch_market_context("005930", "삼성전자")

        room = ChatRoom(ticker="005930", stock_name="삼성전자", context=ctx)
        for agent_type in AgentType:
            agent = room.agents[agent_type]
            assert agent.strategy_directive is not None
            assert "초과" in agent.strategy_directive
            assert "초과" in agent._effective_system_prompt()

    async def test_under_target_has_no_excess_language(self, coordinator):
        """목표 미달이면 '초과' 문구가 없어야 한다 -- 있지도 않은 초과를
        패널이 오인하면 안 된다."""
        patches = _patches(
            _account(stock_value=100_000_000, cash=400_000_000),  # 20%
            judgment_row={"regime": "neutral"},
            target=0.30,
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7]:
            ctx = await coordinator._fetch_market_context("005930", "삼성전자")

        assert ctx.strategy_directive is not None
        assert "초과" not in ctx.strategy_directive
        assert "현재 20.0%" in ctx.strategy_directive

    async def test_kill_switch_off_never_injects(self, coordinator):
        """REGIME_EXPOSURE_ENABLED off -- 배포 시 기본값. 어떤 계산도
        일어나면 안 된다(get_effective_target 미호출)."""
        patches = _patches(
            _account(stock_value=400_000_000, cash=100_000_000),
            judgment_row={"regime": "bear"},
            target=0.30,
            enabled=False,
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7] as target_mock:
            ctx = await coordinator._fetch_market_context("005930", "삼성전자")

        assert ctx.strategy_directive is None
        target_mock.assert_not_called()

    async def test_no_effective_target_yields_no_injection(self, coordinator):
        """판정이 아직 없으면(get_effective_target -> None) 아무것도
        얹지 않는다 -- format_exposure_context(None, ...) == ''와 일관."""
        patches = _patches(
            _account(stock_value=400_000_000, cash=100_000_000),
            judgment_row=None,
            target=None,
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7]:
            ctx = await coordinator._fetch_market_context("005930", "삼성전자")

        assert ctx.strategy_directive is None

    async def test_account_unavailable_never_blocks_discussion(self, coordinator):
        """never-raise: 계좌 조회 실패해도 토론은 그대로 진행되고
        is_stale도 켜지지 않는다(주입 실패는 best-effort)."""
        patches = _patches(
            RuntimeError("no account access"),
            judgment_row={"regime": "bear"},
            target=0.30,
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7]:
            ctx = await coordinator._fetch_market_context("005930", "삼성전자")

        assert ctx.is_stale is False
        assert ctx.strategy_directive is None

    async def test_vote_parsing_and_consensus_threshold_unaffected(self, coordinator):
        """사용자 결정의 핵심 제약: 초과 주입이 투표 파싱·합의 문턱을
        건드리지 않는다 -- consensus_threshold는 여전히 전략 컨텍스트
        (여기서는 미설정 기본값 0.75)에서만 나온다."""
        patches = _patches(
            _account(stock_value=400_000_000, cash=100_000_000),
            judgment_row={"regime": "bear"},
            target=0.30,
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7]:
            ctx = await coordinator._fetch_market_context("005930", "삼성전자")

        assert ctx.consensus_threshold == 0.75
