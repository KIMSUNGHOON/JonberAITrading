"""P4 Task 2 (part 2): position-aware decision — verify/ensure a held ticker's
re-analysis produces a management action (ADD/REDUCE/HOLD/SELL), not a blind
fresh-entry BUY.

Findings (see docs/superpowers/plans/2026-07-15-p4-reanalysis-dedup.md Task 2
and the P4-T2 report):

- **KR is ALREADY position-aware.** `kr_stock_nodes/data_collection.py`
  queries the broker balance (kt00004 `get_account_balance()`) and injects
  `existing_position` into graph state; `kr_stock_strategic_decision_node`
  reads it and routes through `_signal_to_action_with_position` (feasible
  sets `FEASIBLE_WITH_POSITION`/`FEASIBLE_WITHOUT_POSITION` in
  `decision_policy.py`), so a held ticker with a BUY-leaning consensus comes
  out as ADD/HOLD, never BUY. The tests below PIN this existing behavior as
  a regression guard — they don't change KR code.

- **Coin was NOT position-aware** (no `existing_position` concept existed at
  all in `coin_state.py`/`coin_nodes.py` before this task) — every re-analysis
  of a held market behaved identically to a fresh entry. This task wired
  `existing_position` into coin state (`coin_data_collection_node`, sourced
  from `storage.get_coin_position`, the same source `/positions` reads) and
  threaded it into `coin_strategic_decision_node`'s LLM context + SELL
  quantity sizing. Coin's TradeAction stays intentionally 3-valued
  (BUY/SELL/HOLD — `decision_policy.POSITION_AGNOSTIC_ACTIONS`); expanding it
  to ADD/REDUCE is a larger, separate change (would ripple into the coin
  execution node + schemas) and is out of scope here. The tests below cover
  the new wiring: existing_position injection + SELL sizing off the real
  held quantity.
"""

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

pytestmark = pytest.mark.asyncio


def _quiet_kr_telegram(monkeypatch):
    """Neutralize the lazy `services.telegram.get_telegram_notifier` the KR
    node's proposal-notification branches call, so tests don't touch the
    real notifier (same helper as test_kr_stock_graph.py)."""

    async def fake_notifier():
        return MagicMock(is_ready=False)

    monkeypatch.setattr("services.telegram.get_telegram_notifier", fake_notifier)


# =============================================================================
# KR: regression pin — already position-aware
# =============================================================================


