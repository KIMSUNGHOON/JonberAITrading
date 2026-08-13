"""C1 (유동성 인지, 2026-07-27) 리뷰 수정 — 사이징 캡 배선 증명 + 저장값
폴백 + fail-open 가시성.

이 파일이 존재하는 이유(리뷰 Important1): task-6의 원래 그린 스위트는
`portfolio_agent.py`/`decision_nodes.py` 두 호출부에서 `apply_liquidity_cap`
호출을 통째로 삭제해도 동일한 결과를 냈다 — 모든 테스트의 kiwoom client
mock이 `get_daily_chart_df`를 stub하지 않아 매번 TypeError -> `adtv=None`
-> `"adtv_unknown"`(캡 미적용) 경로만 탔기 때문이다. 캡 수학 자체는
`test_r_sizing_liquidity.py`(순수 함수)와 `test_portfolio_agent_rebalance_market.py`
의 `test_calculate_max_position_value_applies_liquidity_cap_when_binding`가
mock 없이 이미 증명한다. 여기서는 "배선"만 별도로 증명한다:

1. `coordinator.on_trade_approved`가 실제로 `_resolve_adtv`를 호출하고 그
   결과를 `calculate_allocation(adtv=...)`으로 흘려보내는가(BUY만).
2. `_resolve_adtv`가 라이브 재계산 실패 시 T3가 `scan_results.factor_json`
   에 저장한 값으로 폴백하는가(Important2a).
3. `adtv_unknown`(캡 완전 비활성)이 조용히 사라지지 않고 로그로 남는가
   (Important2b).
"""

import logging
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.trading.coordinator import ExecutionCoordinator
from services.trading.market_hours import MarketSession
from services.trading.models import AllocationPlan, OrderResult, OrderSide, TradingMode
from services.trading.portfolio_agent import PortfolioAgent


def _open_session() -> MarketSession:
    return MarketSession(
        is_open=True,
        current_time=datetime.now(),
        next_open=None,
        next_close=None,
        message="open",
    )


