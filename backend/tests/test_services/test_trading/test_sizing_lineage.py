"""U3 (사이징 계보, 2026-08-05): 완료된 8회 왕복 거래에서 패자 평균 명목이
승자의 1.27배(등가중 +0.92% vs 자본가중 -0.39%)였는데, risk_score 배수
(1.0/0.7/0.5)와 유동성 참여율 캡 중 어느 쪽이 사이징을 눌렀는지 기록이
없어 원인을 분리할 수 없었다.

`PortfolioAgent._calculate_max_position_value`에 선택적 `lineage` out-param
을 더해 이미 계산되는 중간값(base_max/risk_factor/risk_bucket_cap/r_cap/
liquidity_cap)과 실제로 반환값을 만든 캡의 이름(binding)을 기록한다.

가장 중요한 테스트는 `test_value_identical_with_and_without_lineage`다 —
계보를 붙인 뒤에도 산출값이 완전히 동일해야 한다. 이게 red면 그 자체로
실패다.

기대값은 `RiskParameters()`의 실제 기본값(max_single_position_pct=0.15,
risk_budget_pct=0.75)에서 계산한다 — 하드코딩한 3.0%/0.75% 상수가 아니라
설정에서 읽는다(EOD 전략이 이 파라미터를 야간 개정하므로 하드코딩은 조용히
의미를 잃는다).
"""
import json

import pytest

from services.trading.models import RiskParameters
from services.trading.portfolio_agent import PortfolioAgent

EQUITY = 497_000_000.0


def _agent() -> PortfolioAgent:
    return PortfolioAgent(risk_params=RiskParameters())


# -------------------------------------------
# Step 1: 무변경 테스트 — 가장 중요하다.
# -------------------------------------------


@pytest.mark.parametrize("risk_score", [1, 5, 9])
@pytest.mark.parametrize("adtv", [None, 1_000_000_000.0])
def test_value_identical_with_and_without_lineage(risk_score, adtv):
    """계보 기록이 산출값을 바꾸면 안 된다."""
    a = _agent()
    without = a._calculate_max_position_value(
        EQUITY, risk_score, entry_price=100_000.0, stop_loss=93_000.0, adtv=adtv
    )
    lineage = {}
    with_ = a._calculate_max_position_value(
        EQUITY, risk_score, entry_price=100_000.0, stop_loss=93_000.0,
        adtv=adtv, lineage=lineage,
    )
    assert with_ == without, "계보 기록이 산출값을 바꿨다"
    assert lineage, "lineage를 넘겼는데 비어 있다"


def test_omitting_lineage_arg_is_call_compatible():
    """기존 호출부는 lineage를 넘기지 않는다 — 그대로 동작해야 한다."""
    a = _agent()
    v = a._calculate_max_position_value(EQUITY, 3)
    assert v > 0


# -------------------------------------------
# Step 2: 계보 내용 테스트.
#
# 손절거리의 교차점(crossover) = risk_budget_pct% / (max_single_position_pct
# * risk_factor) — 이보다 손절거리가 짧으면 risk_bucket_cap이 r_cap보다
# 타이트해 이기고, 길면 r_cap이 이긴다. 실제 기본값(0.75%/0.15,
# risk_score=1 -> risk_factor=1.0)에서 crossover = 0.0075/0.15 = 5%.
# 브리프의 예시 수치(93,000/60,000 손절, 3.0%/0.75% 가정)는 이 저장소의
# 실제 기본값(15%/0.75%)과 맞지 않아 그대로 쓰면 어느 캡이 이기는지가
# 뒤바뀐다 — 그래서 crossover를 설정에서 계산해 손절거리를 그 위/아래로
# 충분히 벌린다.
# -------------------------------------------


