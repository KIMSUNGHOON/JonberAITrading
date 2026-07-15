"""
Tests for decision_log — Phase1 C1/C4 durable persistence of completed
agent-chat ChatSessions (decision + votes + sentiment/behavioral signals).

Before this, ChatSession completions only ever lived in the coordinator's
in-memory `_session_history` list and evaporated on restart. `serialize_session`
is a pure function (ChatSession -> (decision dict, list of vote dicts));
`persist_session` wires it to StorageService.save_agent_chat_decision and is
failure-harmless (never raises) so a storage outage can't break the
discussion flow.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

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
from services.agent_chat.decision_log import (
    _extract_behavioral,
    persist_session,
    serialize_session,
)


def _make_session(**overrides) -> ChatSession:
    """Build a ChatSession shaped like a real completed discussion, with
    override hooks for context/status/decision/votes plus any other
    ChatSession attribute (applied via setattr after construction)."""
    context = overrides.pop("context", "unset")
    if context == "unset":
        context = MarketContext(
            ticker="005930",
            stock_name="삼성전자",
            current_price=72500,
            price_change_pct=0.69,
            news_sentiment="positive",
            news_count=5,
            indicators={
                "volume_ratio": 1.5,
                "trend": "bullish",
                "cross": "golden_cross",
                "rsi": 58,
            },
        )

    session = ChatSession(
        ticker="005930",
        stock_name="삼성전자",
        context=context,
    )
    session.status = overrides.pop("status", SessionStatus.DECIDED)

    decision = overrides.pop("decision", "unset")
    if decision == "unset":
        decision = TradeDecision(
            action=DecisionAction.BUY,
            confidence=0.8,
            consensus_level=0.82,
            rationale="돌파",
            dissenting_opinions=["리스크 과열"],
            entry_price=73000,
            stop_loss=70000,
            take_profit=80000,
            position_pct=0.1,
        )
    session.decision = decision

    session.votes = overrides.pop(
        "votes",
        [
            AgentVote(
                agent_type=AgentType.TECHNICAL,
                vote=VoteType.BUY,
                confidence=0.7,
                reasoning="골든크로스",
                key_factors=["golden_cross"],
            ),
            AgentVote(
                agent_type=AgentType.RISK,
                vote=VoteType.HOLD,
                confidence=0.6,
                reasoning="변동성",
                key_factors=["vol"],
                suggested_position_pct=0.1,
                suggested_stop_loss_pct=0.05,
                suggested_take_profit_pct=0.08,
            ),
        ],
    )

    for k, v in overrides.items():
        setattr(session, k, v)

    return session


# -------------------------------------------
# serialize_session — the brief's Step-1 assertions
# -------------------------------------------


class TestSerializeSessionBasics:
    def test_brief_assertions(self):
        session = _make_session()
        dec, votes = serialize_session(session)

        assert dec["action"] == "BUY" and dec["ticker"] == session.ticker
        assert dec["news_sentiment"] == "positive" and dec["news_count"] == 5
        assert (
            dec["behavioral_signals"]["volume_ratio"] == 1.5
            and dec["behavioral_signals"]["cross"] == "golden_cross"
        )
        assert dec["dissenting_opinions"] == session.decision.dissenting_opinions
        assert len(votes) == 2 and votes[0]["decision_id"] == session.id

    def test_id_and_stock_name_and_status(self):
        session = _make_session()
        dec, _ = serialize_session(session)

        assert dec["id"] == session.id
        assert dec["stock_name"] == session.stock_name
        assert dec["status"] == "decided"

    def test_decision_numeric_fields_passthrough(self):
        session = _make_session()
        dec, _ = serialize_session(session)

        assert dec["confidence"] == 0.8
        assert dec["consensus_level"] == 0.82
        assert dec["entry_price"] == 73000
        assert dec["stop_loss"] == 70000
        assert dec["take_profit"] == 80000
        assert dec["position_pct"] == 0.1
        assert dec["rationale"] == "돌파"

    def test_provenance_placeholders_are_none(self):
        session = _make_session()
        dec, _ = serialize_session(session)

        assert dec["market_sentiment"] is None
        assert dec["flow"] is None
        assert dec["regime_snapshot_id"] is None
        assert dec["outcome_realized_pnl"] is None
        assert dec["outcome_label"] is None


class TestSerializeSessionNoDecision:
    """A session that ended without a decision (cancelled/timeout) must
    serialize to action=NO_ACTION with the decision-derived numeric fields
    all None — never raise on decision=None."""

    def test_no_decision_defaults_to_no_action(self):
        session = _make_session(decision=None, status=SessionStatus.CANCELLED)
        dec, _ = serialize_session(session)

        assert dec["action"] == "NO_ACTION"
        assert dec["status"] == "cancelled"
        assert dec["confidence"] is None
        assert dec["rationale"] is None
        assert dec["dissenting_opinions"] is None
        assert dec["entry_price"] is None
        assert dec["stop_loss"] is None
        assert dec["take_profit"] is None
        assert dec["position_pct"] is None

    def test_no_decision_still_reports_session_consensus_level(self):
        session = _make_session(decision=None, status=SessionStatus.TIMEOUT)
        session.consensus_level = 0.42
        dec, _ = serialize_session(session)

        assert dec["consensus_level"] == 0.42


class TestSerializeSessionTradeDate:
    def test_prefers_ended_at(self):
        session = _make_session()
        session.created_at = datetime(2026, 7, 1)
        session.ended_at = datetime(2026, 7, 15)

        dec, _ = serialize_session(session)

        assert dec["trade_date"] == "2026-07-15"

    def test_falls_back_to_created_at_when_no_ended_at(self):
        session = _make_session(ended_at=None)
        session.created_at = datetime(2026, 7, 1)

        dec, _ = serialize_session(session)

        assert dec["trade_date"] == "2026-07-01"


class TestSerializeSessionNoContext:
    def test_missing_context_yields_none_sentiment_and_all_none_behavioral(self):
        session = _make_session(context=None)
        dec, _ = serialize_session(session)

        assert dec["news_sentiment"] is None
        assert dec["news_count"] is None
        assert dec["behavioral_signals"] == {
            "volume_ratio": None,
            "trend": None,
            "cross": None,
            "rsi": None,
        }


class TestSerializeSessionVotes:
    def test_vote_dict_shape(self):
        session = _make_session()
        _, votes = serialize_session(session)

        risk_vote = next(v for v in votes if v["agent_type"] == "risk")
        assert risk_vote["decision_id"] == session.id
        assert risk_vote["vote"] == "hold"
        assert risk_vote["confidence"] == 0.6
        assert risk_vote["reasoning"] == "변동성"
        assert risk_vote["key_factors"] == ["vol"]
        assert risk_vote["suggested_position_pct"] == 0.1
        assert risk_vote["suggested_stop_loss_pct"] == 0.05
        assert risk_vote["suggested_take_profit_pct"] == 0.08

    def test_no_votes_returns_empty_list(self):
        session = _make_session(votes=[])
        _, votes = serialize_session(session)

        assert votes == []

    def test_serialize_is_pure_no_io(self):
        """serialize_session must not touch storage — no patch target needed
        for this test to pass; it's exercising the absence of side effects
        by simply calling it directly with no storage service configured."""
        session = _make_session()
        # Calling twice must be side-effect-free / deterministic.
        dec1, votes1 = serialize_session(session)
        dec2, votes2 = serialize_session(session)
        assert dec1 == dec2
        assert votes1 == votes2


# -------------------------------------------
# _extract_behavioral — flat vs nested indicator shapes
# -------------------------------------------


class TestExtractBehavioral:
    def test_flat_shape_preferred(self):
        result = _extract_behavioral(
            {
                "volume_ratio": 1.5,
                "trend": "bullish",
                "cross": "golden_cross",
                "rsi": 58,
            }
        )
        assert result == {
            "volume_ratio": 1.5,
            "trend": "bullish",
            "cross": "golden_cross",
            "rsi": 58,
        }

    def test_nested_shape_fallback(self):
        result = _extract_behavioral(
            {
                "volume": {"ratio": 2.1},
                "momentum": {"rsi": 42.0},
                "trend": {"direction": "down"},
            }
        )
        assert result == {
            "volume_ratio": 2.1,
            "trend": "down",
            "cross": None,
            "rsi": 42.0,
        }

    def test_none_indicators_returns_all_none(self):
        assert _extract_behavioral(None) == {
            "volume_ratio": None,
            "trend": None,
            "cross": None,
            "rsi": None,
        }

    def test_empty_dict_returns_all_none(self):
        assert _extract_behavioral({}) == {
            "volume_ratio": None,
            "trend": None,
            "cross": None,
            "rsi": None,
        }

    def test_partial_flat_missing_keys_are_none(self):
        result = _extract_behavioral({"rsi": 71.0})
        assert result == {
            "volume_ratio": None,
            "trend": None,
            "cross": None,
            "rsi": 71.0,
        }


# -------------------------------------------
# persist_session — wiring + failure-harmless contract
# -------------------------------------------


class TestPersistSession:
    @pytest.mark.asyncio
    async def test_calls_storage_with_serialized_payload(self):
        session = _make_session()
        fake_storage = AsyncMock()
        fake_storage.save_agent_chat_decision = AsyncMock(return_value=True)

        with patch(
            "services.agent_chat.decision_log.get_storage_service",
            AsyncMock(return_value=fake_storage),
        ):
            await persist_session(session)

        fake_storage.save_agent_chat_decision.assert_awaited_once()
        call_args = fake_storage.save_agent_chat_decision.await_args.args
        assert call_args[0]["id"] == session.id
        assert call_args[0]["action"] == "BUY"
        assert len(call_args[1]) == 2

    @pytest.mark.asyncio
    async def test_never_raises_when_get_storage_service_fails(self):
        session = _make_session()

        with patch(
            "services.agent_chat.decision_log.get_storage_service",
            AsyncMock(side_effect=RuntimeError("db unavailable")),
        ):
            await persist_session(session)  # must not raise

    @pytest.mark.asyncio
    async def test_never_raises_when_save_fails(self):
        session = _make_session()
        fake_storage = AsyncMock()
        fake_storage.save_agent_chat_decision = AsyncMock(
            side_effect=RuntimeError("write failed")
        )

        with patch(
            "services.agent_chat.decision_log.get_storage_service",
            AsyncMock(return_value=fake_storage),
        ):
            await persist_session(session)  # must not raise

    @pytest.mark.asyncio
    async def test_never_raises_on_malformed_session(self):
        """A session missing expected structure (e.g. context=None combined
        with an unexpected votes shape) must still degrade to a logged
        warning, never propagate."""
        session = _make_session(context=None, votes=None)

        with patch(
            "services.agent_chat.decision_log.get_storage_service",
            AsyncMock(side_effect=RuntimeError("unreachable")),
        ):
            await persist_session(session)  # must not raise