def _live_coordinator() -> ExecutionCoordinator:
    """ACTIVE + market open으로 즉시 실행되는 코디네이터. test_r5_p0_
    autotrade_safety.py의 동명 헬퍼와 동일 패턴이지만 그 파일은 A1/A2/A5
    감사 전용이라 재사용하지 않고 이 파일 안에서 독립적으로 유지한다."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._state.mode = TradingMode.ACTIVE
    coord._market_hours.get_market_session = MagicMock(return_value=_open_session())
    coord._refresh_account_info = AsyncMock()
    return coord


async def _capture_executed_order(coord: ExecutionCoordinator) -> list:
    captured = []

    async def _record(order):
        captured.append(order)
        return OrderResult(
            order_id="o1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=order.price or 50_000,
            status="filled",
        )

    coord._execute_order = _record
    return captured


def _stub_allocation(side: OrderSide) -> AllocationPlan:
    return AllocationPlan(
        ticker="005930",
        stock_name="삼성전자",
        side=side,
        quantity=1,
        entry_price=50_000,
        estimated_amount=50_000,
        position_pct=1.0,
        rationale="stub allocation",
        rebalance_orders=[],
    )


# =============================================================================
# 1) on_trade_approved가 실제로 _resolve_adtv를 호출하고 그 결과를
#    calculate_allocation에 흘려보내는가 — BUY 전용 게이팅 포함.
# =============================================================================


class TestOnTradeApprovedResolvesAdtv:
    async def test_buy_threads_resolved_adtv_into_calculate_allocation(self, monkeypatch):
        coord = _live_coordinator()
        await _capture_executed_order(coord)

        resolve_calls = []

        async def fake_resolve_adtv(ticker):
            resolve_calls.append(ticker)
            return 2_000_000_000.0  # 20억

        monkeypatch.setattr(coord.portfolio_agent, "_resolve_adtv", fake_resolve_adtv)

        received_kwargs = {}

        def _capture_calculate_allocation(*args, **kwargs):
            received_kwargs.update(kwargs)
            return _stub_allocation(OrderSide.BUY)

        monkeypatch.setattr(
            coord.portfolio_agent,
            "calculate_allocation",
            MagicMock(side_effect=_capture_calculate_allocation),
        )

        await coord.on_trade_approved(
            session_id="s1",
            ticker="005930",
            stock_name="삼성전자",
            action="BUY",
            entry_price=50_000,
            stop_loss=None,
            take_profit=None,
            risk_score=5,
            quantity_override=1,
        )

        assert resolve_calls == ["005930"]
        assert received_kwargs.get("adtv") == 2_000_000_000.0

    async def test_sell_never_calls_resolve_adtv(self, monkeypatch):
        """BUY 전용 게이팅 회귀 방지: SELL은 `_calculate_max_position_value`
        를 전혀 타지 않으므로(포지션 청산 경로) ADTV 재조회는 청산을 지연
        시킬 뿐인 불필요한 라이브 네트워크 호출이다."""
        coord = _live_coordinator()
        await _capture_executed_order(coord)

        resolve_calls = []

        async def fake_resolve_adtv(ticker):
            resolve_calls.append(ticker)
            return 2_000_000_000.0

        monkeypatch.setattr(coord.portfolio_agent, "_resolve_adtv", fake_resolve_adtv)
        monkeypatch.setattr(
            coord.portfolio_agent,
            "calculate_allocation",
            MagicMock(return_value=_stub_allocation(OrderSide.SELL)),
        )

        await coord.on_trade_approved(
            session_id="s1",
            ticker="005930",
            stock_name="삼성전자",
            action="SELL",
            entry_price=50_000,
            stop_loss=None,
            take_profit=None,
            risk_score=5,
            quantity_override=1,
        )

        assert resolve_calls == []


# =============================================================================
# 2) _resolve_adtv 저장값 폴백 (Important2a) — T3가 scan_results.factor_json
#    에 저장한 adtv20_med. 최초 구현 당시 discovery_candidates/WatchedStock
#    에는 그 조회 경로가 없다고 (잘못) 판단해 폴백을 두지 않았었다.
# =============================================================================


class TestResolveAdtvStoredFallback:
    async def test_falls_back_to_stored_scan_result_when_live_fetch_fails(self, monkeypatch):
        import app.core.kiwoom_singleton as kiwoom_singleton
        import services.background_scanner.scanner as scanner_module

        async def failing_client():
            raise RuntimeError("kiwoom auth down")

        monkeypatch.setattr(kiwoom_singleton, "get_shared_kiwoom_client_async", failing_client)

        class _FakeScanner:
            async def get_latest_adtv(self, stk_cd):
                assert stk_cd == "093190"
                return 1_200_000_000.0  # 실측 빅솔론 자릿수(ADTV 1.2억은 아니고 12억 예시)

        async def fake_get_background_scanner():
            return _FakeScanner()

        monkeypatch.setattr(
            scanner_module, "get_background_scanner", fake_get_background_scanner
        )

        agent = PortfolioAgent()
        adtv = await agent._resolve_adtv("093190")

        assert adtv == 1_200_000_000.0

    async def test_returns_none_when_live_and_stored_both_fail(self, monkeypatch):
        """폴백까지 실패하면 여전히 None(캡 미적용, fail-open) — 회귀 방지."""
        import app.core.kiwoom_singleton as kiwoom_singleton
        import services.background_scanner.scanner as scanner_module

        async def failing_client():
            raise RuntimeError("kiwoom auth down")

        monkeypatch.setattr(kiwoom_singleton, "get_shared_kiwoom_client_async", failing_client)

        class _EmptyScanner:
            async def get_latest_adtv(self, stk_cd):
                return None

        async def fake_get_background_scanner():
            return _EmptyScanner()

        monkeypatch.setattr(
            scanner_module, "get_background_scanner", fake_get_background_scanner
        )

        agent = PortfolioAgent()
        adtv = await agent._resolve_adtv("999999")

        assert adtv is None

    async def test_stored_fallback_not_used_when_live_fetch_succeeds(self, monkeypatch):
        """라이브 재계산이 성공하면 저장값 폴백을 조회조차 하지 않는다 —
        승격(EOD) 당시 값보다 최신 값을 우선한다는 문서화된 의도의 회귀 핀."""
        import app.core.kiwoom_singleton as kiwoom_singleton
        import pandas as pd

        class _FakeClient:
            async def get_daily_chart_df(self, ticker):
                return pd.DataFrame({"value": [3_000_000_000.0] * 20})

        async def fake_client():
            return _FakeClient()

        monkeypatch.setattr(kiwoom_singleton, "get_shared_kiwoom_client_async", fake_client)

        stored_calls = []

        agent = PortfolioAgent()

        async def spy_stored_adtv(ticker):
            stored_calls.append(ticker)
            return 999_000_000.0

        monkeypatch.setattr(agent, "_stored_adtv", spy_stored_adtv)

        adtv = await agent._resolve_adtv("005930")

        assert adtv == 3_000_000_000.0
        assert stored_calls == [], "라이브 재계산이 성공했으면 저장값 폴백을 호출하지 않아야 한다"


# =============================================================================
# 3) adtv_unknown(캡 완전 비활성)이 조용히 사라지지 않는가 (Important2b).
# =============================================================================


class TestAdtvUnknownIsLogged:
    def test_liquidity_cap_adtv_unknown_is_logged(self, caplog):
        agent = PortfolioAgent()

        with caplog.at_level(logging.WARNING, logger="services.trading.portfolio_agent"):
            value = agent._calculate_max_position_value(
                total_equity=500_000_000, risk_score=1, adtv=None
            )

        assert value == 75_000_000  # 캡 미적용(fail-open) — 값 자체는 그대로
        assert any(
            "adtv_unknown" in record.getMessage() for record in caplog.records
        ), "adtv_unknown일 때도 최소 한 줄은 로그로 남아야 한다(리뷰 Important2b)"


# =============================================================================
# 4) 최종 리뷰 Blocking2 — C1 사이징 캡 킬스위치(LIQUIDITY_SIZING_CAP_ENABLED)
#    off면 두 사이징 호출부가 adtv=None을 넘겨 기존 fail-open 경로로 수렴한다.
# =============================================================================


class TestSizingCapKillswitch:
    async def test_resolve_adtv_returns_none_and_skips_fetch_when_disabled(self, monkeypatch):
        import app.core.kiwoom_singleton as kiwoom_singleton
        import pandas as pd
        from app.config import settings

        monkeypatch.setattr(settings, "LIQUIDITY_SIZING_CAP_ENABLED", False)

        fetch_calls = []

        class _FakeClient:
            async def get_daily_chart_df(self, ticker):
                fetch_calls.append(ticker)
                return pd.DataFrame({"value": [3_000_000_000.0] * 20})

        monkeypatch.setattr(
            kiwoom_singleton, "get_shared_kiwoom_client_async", AsyncMock(return_value=_FakeClient())
        )

        agent = PortfolioAgent()
        adtv = await agent._resolve_adtv("005930")

        assert adtv is None, "킬스위치 off인데 ADTV가 흘러갔다 — 부분 롤백 수단 무효"
        assert fetch_calls == [], "캡이 꺼졌으면 일봉 재조회 자체가 불필요하다"

    async def test_resolve_adtv_defaults_enabled(self, monkeypatch):
        """기본값은 on — 스위치를 건드리지 않으면 기존 동작 그대로."""
        import app.core.kiwoom_singleton as kiwoom_singleton
        import pandas as pd
        from app.config import settings

        assert settings.LIQUIDITY_SIZING_CAP_ENABLED is True

        class _FakeClient:
            async def get_daily_chart_df(self, ticker):
                return pd.DataFrame({"value": [3_000_000_000.0] * 20})

        monkeypatch.setattr(
            kiwoom_singleton, "get_shared_kiwoom_client_async", AsyncMock(return_value=_FakeClient())
        )

        agent = PortfolioAgent()
        assert await agent._resolve_adtv("005930") == 3_000_000_000.0


# =============================================================================
# 5) 최종 리뷰 Blocking3 — skip-floor가 무로그로 비활성화되던 경로.
#
# `_get_account_equity`가 예외를 완전히 삼키고(로그 0줄) 호출부가 None을
# 0.0으로 조용히 대체해, `apply_liquidity_cap`의 skip-floor 분기가 `equity > 0`
# 선행 조건 때문에 평가조차 되지 않은 채 통과했다. 게다가 확률적 위험이 아니라
# 확정 경로다 — coordinator._state.account.total_equity는 _refresh_account_info
# 전 기본값이 0이라 배포 후 /trading/start 재발행 전 구간에서는 예외 없이
# float(0)이 그대로 흐른다.
# =============================================================================


class TestSkipFloorObservability:
    async def test_get_account_equity_logs_when_lookup_fails(self, monkeypatch, caplog):
        import agents.graph.kr_stock_nodes.decision_nodes as kr
        import app.dependencies as deps

        monkeypatch.setattr(
            deps, "get_trading_coordinator", AsyncMock(side_effect=RuntimeError("coordinator down"))
        )

        with caplog.at_level(
            logging.WARNING, logger="agents.graph.kr_stock_nodes.decision_nodes"
        ):
            equity = await kr._get_account_equity()

        assert equity is None
        assert any(
            "liquidity_skip_equity_unavailable" in record.getMessage()
            for record in caplog.records
        ), "예외를 삼키더라도 로그 한 줄은 남아야 한다(ADTV 실패와 동일 원칙)"

    async def test_decision_node_logs_skip_floor_disabled_on_zero_equity(
        self, monkeypatch, caplog
    ):
        """종단: equity=0(기본값 경로)으로 BUY 사이징이 끝나면 skip-floor가
        비활성인 채 통과했다는 사실이 로그로 남아야 한다."""
        import agents.graph.kr_stock_nodes.decision_nodes as kr
        import app.dependencies as deps
        import pandas as pd
        from services.trading.coordinator import ExecutionCoordinator

        # total_equity 기본값 0 — _refresh_account_info 전 라이브 상태 재현.
        coordinator = ExecutionCoordinator(kiwoom_client=None)
        assert coordinator._state.account.total_equity == 0
        monkeypatch.setattr(
            deps, "get_trading_coordinator", AsyncMock(return_value=coordinator)
        )

        class _FakeClient:
            async def get_cash_balance(self):
                return MagicMock(ord_psbl_amt=100_000_000)

            async def get_daily_chart_df(self, ticker):
                return pd.DataFrame({"value": [3_000_000_000.0] * 20})

        monkeypatch.setattr(
            kr, "get_shared_kiwoom_client_async", AsyncMock(return_value=_FakeClient())
        )

        async def fake_decide_action(llm, messages, *, rule_action, **kwargs):
            return rule_action, "", "rule_fallback", None, None

        monkeypatch.setattr(kr, "get_llm_provider", lambda: MagicMock())
        monkeypatch.setattr(kr, "decide_action", fake_decide_action)

        async def fake_notifier():
            return MagicMock(is_ready=False)

        monkeypatch.setattr("services.telegram.get_telegram_notifier", fake_notifier)

        buy_analyses = {
            f"{kind}_analysis": {
                "agent_type": kind, "signal": "buy", "confidence": 0.8,
                "summary": "매수", "key_factors": [],
            }
            for kind in ("technical", "fundamental", "sentiment")
        }
        state = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "market_data": {"cur_prc": 70_000},
            **buy_analyses,
        }

        with caplog.at_level(
            logging.WARNING, logger="agents.graph.kr_stock_nodes.decision_nodes"
        ):
            result = await kr.kr_stock_strategic_decision_node(state)

        assert result["trade_proposal"]["action"] == "BUY"
        messages = [r.getMessage() for r in caplog.records]
        assert any("liquidity_skip_floor_disabled" in m for m in messages), (
            "equity<=0이면 skip-floor가 평가조차 되지 않는다 — 무로그로 지나가면 안 된다"
        )
        assert any("liquidity_cap_without_skip_floor" in m for m in messages), (
            "사유가 실제로 apply_liquidity_cap에서 구분돼 돌아와야 한다"
        )