def test_lineage_records_every_cap_and_the_binding_one():
    a = _agent()
    p = a.risk_params
    crossover_pct = (p.risk_budget_pct / 100.0) / (p.max_single_position_pct * 1.0)
    stop_distance_pct = crossover_pct / 2  # crossover보다 충분히 짧다
    entry_price = 100_000.0
    stop_loss = entry_price * (1 - stop_distance_pct)

    lineage = {}
    value = a._calculate_max_position_value(
        EQUITY, risk_score=1, entry_price=entry_price, stop_loss=stop_loss,
        adtv=None, lineage=lineage,
    )
    # risk_score=1 -> risk_factor=1.0. 손절거리가 crossover보다 짧으므로
    # risk_bucket_cap(=base_max)이 r_cap보다 타이트해 이긴다.
    assert lineage["risk_factor"] == 1.0
    assert lineage["base_max"] == pytest.approx(EQUITY * p.max_single_position_pct)
    assert lineage["risk_bucket_cap"] == pytest.approx(EQUITY * p.max_single_position_pct)
    assert lineage["r_cap"] is not None and lineage["r_cap"] > lineage["risk_bucket_cap"]
    assert lineage["liquidity_cap"] is None
    assert lineage["binding"] == "risk_bucket_cap"
    assert value == pytest.approx(lineage["risk_bucket_cap"])


def test_lineage_binding_is_r_cap_when_stop_is_far():
    """손절이 멀면 R-캡이 종목캡보다 타이트해진다."""
    a = _agent()
    p = a.risk_params
    crossover_pct = (p.risk_budget_pct / 100.0) / (p.max_single_position_pct * 1.0)
    stop_distance_pct = min(crossover_pct * 4, 0.9)  # crossover보다 충분히 길다
    entry_price = 100_000.0
    stop_loss = entry_price * (1 - stop_distance_pct)

    lineage = {}
    value = a._calculate_max_position_value(
        EQUITY, risk_score=1, entry_price=entry_price, stop_loss=stop_loss,
        adtv=None, lineage=lineage,
    )
    assert lineage["binding"] == "r_cap"
    assert value == pytest.approx(lineage["r_cap"])


def test_lineage_records_risk_bucket_multiplier():
    a = _agent()
    for score, expected in [(1, 1.0), (5, 0.7), (9, 0.5)]:
        lineage = {}
        a._calculate_max_position_value(EQUITY, score, lineage=lineage)
        assert lineage["risk_factor"] == expected


def test_lineage_records_liquidity_cap_when_binding():
    """adtv가 얕으면 유동성 캡이 리스크버킷 캡보다 타이트해 이긴다 — 기존
    test_portfolio_agent_rebalance_market.py의
    test_calculate_max_position_value_applies_liquidity_cap_when_binding과
    같은 시나리오(adtv=20억)에 lineage 관측을 더한 것."""
    a = _agent()
    lineage = {}
    value = a._calculate_max_position_value(
        EQUITY, risk_score=1, adtv=2_000_000_000.0, lineage=lineage,
    )
    assert lineage["liquidity_cap"] is not None
    assert lineage["binding"] == "liquidity_cap"
    assert value == pytest.approx(lineage["liquidity_cap"])


def test_lineage_liquidity_cap_is_none_when_adtv_unknown():
    a = _agent()
    lineage = {}
    a._calculate_max_position_value(EQUITY, risk_score=1, adtv=None, lineage=lineage)
    assert lineage["liquidity_cap"] is None


# -------------------------------------------
# Wiring: does the lineage actually land on a real agent_chat_decisions row?
#
# `PortfolioAgent.calculate_allocation` builds the lineage dict and returns
# it on `AllocationPlan.sizing_lineage` (a pure, synchronous, no-I/O
# computation — proven above). `ExecutionCoordinator.on_trade_approved` is
# the only caller, and it already has a `session_id` in scope that equals
# `agent_chat_decisions.id` for the agent-chat autonomous path (per
# `services/agent_chat/decision_log.py::serialize_session`, and confirmed
# `persist_session` always runs before `on_trade_approved` is ever reached
# in that path — `services/agent_chat/coordinator.py:994` then `:998`/
# `:1080`/`:1192`). This drives that real coordinator method end-to-end
# (mocking only the broker call and `PortfolioAgent.calculate_allocation`'s
# internals — the sizing math itself is covered exhaustively above) and
# reads the row back through `isolated_storage_service` to prove the write
# actually lands, not just that the accessor method is syntactically wired.
# -------------------------------------------


