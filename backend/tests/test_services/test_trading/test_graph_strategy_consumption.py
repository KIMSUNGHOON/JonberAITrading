"""Phase4 T5: graph-path + opportunity-detection strategy consumption.

Default-equivalence is the core invariant: no strategy (or a default
strategy) must reproduce the legacy hardcoded behavior exactly.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.trading.strategy import EntryConditions, TradingStrategy

pytestmark = pytest.mark.asyncio


def test_entry_conditions_new_fields_defaults_match_legacy():
    ec = EntryConditions()
    assert ec.entry_proximity_pct == pytest.approx(0.03)
    assert ec.opportunity_min_confidence == pytest.approx(0.75)


def test_new_fields_not_llm_adjustable():
    """KNOB_BOUNDS(Phase3 EOD 합의가 움직일 수 있는 노브)에 미포함 확인."""
    from services.trading.strategy_consensus import KNOB_BOUNDS

    assert "entry_proximity_pct" not in KNOB_BOUNDS
    assert "opportunity_min_confidence" not in KNOB_BOUNDS


async def test_graph_risk_node_uses_strategy_exits():
    from agents.graph.kr_stock_nodes import decision_nodes

    strategy = TradingStrategy()
    strategy.exit_conditions.stop_loss_pct = 0.06
    strategy.exit_conditions.take_profit_pct = 0.20
    strategy.position_sizing.max_position_pct = 0.08
    trading = MagicMock()
    trading.get_strategy.return_value = strategy

    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(return_value=trading)):
        got = await decision_nodes._get_active_strategy()
    assert got is strategy

    # 저리스크: 전략값 그대로 / 고리스크: 손절 ×1.15, 익절 ×0.8, 포지션 ×0.6
    lo = decision_nodes._strategy_stop_params(strategy, risk_score=0.3)
    assert lo == (pytest.approx(0.06), pytest.approx(0.20), pytest.approx(8.0))
    hi = decision_nodes._strategy_stop_params(strategy, risk_score=0.7)
    assert hi == (pytest.approx(0.069), pytest.approx(0.16), pytest.approx(4.8))


async def test_graph_strategy_fetch_failure_is_none():
    from agents.graph.kr_stock_nodes import decision_nodes

    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(side_effect=RuntimeError("down"))):
        assert await decision_nodes._get_active_strategy() is None


async def test_detect_opportunity_uses_strategy_thresholds():
    from services.agent_chat.coordinator import ChatCoordinator

    strategy = TradingStrategy()
    strategy.entry_conditions.entry_proximity_pct = 0.01   # 타이트
    strategy.entry_conditions.opportunity_min_confidence = 0.9
    trading = MagicMock()
    trading.get_strategy.return_value = strategy
    coordinator = ChatCoordinator()

    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(return_value=trading)):
        # 근접 2% — 기본(3%)이면 기회지만 전략(1%)에선 아님
        near = {"ticker": "005930", "current_price": 102.0,
                "target_entry_price": 100.0, "confidence": 0.5}
        assert await coordinator._detect_opportunity(near) is False
        # 신뢰도 0.8 — 기본(0.75)이면 기회지만 전략(0.9)에선 아님
        confident = {"ticker": "005930", "current_price": 0,
                     "target_entry_price": None, "confidence": 0.8}
        assert await coordinator._detect_opportunity(confident) is False
        # 전략 임계 통과
        hit = {"ticker": "005930", "current_price": 100.5,
               "target_entry_price": 100.0, "confidence": 0.5}
        assert await coordinator._detect_opportunity(hit) is True


async def test_detect_opportunity_without_strategy_keeps_legacy():
    from services.agent_chat.coordinator import ChatCoordinator

    trading = MagicMock()
    trading.get_strategy.return_value = None
    coordinator = ChatCoordinator()
    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(return_value=trading)):
        near = {"ticker": "005930", "current_price": 102.0,
                "target_entry_price": 100.0, "confidence": 0.5}
        assert await coordinator._detect_opportunity(near) is True  # 기본 3%
