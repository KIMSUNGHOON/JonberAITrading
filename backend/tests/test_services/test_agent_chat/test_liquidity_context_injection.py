"""C2(유동성 인지) 배선 회귀 핀 — 최종 리뷰가 지목한 검출 갭.

최종 리뷰가 확인한 사실: `liquidity_context`/`position_notional`/`is_new_entry`
가 순수함수 테스트 파일(`test_agent_chat_liquidity_note.py`) 밖에서 전혀
참조되지 않아, coordinator→MarketContext→risk_agent 프롬프트 배선을 통째로
삭제해도 스위트가 그린이었다. 같은 아크의 T6가 사이징 캡에서 정확히 같은
패턴을 자기 적발해 `test_liquidity_sizing_wiring.py`로 봉합한 전례가 있다 —
이 파일이 C2쪽 같은 조치다.

여기서 고정하는 계약:
1. `coordinator._fetch_market_context`가 `liquidity_context`를 실제로 채우고
   그 값이 risk_agent 프롬프트(analysis/vote 양쪽)까지 도달한다.
2. 판정 지시문은 유동성 수치 줄과 **함께** 나타나고 **함께** 사라진다
   (Blocking1 회귀 핀 — 지시문이 템플릿 본문으로 돌아가면 여기서 깨진다).
3. 보유(is_new_entry=False)와 신규(True)의 판정 지시문이 다르다 — 보유
   포지션에 전량청산 지시가 흘러가면 안 된다.
4. 유동성 주입은 넛지일 뿐 투표 로직을 바꾸지 않는다(기존 US 신호 계약과 동일).

실 네트워크·실 LLM 금지 — LLM은 항상 목.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from services.agent_chat.models import MarketContext

VERDICT_MARKER = "유동성 판정 기준"

# 라이브 실 포지션(094840 슈프리마HQ) 자릿수를 재현 — 참여율 약 3.8%.
_PRICE = 20_000
_QTY = 1_315
_ADTV = 700_000_000.0  # 7억 -> 1,315 x 20,000 / 7억 = 3.76%


def _context(**kw) -> MarketContext:
    return MarketContext(
        ticker="094840", stock_name="슈프리마에이치큐",
        current_price=_PRICE, price_change_pct=1.0, **kw,
    )


# ---------------------------------------------------------------------------
# 1) risk_agent 프롬프트 왕복 — 템플릿 상수가 아니라 .format(...) 호출부까지
# ---------------------------------------------------------------------------


async def _capture_analysis_prompt(ctx: MarketContext) -> str:
    from services.agent_chat.agents.risk_agent import RiskDiscussionAgent

    agent = RiskDiscussionAgent()
    captured = {}

    async def fake_generate(messages):
        captured["prompt"] = messages[-1].content
        return "신뢰도: 70%"

    agent.llm.generate = AsyncMock(side_effect=fake_generate)
    await agent.analyze(ctx)
    return captured["prompt"]


async def _capture_vote_prompt(ctx: MarketContext) -> str:
    from services.agent_chat.agents.risk_agent import RiskDiscussionAgent

    agent = RiskDiscussionAgent()
    # 구조화 투표를 실패시켜 regex 폴백으로 강제 — 그 경로가 실제
    # vote_prompt_template.format(...)을 호출한다(US 신호 테스트와 동일 패턴).
    agent.llm.generate_structured = AsyncMock(side_effect=RuntimeError("force fallback"))
    captured = {}

    async def fake_generate(messages):
        captured["prompt"] = messages[-1].content
        return "투표: HOLD\n신뢰도: 70%"

    agent.llm.generate = AsyncMock(side_effect=fake_generate)
    await agent.vote(ctx, [])
    return captured["prompt"]


class TestRiskPromptLiquidityInjection:
    async def test_analysis_prompt_carries_note_and_verdict(self):
        from services.agent_chat.liquidity_note import build_liquidity_note

        note = build_liquidity_note(_ADTV, _PRICE * _QTY, is_new_entry=False)
        prompt = await _capture_analysis_prompt(_context(liquidity_context=note))

        assert "일평균 거래대금" in prompt
        assert "3.8%" in prompt
        assert VERDICT_MARKER in prompt

    async def test_vote_prompt_carries_note_and_verdict(self):
        """두 단계 기준 대칭 — analysis에만 있던 비대칭의 회귀 핀."""
        from services.agent_chat.liquidity_note import build_liquidity_note

        note = build_liquidity_note(_ADTV, _PRICE * _QTY, is_new_entry=False)
        prompt = await _capture_vote_prompt(_context(liquidity_context=note))

        assert "일평균 거래대금" in prompt
        assert VERDICT_MARKER in prompt

    @pytest.mark.parametrize("capture", [_capture_analysis_prompt, _capture_vote_prompt])
    async def test_verdict_absent_when_note_absent(self, capture):
        """⚠️ Blocking1 핵심 핀: 유동성 줄이 없으면 판정 지시문도 없어야 한다.

        지시문이 프롬프트 템플릿 본문으로 돌아가면 (chart_df 빈 DF /
        total_portfolio 결측 / ADTV 표본 부족 경로에서) 수치 없이 지시만 남아
        LLM이 존재하지 않는 '위 참여율'을 판정하게 된다."""
        prompt = await capture(_context())  # liquidity_context 기본 None

        assert VERDICT_MARKER not in prompt
        assert "참여율" not in prompt
        assert "None" not in prompt  # 포맷 버그로 리터럴 None이 새면 안 된다

    async def test_holding_and_new_entry_verdicts_differ_in_prompt(self):
        """보유 포지션 토론에 '반대표(SELL)'가 흘러가면 전량청산 지시가 된다."""
        from services.agent_chat.liquidity_note import build_liquidity_note

        holding = await _capture_analysis_prompt(
            _context(
                liquidity_context=build_liquidity_note(
                    _ADTV, _PRICE * _QTY, is_new_entry=False
                )
            )
        )
        new_entry = await _capture_analysis_prompt(
            _context(
                liquidity_context=build_liquidity_note(
                    _ADTV, _PRICE * _QTY, is_new_entry=True
                )
            )
        )

        assert "반대표" in new_entry
        assert "반대표" not in holding
        assert "즉시 청산의 근거가 아닙니다" in holding

    async def test_vote_direction_unchanged_by_liquidity_context(self):
        """넛지 계약(US 신호와 동일): 같은 LLM 응답이면 유동성 주입 유무와
        무관하게 vote()가 도출하는 방향/신뢰도가 같아야 한다."""
        from services.agent_chat.agents.risk_agent import RiskDiscussionAgent
        from services.agent_chat.liquidity_note import build_liquidity_note

        response_text = "투표: BUY\n신뢰도: 70%\n포지션: 5%\n손절가: -5%\n익절가: +10%"
        note = build_liquidity_note(_ADTV, _PRICE * _QTY, is_new_entry=True)

        results = {}
        for label, liq in (("with", note), ("without", None)):
            agent = RiskDiscussionAgent()
            agent.llm.generate_structured = AsyncMock(
                side_effect=RuntimeError("force fallback")
            )
            agent.llm.generate = AsyncMock(return_value=response_text)
            results[label] = await agent.vote(_context(liquidity_context=liq), [])

        assert results["with"].vote == results["without"].vote
        assert results["with"].confidence == results["without"].confidence
        assert results["with"].suggested_position_pct == results["without"].suggested_position_pct


# ---------------------------------------------------------------------------
# 2) coordinator._fetch_market_context 배선 — liquidity_context가 실제로 채워지나
# ---------------------------------------------------------------------------


def _chart_df(n: int = 30, daily_value: float = _ADTV) -> pd.DataFrame:
    idx = pd.date_range("2026-06-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": [_PRICE] * n,
            "high": [_PRICE] * n,
            "low": [_PRICE] * n,
            "close": [_PRICE] * n,
            "volume": [daily_value / _PRICE] * n,
            "value": [daily_value] * n,
        },
        index=idx,
    )


def _stock_info():
    return {"stk_cd": "094840", "stk_nm": "슈프리마에이치큐", "cur_prc": _PRICE, "prdy_ctrt": 0.5}


def _account(holding_qty=None):
    account = MagicMock()
    account.d2_ord_psbl_amt = 100_000_000
    account.evlu_amt = 400_000_000
    if holding_qty:
        holding = MagicMock()
        holding.stk_cd = "094840"
        holding.hldg_qty = holding_qty
        holding.avg_buy_prc = _PRICE
        holding.evlu_pfls_rt = 1.5
        account.holdings = [holding]
    else:
        account.holdings = []
    return account


def _mock_empty_news_service():
    news_service = MagicMock()
    news_service.providers = []
    return news_service


def _coordinator_patches(chart_df, account_or_error):
    client = MagicMock()
    if isinstance(account_or_error, Exception):
        client_getter = AsyncMock(side_effect=account_or_error)
    else:
        client.get_account_balance = AsyncMock(return_value=account_or_error)
        client_getter = AsyncMock(return_value=client)

    return (
        patch(
            "agents.tools.kr_market_data.get_kr_stock_info",
            AsyncMock(return_value=_stock_info()),
        ),
        patch(
            "agents.tools.kr_market_data.get_kr_daily_chart",
            AsyncMock(return_value=chart_df),
        ),
        patch(
            "agents.tools.kr_market_data.calculate_kr_technical_indicators",
            MagicMock(return_value={}),
        ),
        patch("app.core.kiwoom_singleton.get_shared_kiwoom_client_async", client_getter),
        patch(
            "app.dependencies.get_news_service",
            AsyncMock(return_value=_mock_empty_news_service()),
        ),
    )


class TestLiquidityContextWiring:
    @pytest.fixture
    def coordinator(self):
        from services.agent_chat.coordinator import ChatCoordinator

        return ChatCoordinator(
            check_interval_minutes=5,
            max_concurrent_discussions=3,
            min_discussion_interval_minutes=30,
        )

    async def test_holding_position_fills_context_with_holding_verdict(self, coordinator):
        """실 보유 포지션 경로 — 참여율은 수량x현재가 기준, 지시문은 보유용."""
        p1, p2, p3, p4, p5 = _coordinator_patches(_chart_df(), _account(holding_qty=_QTY))
        with p1, p2, p3, p4, p5:
            ctx = await coordinator._fetch_market_context("094840", "슈프리마에이치큐")

        assert ctx.has_position is True
        assert ctx.liquidity_context, "보유 포지션인데 유동성 줄이 비었다 — C2 배선 회귀"
        assert "이 포지션의 참여율" in ctx.liquidity_context
        assert "3.8%" in ctx.liquidity_context
        assert VERDICT_MARKER in ctx.liquidity_context
        assert "반대표" not in ctx.liquidity_context

    async def test_new_candidate_fills_context_with_new_entry_verdict(self, coordinator):
        """미보유 후보 — T3 게이트 가정(계좌 4%)을 재사용, 지시문은 신규용."""
        p1, p2, p3, p4, p5 = _coordinator_patches(_chart_df(), _account())
        with p1, p2, p3, p4, p5:
            ctx = await coordinator._fetch_market_context("094840", "슈프리마에이치큐")

        assert ctx.has_position is False
        assert ctx.liquidity_context
        assert "예상 진입 규모 기준 참여율" in ctx.liquidity_context
        assert "반대표" in ctx.liquidity_context

    async def test_empty_chart_leaves_context_empty(self, coordinator):
        """chart_df 빈 DF 경로(coordinator.py의 실제 폴백) — ADTV 계산 불가.
        수치도 지시문도 없어야 한다."""
        p1, p2, p3, p4, p5 = _coordinator_patches(pd.DataFrame(), _account(holding_qty=_QTY))
        with p1, p2, p3, p4, p5:
            ctx = await coordinator._fetch_market_context("094840", "슈프리마에이치큐")

        assert not ctx.liquidity_context
        assert VERDICT_MARKER not in (ctx.liquidity_context or "")

    async def test_account_unavailable_leaves_new_entry_context_empty(self, coordinator):
        """total_portfolio 결측 경로 — 신규 후보의 notional을 지어내지 않는다."""
        p1, p2, p3, p4, p5 = _coordinator_patches(
            _chart_df(), RuntimeError("no account access")
        )
        with p1, p2, p3, p4, p5:
            ctx = await coordinator._fetch_market_context("094840", "슈프리마에이치큐")

        assert not ctx.liquidity_context

    async def test_liquidity_build_failure_never_blocks_discussion(self, coordinator):
        """never-raise: adtv_median이 터져도 토론은 진행되고 is_stale도 안 켜진다."""
        p1, p2, p3, p4, p5 = _coordinator_patches(_chart_df(), _account(holding_qty=_QTY))
        with p1, p2, p3, p4, p5, patch(
            "services.discovery.liquidity.adtv_median",
            MagicMock(side_effect=RuntimeError("boom")),
        ):
            ctx = await coordinator._fetch_market_context("094840", "슈프리마에이치큐")

        assert not ctx.liquidity_context
        assert ctx.is_stale is False