async def test_sizing_lineage_lands_on_the_decision_row(isolated_storage_service):
    from datetime import datetime
    from unittest.mock import AsyncMock, MagicMock

    from services.trading.coordinator import ExecutionCoordinator
    from services.trading.market_hours import MarketSession
    from services.trading.models import (
        AllocationPlan,
        OrderResult,
        OrderSide,
        TradingMode,
    )

    decision_id = "u3-wiring-test-decision"
    await isolated_storage_service.save_agent_chat_decision(
        {
            "id": decision_id,
            "ticker": "005930",
            "trade_date": "2026-08-05",
            "status": "decided",
            "action": "BUY",
            "confidence": 0.7,
            "consensus_level": 0.8,
            "rationale": "test",
        },
        [],
    )

    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._state.mode = TradingMode.ACTIVE
    coord._market_hours.get_market_session = MagicMock(
        return_value=MarketSession(
            is_open=True,
            current_time=datetime.now(),
            next_open=None,
            next_close=None,
            message="open",
        )
    )
    coord._refresh_account_info = AsyncMock()
    # Never touch the real Kiwoom singleton for ADTV — BUY always resolves
    # it before calculate_allocation; short-circuit to None (fail-open,
    # matches _resolve_adtv's own documented degrade path).
    coord.portfolio_agent._resolve_adtv = AsyncMock(return_value=None)

    async def _fake_execute_order(order):
        return OrderResult(
            order_id="o1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=order.price or 50_000,
            status="filled",
        )

    coord._execute_order = _fake_execute_order

    stub_lineage = {
        "base_max": 74_550_000.0,
        "risk_factor": 1.0,
        "risk_bucket_cap": 74_550_000.0,
        "r_cap": None,
        "liquidity_cap": None,
        "binding": "risk_bucket_cap",
    }
    stub_plan = AllocationPlan(
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.BUY,
        quantity=1,
        entry_price=50_000,
        estimated_amount=50_000,
        position_pct=1.0,
        rationale="stub allocation",
        rebalance_orders=[],
        sizing_lineage=stub_lineage,
    )
    coord.portfolio_agent.calculate_allocation = MagicMock(return_value=stub_plan)

    await coord.on_trade_approved(
        session_id=decision_id,
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=50_000,
        stop_loss=None,
        take_profit=None,
        risk_score=1,
        quantity_override=1,
    )

    rows = await isolated_storage_service.get_agent_chat_decisions(ticker="005930")
    matches = [r for r in rows if r["id"] == decision_id]
    assert matches, "decision row not found"
    raw = matches[0]["sizing_lineage"]
    assert raw is not None, "sizing_lineage column is NULL -- the write never landed"
    assert json.loads(raw) == stub_lineage


async def test_sizing_lineage_write_is_a_noop_when_no_matching_decision_row(
    isolated_storage_service,
):
    """A session_id with no backing agent_chat_decisions row (e.g. a
    manually-approved trade, or a queued trade predating this column) must
    not raise -- same convention as update_decision_outcome/
    update_decision_label."""
    from datetime import datetime
    from unittest.mock import AsyncMock, MagicMock

    from services.trading.coordinator import ExecutionCoordinator
    from services.trading.market_hours import MarketSession
    from services.trading.models import (
        AllocationPlan,
        OrderResult,
        OrderSide,
        TradingMode,
    )

    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._state.mode = TradingMode.ACTIVE
    coord._market_hours.get_market_session = MagicMock(
        return_value=MarketSession(
            is_open=True,
            current_time=datetime.now(),
            next_open=None,
            next_close=None,
            message="open",
        )
    )
    coord._refresh_account_info = AsyncMock()
    coord.portfolio_agent._resolve_adtv = AsyncMock(return_value=None)

    async def _fake_execute_order(order):
        return OrderResult(
            order_id="o1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=order.price or 50_000,
            status="filled",
        )

    coord._execute_order = _fake_execute_order

    stub_plan = AllocationPlan(
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.BUY,
        quantity=1,
        entry_price=50_000,
        estimated_amount=50_000,
        position_pct=1.0,
        rationale="stub allocation",
        rebalance_orders=[],
        sizing_lineage={"binding": "risk_bucket_cap"},
    )
    coord.portfolio_agent.calculate_allocation = MagicMock(return_value=stub_plan)

    # Must not raise even though "no-such-decision" matches no row.
    allocation = await coord.on_trade_approved(
        session_id="no-such-decision",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=50_000,
        stop_loss=None,
        take_profit=None,
        risk_score=1,
        quantity_override=1,
    )
    assert allocation.quantity == 1