class TestKRPositionAwareDecisionRegression:
    """`_signal_to_action_with_position` + the strategic-decision node's use
    of `existing_position` from state — pinned so a future change can't
    silently regress a held ticker back to being treated as a fresh entry."""

    @staticmethod
    def _buy_leaning_analyses():
        """Three voting analyses (technical/fundamental/sentiment) tuned to
        a clear BUY consensus (avg_signal ~1.0, well past the 0.4 BUY /
        below 1.3 STRONG_BUY thresholds in calculate_kr_stock_consensus_signal)."""
        return {
            "technical_analysis": {
                "agent_type": "technical",
                "signal": "buy",
                "confidence": 0.8,
                "summary": "상승 추세",
                "key_factors": [],
            },
            "fundamental_analysis": {
                "agent_type": "fundamental",
                "signal": "buy",
                "confidence": 0.8,
                "summary": "저평가",
                "key_factors": [],
            },
            "sentiment_analysis": {
                "agent_type": "sentiment",
                "signal": "buy",
                "confidence": 0.8,
                "summary": "긍정적 뉴스",
                "key_factors": [],
            },
        }

    async def test_held_ticker_buy_signal_yields_add_not_buy(self, monkeypatch):
        """The important pin: same BUY-leaning consensus, but stk_cd is
        ALREADY held -> the proposal action must be ADD (management re-eval),
        never a fresh BUY."""
        import agents.graph.kr_stock_nodes.decision_nodes as kr

        async def fake_decide_action(llm, messages, *, rule_action, **kwargs):
            # Echo the rule action decision_nodes computed via
            # _signal_to_action_with_position — pins the WIRING (state ->
            # has_position -> rule_action), independent of any real LLM call.
            return rule_action, "", "rule_fallback", None, None

        monkeypatch.setattr(kr, "get_llm_provider", lambda: MagicMock())
        monkeypatch.setattr(kr, "decide_action", fake_decide_action)
        _quiet_kr_telegram(monkeypatch)

        state = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "market_data": {"cur_prc": 70000},
            "existing_position": {
                "quantity": 100,
                "avg_buy_price": 68000,
                "current_price": 70000,
                "profit_loss": 200000,
                "profit_loss_pct": -2.94,  # at a loss -> ADD branch
            },
            **self._buy_leaning_analyses(),
        }

        result = await kr.kr_stock_strategic_decision_node(state)

        assert result["trade_proposal"]["action"] == "ADD"
        assert result["trade_proposal"]["action"] != "BUY"
        # ADD sizing goes through the BUY/ADD quantity branch (current_price
        # > 0), not the existing_position-quantity branch used by SELL/REDUCE.

    async def test_unheld_ticker_same_buy_signal_yields_fresh_buy(self, monkeypatch):
        """Divergence check: the EXACT same consensus signal, but no
        existing_position -> a genuine fresh-entry BUY."""
        import agents.graph.kr_stock_nodes.decision_nodes as kr

        async def fake_decide_action(llm, messages, *, rule_action, **kwargs):
            return rule_action, "", "rule_fallback", None, None

        monkeypatch.setattr(kr, "get_llm_provider", lambda: MagicMock())
        monkeypatch.setattr(kr, "decide_action", fake_decide_action)
        monkeypatch.setattr(
            kr, "get_shared_kiwoom_client_async", AsyncMock(side_effect=RuntimeError("no cash lookup in test"))
        )
        _quiet_kr_telegram(monkeypatch)

        state = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "market_data": {"cur_prc": 70000},
            # no existing_position key at all -> has_position False
            **self._buy_leaning_analyses(),
        }

        result = await kr.kr_stock_strategic_decision_node(state)

        assert result["trade_proposal"]["action"] == "BUY"

    async def test_held_ticker_strong_sell_signal_yields_sell_with_real_quantity(
        self, monkeypatch
    ):
        """A held ticker with a STRONG_SELL consensus -> full SELL, sized off
        the REAL held quantity (not independently computed/blind)."""
        import agents.graph.kr_stock_nodes.decision_nodes as kr

        async def fake_decide_action(llm, messages, *, rule_action, **kwargs):
            return rule_action, "", "rule_fallback", None, None

        monkeypatch.setattr(kr, "get_llm_provider", lambda: MagicMock())
        monkeypatch.setattr(kr, "decide_action", fake_decide_action)
        _quiet_kr_telegram(monkeypatch)

        strong_sell_analyses = {
            "technical_analysis": {
                "agent_type": "technical", "signal": "strong_sell", "confidence": 0.9,
                "summary": "급락", "key_factors": [],
            },
            "fundamental_analysis": {
                "agent_type": "fundamental", "signal": "strong_sell", "confidence": 0.9,
                "summary": "실적 악화", "key_factors": [],
            },
            "sentiment_analysis": {
                "agent_type": "sentiment", "signal": "strong_sell", "confidence": 0.9,
                "summary": "부정적 뉴스", "key_factors": [],
            },
        }
        state = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "market_data": {"cur_prc": 70000},
            "existing_position": {
                "quantity": 100,
                "avg_buy_price": 68000,
                "current_price": 70000,
                "profit_loss": 200000,
                "profit_loss_pct": 2.94,
            },
            **strong_sell_analyses,
        }

        result = await kr.kr_stock_strategic_decision_node(state)

        assert result["trade_proposal"]["action"] == "SELL"
        assert result["trade_proposal"]["quantity"] == 100  # the real held qty

    async def test_signal_to_action_with_position_helper_pin(self):
        """Direct unit pin on the helper decision_nodes delegates to."""
        from agents.graph.kr_stock_nodes.helpers import _signal_to_action_with_position
        from agents.graph.kr_stock_state import SignalType, TradeAction

        # Held + BUY-leaning + at a loss -> ADD (average down), never BUY.
        assert (
            _signal_to_action_with_position(SignalType.BUY, has_position=True, position_pnl_pct=-5.0)
            == TradeAction.ADD
        )
        # Unheld + BUY-leaning -> fresh BUY.
        assert (
            _signal_to_action_with_position(SignalType.BUY, has_position=False, position_pnl_pct=0.0)
            == TradeAction.BUY
        )
        # Held + HOLD signal -> HOLD (maintain), not a trade.
        assert (
            _signal_to_action_with_position(SignalType.HOLD, has_position=True, position_pnl_pct=1.0)
            == TradeAction.HOLD
        )


