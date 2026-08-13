"""L4: end-to-end decision <-> fill <-> P&L <-> calibration lineage.

L1 (persist_analysis_decision / decision_source), L2 (order-placement
lineage wiring), and L3 (PositionManager provenance) each landed their own
narrow slice with unit-level tests. Nothing before this file exercised the
FULL chain end-to-end against real production functions: a persisted
decision -> a recorded BUY fill -> a real ExecutionCoordinator position
carrying that decision as `analysis_session_id` -> a real SELL close ->
`kr_realized_pnl` (entry/exit ids) -> `update_decision_outcome` backfilling
the entry decision's `outcome_realized_pnl` -> `label_and_calibrate` scoring
it.

Two entry points into that SAME chain are covered, mirroring spec D1's two
decision_source values:

  1. the "analysis" path (LangGraph): `persist_analysis_decision`.
  2. the "agent_chat" path (group discussion): `decision_log.persist_session`
     (this is also the ONLY path with backing votes, so it is additionally
     used to prove per-agent calibration rows get produced).

Everything runs against an isolated tmp-path StorageService (never the real
data/storage.db — see the `temp_storage` fixture, which mirrors the pattern
already established in test_kr_execution_trade_log.py /
test_kr_realized_pnl.py).
"""

from datetime import datetime
from typing import Optional

import pytest