# =============================================================================
# S-4 (생존 규율, decision D4): R-based sizing — quantity calc r_cap_value()
# min()-combines the notional cap with an R-budget cap using the SAME
# stop_loss the proposal carries (stop_loss precompute moved before the
# quantity calc — the "reorder is harmless" pin lives here too).
# Spec: docs/superpowers/specs/2026-07-19-survival-discipline-design.md §2 S-4.
# =============================================================================


class TestRCapSizingDecisionNodes:
    @staticmethod
    def _buy_leaning_analyses():
        return {
            "technical_analysis": {
                "agent_type": "technical", "signal": "buy", "confidence": 0.8,
                "summary": "상승 추세", "key_factors": [],
            },
            "fundamental_analysis": {
                "agent_type": "fundamental", "signal": "buy", "confidence": 0.8,
                "summary": "저평가", "key_factors": [],
            },
            "sentiment_analysis": {
                "agent_type": "sentiment", "signal": "buy", "confidence": 0.8,
                "summary": "긍정적 뉴스", "key_factors": [],
            },
        }

    @staticmethod
    def _fake_kiwoom_client(orderable_amount: int, adtv: float | None = None):
        client = MagicMock()
        client.get_cash_balance = AsyncMock(
            return_value=MagicMock(ord_psbl_amt=orderable_amount)
        )
        if adtv is not None:
            # 20행 constant -> adtv_median(중앙값) == adtv 그대로.
            df = pd.DataFrame({"value": [adtv] * 20})
            client.get_daily_chart_df = AsyncMock(return_value=df)
        return client

    def _wire_common_mocks(
        self, monkeypatch, kr, *,
        orderable_amount: int,
        risk_budget_pct: float = 0.75,
        adtv: float | None = None,
        account_equity: float | None = None,
    ):
        async def fake_decide_action(llm, messages, *, rule_action, **kwargs):
            return rule_action, "", "rule_fallback", None, None

        monkeypatch.setattr(kr, "get_llm_provider", lambda: MagicMock())
        monkeypatch.setattr(kr, "decide_action", fake_decide_action)
        # 결정론성 확보 — 전역 coordinator 싱글턴 오염(다른 테스트가 먼저
        # 초기화했을 수 있음)과 무관하게 전략=None/risk_budget_pct 고정값을
        # 강제한다 (best-effort lazy fetch를 우회).
        monkeypatch.setattr(kr, "_get_active_strategy", AsyncMock(return_value=None))
        monkeypatch.setattr(kr, "_get_risk_budget_pct", AsyncMock(return_value=risk_budget_pct))
        monkeypatch.setattr(
            kr, "get_shared_kiwoom_client_async",
            AsyncMock(return_value=self._fake_kiwoom_client(orderable_amount, adtv=adtv)),
        )
        # C1 Important3(리뷰): skip-floor는 계좌 총평가액 기준 — 지정되지
        # 않으면 조회 실패(None)를 흉내내 기존 테스트의 결정론성을 유지한다
        # (실제 _get_account_equity도 coordinator 미가동 시 None -> equity=0.0
        # -> skip-floor 미적용, 캡 바인딩 자체는 영향 없음).
        monkeypatch.setattr(kr, "_get_account_equity", AsyncMock(return_value=account_equity))
        _quiet_kr_telegram(monkeypatch)

    async def test_r_cap_tightens_quantity_when_binding(self, monkeypatch):
        """R 캡이 기존 notional 캡보다 작을 때 채택 — 수량이 줄어든다.

        orderable=10,000,000, position_size_pct=50 -> investment_amount=
        5,000,000(사전 R캡). stop 10% 거리 -> r_cap=10,000,000*0.0075/0.10=
        750,000 < 5,000,000 -> 채택. quantity=750,000//100,000=7.
        """
        import agents.graph.kr_stock_nodes.decision_nodes as kr

        self._wire_common_mocks(monkeypatch, kr, orderable_amount=10_000_000)

        state = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "market_data": {"cur_prc": 100_000},
            "risk_assessment": {
                "signals": {
                    "max_position_pct": 50.0,
                    "suggested_stop_loss": 90_000,  # 10% distance
                    "suggested_take_profit": 120_000,
                    "risk_score": 0.5,
                }
            },
            **self._buy_leaning_analyses(),
        }

        result = await kr.kr_stock_strategic_decision_node(state)
        proposal = result["trade_proposal"]

        assert proposal["action"] == "BUY"
        assert proposal["quantity"] == 7
        # stop_loss/take_profit는 risk_signals 값 그대로 — 재배치 무해.
        assert proposal["stop_loss"] == 90_000
        assert proposal["take_profit"] == 120_000

    async def test_r_cap_does_not_bind_when_looser_than_notional_cap(self, monkeypatch):
        """R 캡이 기존 notional 캡보다 클 때 — 기존 수량 그대로(회귀 핀).

        orderable=10,000,000, position_size_pct=5(기본) -> investment_amount=
        500,000. stop 2% 거리 -> r_cap=3,750,000 (느슨) -> 미채택.
        """
        import agents.graph.kr_stock_nodes.decision_nodes as kr

        self._wire_common_mocks(monkeypatch, kr, orderable_amount=10_000_000)

        state = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "market_data": {"cur_prc": 100_000},
            "risk_assessment": {
                "signals": {
                    "max_position_pct": 5.0,
                    "suggested_stop_loss": 98_000,  # 2% distance
                    "suggested_take_profit": 110_000,
                    "risk_score": 0.5,
                }
            },
            **self._buy_leaning_analyses(),
        }

        result = await kr.kr_stock_strategic_decision_node(state)
        proposal = result["trade_proposal"]

        assert proposal["action"] == "BUY"
        assert proposal["quantity"] == 5  # 500,000 // 100,000, R 캡 미적용
        assert proposal["stop_loss"] == 98_000
        assert proposal["take_profit"] == 110_000

    async def test_stop_precompute_reorder_is_byte_identical_pin(self, monkeypatch):
        """재배치 무해 핀: risk_signals에 suggested_stop_loss가 없어 폴백 산식
        경로를 타도(strategy=None) proposal.stop_loss/take_profit이 재배치
        이전과 동일한 폴백 값(entry*0.95 / entry*1.10)을 낸다 — 산식은 불변,
        순서만 수량 계산 앞으로 옮겨졌을 뿐."""
        import agents.graph.kr_stock_nodes.decision_nodes as kr

        self._wire_common_mocks(monkeypatch, kr, orderable_amount=10_000_000)

        state = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "market_data": {"cur_prc": 70_000},
            # risk_assessment 키 자체가 없음 -> risk_signals={} -> 폴백 산식
            **self._buy_leaning_analyses(),
        }

        result = await kr.kr_stock_strategic_decision_node(state)
        proposal = result["trade_proposal"]

        assert proposal["stop_loss"] == int(70_000 * 0.95)      # 66500, byte-identical
        assert proposal["take_profit"] == int(70_000 * 1.10)    # 77000, byte-identical
        # position_size_pct 기본값 5.0 -> investment_amount=500,000.
        # distance=(70000-66500)/70000=5% -> r_cap=1,500,000 (느슨) -> 미채택.
        assert proposal["quantity"] == 500_000 // 70_000  # 7

    # =========================================================================
    # C1 (유동성 인지, 2026-07-27) — 리뷰 수정.
    #
    # Important1: 기존 3개 R-cap 테스트는 client가 plain MagicMock이라
    # get_daily_chart_df가 TypeError를 내고 캡이 항상 "adtv_unknown"으로
    # fail-open했다 — 캡을 통째로 지워도 그린이었다. 아래 두 테스트는
    # `adtv=`로 실제 값을 흘려보내 decision_nodes 엔진의 캡이 실제로
    # 바인딩한다는 것을 증명한다.
    #
    # Important3: skip-floor(계좌의 1%)가 orderable_amount(가용현금) 기준
    # 이면 계좌가 상당 부분 투자된 상태에서 사실상 무력화된다 — 아래
    # `test_decision_node_skip_floor_uses_account_equity_not_orderable_amount`
    # 가 그 회귀를 핀한다.
    # =========================================================================

    async def test_decision_node_liquidity_cap_binds_with_real_adtv(self, monkeypatch):
        """ADTV 6억(real 값, mock 우회 없음) -> liquidity cap = 0.5% =
        300만원. orderable=10,000,000, position_size_pct=50 ->
        investment_amount(사전 캡)=5,000,000. stop 0.5% 거리로 r_cap을
        느슨하게 유지(15,000,000 > 5,000,000, 미채택)해 유동성 캡만 단독
        바인딩하게 한다. account_equity=1억 -> skip-floor=100만원 <
        liq_cap(300만원)이라 skip은 발동하지 않는다(캡 바인딩만 검증)."""
        import agents.graph.kr_stock_nodes.decision_nodes as kr

        self._wire_common_mocks(
            monkeypatch, kr, orderable_amount=10_000_000,
            adtv=600_000_000.0, account_equity=100_000_000.0,
        )

        state = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "market_data": {"cur_prc": 100_000},
            "risk_assessment": {
                "signals": {
                    "max_position_pct": 50.0,
                    "suggested_stop_loss": 99_500,  # 0.5% distance -> r_cap 느슨
                    "suggested_take_profit": 120_000,
                    "risk_score": 0.5,
                }
            },
            **self._buy_leaning_analyses(),
        }

        result = await kr.kr_stock_strategic_decision_node(state)
        proposal = result["trade_proposal"]

        assert proposal["action"] == "BUY"
        # liq_cap = 600,000,000 * 0.005 = 3,000,000 < investment_amount
        # (5,000,000) -> 바인딩. quantity = 3,000,000 // 100,000 = 30.
        assert proposal["quantity"] == 30

    async def test_decision_node_skip_floor_uses_account_equity_not_orderable_amount(
        self, monkeypatch
    ):
        """리뷰 Important3 회귀 핀: skip-floor는 정의상(r_sizing.
        SKIP_MIN_EQUITY_PCT) "계좌의 1%"다 — R-cap의 자본 베이스인
        orderable_amount(가용현금)와는 분리해야 한다.

        orderable_amount=5,000,000(계좌가 상당 부분 투자돼 현금이 적은
        상태), account_equity=500,000,000(계좌 총평가액은 그대로 큼).
        adtv=5억 -> liq_cap=2,500,000.

        - 버그 상태(고친 전, orderable_amount를 skip 비교에 썼을 때):
          floor = 5,000,000 * 1% = 50,000. liq_cap(2,500,000) >= floor ->
          skip 미발동 -> 캡이 2,500,000으로 "바인딩"만 하고 25주가 체결됐을
          것 — 실측 빅솔론 케이스(ADTV 1.2억에 얇은 종목 참여율 16%)와
          같은 패턴.
        - 수정 후(계좌 총평가액 기준): floor = 500,000,000 * 1% =
          5,000,000. liq_cap(2,500,000) < floor -> skip 발동 ->
          investment_amount=0 -> quantity=0. 진입 자체를 포기한다.
        """
        import agents.graph.kr_stock_nodes.decision_nodes as kr

        self._wire_common_mocks(
            monkeypatch, kr, orderable_amount=5_000_000,
            adtv=500_000_000.0, account_equity=500_000_000.0,
        )

        state = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "market_data": {"cur_prc": 100_000},
            "risk_assessment": {
                "signals": {
                    "max_position_pct": 100.0,
                    "suggested_stop_loss": 99_500,  # 0.5% distance -> r_cap 느슨(7,500,000)
                    "suggested_take_profit": 120_000,
                    "risk_score": 0.5,
                }
            },
            **self._buy_leaning_analyses(),
        }

        result = await kr.kr_stock_strategic_decision_node(state)
        proposal = result["trade_proposal"]

        assert proposal["quantity"] == 0, (
            "skip-floor가 orderable_amount(가용현금) 기준으로 새면 캡이 "
            "2,500,000으로만 바인딩해 25주가 나간다 — 계좌 총평가액 기준"
            "이어야 skip이 발동해 진입을 포기한다"
        )


# =============================================================================
# Coin: new wiring — existing_position injection + SELL sizing
# =============================================================================


class TestCoinPositionAwareDataCollection:
    """`coin_data_collection_node` now queries `storage.get_coin_position`
    (P4 Task 2 wiring) and injects `existing_position` into state — this was
    entirely absent before."""

    @staticmethod
    def _fake_upbit_client_factory():
        class _FakeAnalysisData:
            current_price = 100_000_000
            change_rate_24h = 1.5
            volume_24h = 123.0
            high_24h = 101_000_000
            low_24h = 99_000_000
            bid_ask_ratio = 1.1
            candles = []

        class _FakeUpbitClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get_analysis_data(self, market, candle_count, trade_count):
                return _FakeAnalysisData()

            async def get_orderbook(self, markets):
                return []

            async def get_trades(self, market, count):
                return []

        return lambda *a, **kw: _FakeUpbitClient()

    @pytest.fixture
    async def temp_storage(self, tmp_path, monkeypatch):
        import services.storage_service as ss

        storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
        await storage.initialize()
        monkeypatch.setattr(ss, "_storage_service", storage)
        yield storage
        monkeypatch.setattr(ss, "_storage_service", None)

    @pytest.fixture(autouse=True)
    def _fake_upbit(self, monkeypatch):
        import agents.graph.coin_nodes as coin_nodes_module

        monkeypatch.setattr(
            coin_nodes_module, "UpbitClient", self._fake_upbit_client_factory()
        )

    async def test_held_market_gets_existing_position_injected(self, temp_storage):
        import agents.graph.coin_nodes as coin

        await temp_storage.save_coin_position(
            {
                "market": "KRW-BTC",
                "currency": "BTC",
                "quantity": 0.25,
                "avg_entry_price": 95_000_000,
            }
        )

        result = await coin.coin_data_collection_node({"market": "KRW-BTC"})

        assert result["existing_position"] is not None
        assert result["existing_position"]["quantity"] == 0.25
        assert result["existing_position"]["avg_entry_price"] == 95_000_000

    async def test_unheld_market_gets_no_existing_position(self, temp_storage):
        import agents.graph.coin_nodes as coin

        result = await coin.coin_data_collection_node({"market": "KRW-ETH"})

        assert result["existing_position"] is None

    async def test_storage_failure_degrades_to_no_position(self, monkeypatch):
        """Best-effort: a storage lookup failure must not crash data
        collection — existing_position degrades to None."""
        import agents.graph.coin_nodes as coin
        import services.storage_service as ss

        async def _boom():
            raise RuntimeError("storage unavailable")

        monkeypatch.setattr(ss, "get_storage_service", _boom)

        result = await coin.coin_data_collection_node({"market": "KRW-BTC"})

        assert result["existing_position"] is None
        assert result.get("error") is None  # data collection itself still succeeds