import services.storage_service as ss
from services.agent_chat.decision_log import persist_session
from services.agent_chat.models import (
    AgentType,
    AgentVote,
    ChatSession,
    DecisionAction,
    MarketContext,
    SessionStatus,
    TradeDecision,
    VoteType,
)
from services.storage_service import StorageService
from services.trading import trade_log
from services.trading.calibration import label_and_calibrate
from services.trading.coordinator import ExecutionCoordinator
from services.trading.decision_ledger import persist_analysis_decision
from services.trading.models import ManagedPosition, OrderResult, OrderSide

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    storage = StorageService(db_path=tmp_path / "lineage_e2e.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


def _real_coordinator() -> ExecutionCoordinator:
    coordinator = ExecutionCoordinator(kiwoom_client=None)
    # record_kr_realized_pnl is only fired when persistence is "active"
    # (_apply_sell_position_delta's own gate) — mirrors
    # test_kr_execution_trade_log.py's precedent for exercising the real
    # coordinator without a live persistence subsystem behind it.
    coordinator._persistence_active = True
    return coordinator


async def _close_full_position(
    coordinator: ExecutionCoordinator,
    *,
    ticker: str,
    exit_price: float,
    exit_decision_id: Optional[str],
) -> None:
    """Real SELL through the coordinator's own choke point
    (`_close_position` -> `_apply_sell_fill` -> `_apply_sell_position_delta`
    -> `record_kr_realized_pnl`), with the broker call itself stubbed (the
    lineage machinery under test lives entirely on the coordinator/storage
    side, not inside the Kiwoom order adapter)."""

    async def _exec_close(order):
        return OrderResult(
            order_id="ORD-E2E-SELL",
            ticker=order.ticker,
            side=OrderSide.SELL,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=exit_price,
            status="filled",
        )

    coordinator._execute_order = _exec_close
    await coordinator._close_position(ticker, decision_id=exit_decision_id)
    await trade_log.wait_for_pending_trade_fill_writes()


# -------------------------------------------
# 1) analysis path: persist_analysis_decision -> ... -> label_and_calibrate
# -------------------------------------------


async def test_analysis_path_full_lineage_e2e(temp_storage):
    storage = temp_storage

    # -- entry decision (L1) --
    entry_decision_id = await persist_analysis_decision(
        storage,
        session_id="sess-analysis-entry",
        ticker="005930",
        action="BUY",
        confidence=0.8,
        rationale="e2e entry",
    )
    assert entry_decision_id is not None
    assert entry_decision_id != "sess-analysis-entry"  # durable id, not the SM session id

    # -- BUY fill recorded, carrying decision_id/entry_or_exit (L2) --
    await trade_log.record_trade_fill_async(
        stk_cd="005930",
        stk_nm="삼성전자",
        side="buy",
        order_type="limit",
        price=70000,
        quantity=10,
        executed_quantity=10,
        status="completed",
        order_id="ORD-E2E-BUY",
        session_id="sess-analysis-entry",
        decision_id=entry_decision_id,
        entry_or_exit="entry",
    )
    trades = await storage.get_kr_stock_trades()
    assert len(trades) == 1
    assert trades[0]["decision_id"] == entry_decision_id
    assert trades[0]["entry_or_exit"] == "entry"

    # -- real ExecutionCoordinator position carrying the durable decision id --
    coordinator = _real_coordinator()
    coordinator._add_position(
        ManagedPosition(
            ticker="005930",
            stock_name="삼성전자",
            quantity=10,
            avg_price=70000,
            current_price=70000,
            analysis_session_id=entry_decision_id,
        )
    )
    assert coordinator._state.positions[0].analysis_session_id == entry_decision_id

    # -- exit decision + real SELL through coordinator._close_position --
    exit_decision_id = await persist_analysis_decision(
        storage,
        session_id="sess-analysis-exit",
        ticker="005930",
        action="SELL",
        confidence=0.7,
        rationale="e2e exit",
    )
    assert exit_decision_id is not None

    await _close_full_position(
        coordinator,
        ticker="005930",
        exit_price=75000,
        exit_decision_id=exit_decision_id,
    )

    # -- kr_realized_pnl carries BOTH entry and exit decision ids --
    pnl_rows = await storage.get_kr_realized_pnl(stk_cd="005930")
    assert len(pnl_rows) == 1
    assert pnl_rows[0]["entry_decision_id"] == entry_decision_id
    assert pnl_rows[0]["exit_decision_id"] == exit_decision_id
    expected_pnl = (75000 - 70000) * 10  # gross -- 원장은 gross를 그대로 든다
    assert pnl_rows[0]["realized_amount"] == expected_pnl

    # 2026-08-08: 원장이 gross와 net을 나란히 든다. 수수료 편도 2bp + 매도
    # 증권거래세 23bp -> 매수 700,000*2bp=140, 매도 750,000*2bp=150,
    # 세금 750,000*23bp=1,725.
    expected_fee = 140 + 150
    expected_tax = 1_725
    expected_net = expected_pnl - expected_fee - expected_tax  # 47,985
    assert pnl_rows[0]["fee"] == expected_fee
    assert pnl_rows[0]["tax"] == expected_tax
    assert pnl_rows[0]["net_amount"] == expected_net

    # -- outcome backfilled onto the ENTRY decision (record_kr_realized_pnl_async
    # -> update_decision_outcome, exercised for real via the fire-and-forget
    # SELL path above) -- 학습 신호는 **net**이다(gross면 비용을 못 넘긴
    # 거래가 "승리"로 학습된다).
    decisions = {
        d["id"]: d for d in await storage.get_agent_chat_decisions(ticker="005930")
    }
    assert decisions[entry_decision_id]["outcome_realized_pnl"] == expected_net
    assert decisions[entry_decision_id]["decision_source"] == "analysis"

    # -- direct confirmation update_decision_outcome itself reports success --
    assert await storage.update_decision_outcome(entry_decision_id, expected_net) is True

    # -- label_and_calibrate scores the entry decision --
    # I3 (final-review fix): persist_analysis_decision now stamps trade_date
    # as explicit KST "today" (services.trading.decision_ledger._KST) rather
    # than leaving it NULL -- as_of_date here must be computed the SAME way
    # (not naive datetime.now(), which can drift a calendar day from KST on
    # a non-KST host) so this test's window check stays host-timezone
    # independent instead of relying on _within_window's missing-trade_date
    # fail-open (the exact behavior this fix removes).
    from datetime import timedelta, timezone

    as_of_date = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    result = await label_and_calibrate(storage, as_of_date)
    assert result["decisions_scored"] >= 1

    relabeled = {
        d["id"]: d for d in await storage.get_agent_chat_decisions(ticker="005930")
    }
    assert relabeled[entry_decision_id]["outcome_label"] == "correct"


# -------------------------------------------
# 2) agent_chat path: persist_session -> ... -> per-agent calibration
# -------------------------------------------


def _chat_session(
    *, action: DecisionAction, votes: list[AgentVote]
) -> ChatSession:
    context = MarketContext(
        ticker="005930",
        stock_name="삼성전자",
        current_price=70000,
        price_change_pct=0.5,
    )
    session = ChatSession(ticker="005930", stock_name="삼성전자", context=context)
    session.status = SessionStatus.DECIDED
    session.decision = TradeDecision(
        action=action,
        confidence=0.75,
        consensus_level=0.8,
        rationale="e2e agent-chat decision",
        entry_price=70000 if action == DecisionAction.BUY else 75000,
    )
    session.votes = votes
    return session


async def test_agent_chat_path_full_lineage_e2e(temp_storage):
    storage = temp_storage

    # -- entry decision + votes persisted via decision_log.persist_session --
    entry_session = _chat_session(
        action=DecisionAction.BUY,
        votes=[
            AgentVote(
                agent_type=AgentType.TECHNICAL,
                vote=VoteType.BUY,
                confidence=0.8,
                reasoning="e2e bullish",
            ),
            AgentVote(
                agent_type=AgentType.MODERATOR,
                vote=VoteType.STRONG_BUY,
                confidence=0.9,
                reasoning="moderator never scores",
            ),
        ],
    )
    await persist_session(entry_session)
    entry_decision_id = entry_session.id

    saved = {
        d["id"]: d for d in await storage.get_agent_chat_decisions(ticker="005930")
    }
    assert entry_decision_id in saved
    votes = await storage.get_agent_chat_votes(entry_decision_id)
    assert len(votes) == 2

    # -- BUY fill recorded, carrying the SAME durable decision id --
    await trade_log.record_trade_fill_async(
        stk_cd="005930",
        stk_nm="삼성전자",
        side="buy",
        order_type="limit",
        price=70000,
        quantity=10,
        executed_quantity=10,
        status="completed",
        order_id="ORD-E2E-CHAT-BUY",
        session_id=entry_decision_id,
        decision_id=entry_decision_id,
        entry_or_exit="entry",
    )

    # -- real ExecutionCoordinator position --
    coordinator = _real_coordinator()
    coordinator._add_position(
        ManagedPosition(
            ticker="005930",
            stock_name="삼성전자",
            quantity=10,
            avg_price=70000,
            current_price=70000,
            analysis_session_id=entry_decision_id,
        )
    )

    # -- exit decision (a second discussion) + real SELL --
    exit_session = _chat_session(action=DecisionAction.SELL, votes=[])
    await persist_session(exit_session)
    exit_decision_id = exit_session.id

    await _close_full_position(
        coordinator,
        ticker="005930",
        exit_price=63000,  # a LOSS this time, to exercise the "incorrect" label
        exit_decision_id=exit_decision_id,
    )

    pnl_rows = await storage.get_kr_realized_pnl(stk_cd="005930")
    assert len(pnl_rows) == 1
    assert pnl_rows[0]["entry_decision_id"] == entry_decision_id
    assert pnl_rows[0]["exit_decision_id"] == exit_decision_id
    expected_pnl = (63000 - 70000) * 10  # gross
    assert pnl_rows[0]["realized_amount"] == expected_pnl

    # 매수 700,000*2bp=140, 매도 630,000*2bp=126, 세금 630,000*23bp=1,449.
    expected_fee = 140 + 126
    expected_tax = 1_449
    expected_net = expected_pnl - expected_fee - expected_tax  # -71,715
    assert pnl_rows[0]["net_amount"] == expected_net

    decisions = {
        d["id"]: d for d in await storage.get_agent_chat_decisions(ticker="005930")
    }
    assert decisions[entry_decision_id]["outcome_realized_pnl"] == expected_net
    # decision_source is unset for the normal agent_chat debate path (NULL ==
    # 'agent_chat' by read-consumer convention, spec D1) — never 'analysis'.
    assert decisions[entry_decision_id]["decision_source"] != "analysis"

    # -- label_and_calibrate: decision scored AND a per-agent row produced --
    as_of_date = datetime.now().strftime("%Y-%m-%d")
    result = await label_and_calibrate(storage, as_of_date)
    assert result["decisions_scored"] >= 1

    per_agent = result["per_agent_accuracy"]
    assert "technical" in per_agent
    assert per_agent["technical"]["decisions_scored"] >= 1
    # moderator votes are excluded entirely (never scores, calibration.py's
    # _EXCLUDED_AGENT_TYPES) -- must not appear even though it voted.
    assert "moderator" not in per_agent

    calibration_rows = {
        r["agent_type"]: r for r in await storage.get_agent_calibration(as_of_date)
    }
    assert "technical" in calibration_rows
    assert calibration_rows["technical"]["decisions_scored"] >= 1