class TestCoinPositionAwareStrategicDecision:
    """`coin_strategic_decision_node` now reads `existing_position` from
    state (P4 Task 2) — feeding LLM context and, for SELL, sizing quantity
    off the REAL held quantity instead of always defaulting to 0.0."""

    async def test_sell_uses_real_held_quantity_when_position_exists(self, monkeypatch):
        import agents.graph.coin_nodes as coin

        async def fake_decide_action(llm, messages, **kwargs):
            return coin.TradeAction.SELL, "sell signal", "llm", None, None

        monkeypatch.setattr(coin, "get_llm_provider", lambda: MagicMock())
        monkeypatch.setattr(coin, "decide_action", fake_decide_action)

        state = {
            "market": "KRW-BTC",
            "market_data": {"current_price": 100_000_000},
            "existing_position": {
                "market": "KRW-BTC",
                "quantity": 0.42,
                "avg_entry_price": 90_000_000,
            },
        }

        result = await coin.coin_strategic_decision_node(state)

        assert result["trade_proposal"]["action"] == "SELL"
        assert result["trade_proposal"]["quantity"] == 0.42

    async def test_sell_without_position_stays_zero_quantity_unchanged(self, monkeypatch):
        """Regression: the pre-existing (unheld) SELL path is untouched —
        quantity stays 0.0 exactly as before this task's wiring."""
        import agents.graph.coin_nodes as coin

        async def fake_decide_action(llm, messages, **kwargs):
            return coin.TradeAction.SELL, "sell signal", "llm", None, None

        monkeypatch.setattr(coin, "get_llm_provider", lambda: MagicMock())
        monkeypatch.setattr(coin, "decide_action", fake_decide_action)

        state = {
            "market": "KRW-BTC",
            "market_data": {"current_price": 100_000_000},
            # no existing_position key -> has_position False
        }

        result = await coin.coin_strategic_decision_node(state)

        assert result["trade_proposal"]["action"] == "SELL"
        assert result["trade_proposal"]["quantity"] == 0.0

    async def test_hold_action_unaffected_by_position_presence(self, monkeypatch):
        """Coin's action space stays 3-valued (BUY/SELL/HOLD) by design —
        a HOLD consensus produces HOLD regardless of has_position, since
        coin has no ADD/REDUCE actions to route to."""
        import agents.graph.coin_nodes as coin

        async def fake_decide_action(llm, messages, **kwargs):
            return coin.TradeAction.HOLD, "hold signal", "llm", None, None

        monkeypatch.setattr(coin, "get_llm_provider", lambda: MagicMock())
        monkeypatch.setattr(coin, "decide_action", fake_decide_action)

        state = {
            "market": "KRW-BTC",
            "market_data": {"current_price": 100_000_000},
            "existing_position": {
                "market": "KRW-BTC",
                "quantity": 0.1,
                "avg_entry_price": 90_000_000,
            },
        }

        result = await coin.coin_strategic_decision_node(state)

        assert result["trade_proposal"]["action"] == "HOLD"
        assert result["trade_proposal"]["quantity"] == 0.0
