"""
Tests for the discussion-transcript ledger (session-ssot P4-3).

Before this, a completed ChatSession's decision + votes summary was
persisted by decision_log.persist_session (see test_decision_log.py --
unchanged by this task), but the full message/round transcript was
discarded: it only ever lived in the coordinator's in-memory history and in
SessionManager's TTL'd state, both of which evaporate on restart/TTL expiry.
This file locks down two orthogonal things:

  - StorageService.save_agent_chat_transcript / get_agent_chat_transcript
    against a real tmp-file SQLite db: schema creation, round-trip content,
    INSERT OR REPLACE idempotency, and the additive total_messages/
    total_rounds columns on agent_chat_decisions (NULL-safe for rows written
    before this migration).
  - decision_log.persist_session's independence contract: the decision+votes
    save and the transcript save are two separate try/except blocks, so a
    failure in either one must not skip, roll back, or raise past the other.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from services.agent_chat.decision_log import persist_session
from services.agent_chat.models import (
    AgentMessage,
    AgentType,
    AgentVote,
    ChatRound,
    ChatSession,
    DecisionAction,
    MarketContext,
    MessageType,
    SessionStatus,
    TradeDecision,
    VoteType,
)
from services.storage_service import StorageService


def _make_session(**overrides) -> ChatSession:
    """Build a completed ChatSession with real rounds/messages/votes/decision
    -- unlike test_decision_log.py's helper (which only needs decision+votes
    for its serialize_session assertions), this one populates rounds/
    all_messages so round-trip assertions have transcript content to
    restore."""
    context = overrides.pop(
        "context",
        MarketContext(
            ticker="005930",
            stock_name="삼성전자",
            current_price=72500,
            price_change_pct=0.69,
            news_sentiment="positive",
            news_count=5,
        ),
    )

    session = ChatSession(ticker="005930", stock_name="삼성전자", context=context)
    session.status = overrides.pop("status", SessionStatus.DECIDED)

    msg1 = AgentMessage(
        agent_type=AgentType.TECHNICAL,
        agent_name="기술분석가",
        message_type=MessageType.ANALYSIS,
        content="골든크로스 발생",
    )
    msg2 = AgentMessage(
        agent_type=AgentType.RISK,
        agent_name="리스크관리자",
        message_type=MessageType.OPINION,
        content="변동성 확대 주의",
    )
    default_round = ChatRound(round_number=1, round_type="analysis", messages=[msg1, msg2])
    session.rounds = overrides.pop("rounds", [default_round])
    session.all_messages = overrides.pop("all_messages", [msg1, msg2])

    session.decision = overrides.pop(
        "decision",
        TradeDecision(
            action=DecisionAction.BUY,
            confidence=0.8,
            consensus_level=0.82,
            rationale="돌파",
            entry_price=73000,
            stop_loss=70000,
            take_profit=80000,
            position_pct=0.1,
        ),
    )
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
# ① persist_session -> real StorageService -> transcript round-trip
# -------------------------------------------


class TestTranscriptRoundtrip:
    @pytest.mark.asyncio
    async def test_persist_then_reconstruct_all_messages_and_rounds(self, tmp_path):
        session = _make_session()
        storage = StorageService(db_path=str(tmp_path / "t.db"))

        with patch(
            "services.agent_chat.decision_log.get_storage_service",
            AsyncMock(return_value=storage),
        ):
            await persist_session(session)

        raw = await storage.get_agent_chat_transcript(session.id)
        assert raw is not None

        restored = ChatSession.model_validate(json.loads(raw))
        assert len(restored.all_messages) == 2
        assert restored.all_messages[0].content == "골든크로스 발생"
        assert len(restored.rounds) == 1
        assert restored.rounds[0].round_type == "analysis"
        assert len(restored.rounds[0].messages) == 2
        assert restored.decision is not None
        assert restored.decision.action == DecisionAction.BUY
        assert len(restored.votes) == 2
        assert restored.id == session.id

    @pytest.mark.asyncio
    async def test_missing_session_returns_none(self, tmp_path):
        storage = StorageService(db_path=str(tmp_path / "t.db"))
        assert await storage.get_agent_chat_transcript("nonexistent-id") is None


# -------------------------------------------
# ⑤ INSERT OR REPLACE idempotency
# -------------------------------------------


class TestTranscriptReplaceIdempotent:
    @pytest.mark.asyncio
    async def test_repersisting_same_session_id_replaces_not_duplicates(self, tmp_path):
        session = _make_session()
        storage = StorageService(db_path=str(tmp_path / "t.db"))

        with patch(
            "services.agent_chat.decision_log.get_storage_service",
            AsyncMock(return_value=storage),
        ):
            await persist_session(session)

            # Mutate and re-persist under the same session id (e.g. a
            # session that somehow completes/re-flushes twice).
            extra_msg = AgentMessage(
                agent_type=AgentType.SENTIMENT,
                agent_name="센티먼트분석가",
                message_type=MessageType.OPINION,
                content="뉴스 호재",
            )
            session.all_messages.append(extra_msg)
            await persist_session(session)

        raw = await storage.get_agent_chat_transcript(session.id)
        restored = ChatSession.model_validate(json.loads(raw))
        assert len(restored.all_messages) == 3

        # Exactly one row for this session_id -- no duplicate accretion.
        import aiosqlite

        async with aiosqlite.connect(str(tmp_path / "t.db")) as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM agent_chat_transcripts WHERE session_id = ?",
                (session.id,),
            )
            row = await cursor.fetchone()
            assert row[0] == 1


# -------------------------------------------
# ②③ persist_session independence: neither write blocks/rolls back the other
# -------------------------------------------


class TestPersistSessionIndependence:
    @pytest.mark.asyncio
    async def test_transcript_save_failure_does_not_block_decision_save(self):
        session = _make_session()
        fake_storage = AsyncMock()
        fake_storage.save_agent_chat_decision = AsyncMock(return_value=True)
        fake_storage.save_agent_chat_transcript = AsyncMock(
            side_effect=RuntimeError("transcript write failed")
        )

        with patch(
            "services.agent_chat.decision_log.get_storage_service",
            AsyncMock(return_value=fake_storage),
        ):
            await persist_session(session)  # must not raise

        fake_storage.save_agent_chat_decision.assert_awaited_once()
        fake_storage.save_agent_chat_transcript.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_decision_save_failure_does_not_block_transcript_save(self):
        session = _make_session()
        fake_storage = AsyncMock()
        fake_storage.save_agent_chat_decision = AsyncMock(
            side_effect=RuntimeError("decision write failed")
        )
        fake_storage.save_agent_chat_transcript = AsyncMock(return_value=True)

        with patch(
            "services.agent_chat.decision_log.get_storage_service",
            AsyncMock(return_value=fake_storage),
        ):
            await persist_session(session)  # must not raise

        fake_storage.save_agent_chat_decision.assert_awaited_once()
        fake_storage.save_agent_chat_transcript.assert_awaited_once()
        call_args = fake_storage.save_agent_chat_transcript.await_args.args
        assert call_args[0] == session.id
        restored = ChatSession.model_validate(json.loads(call_args[1]))
        assert len(restored.all_messages) == 2


# -------------------------------------------
# ④ total_messages/total_rounds columns
# -------------------------------------------


class TestDecisionCountColumns:
    @pytest.mark.asyncio
    async def test_new_row_gets_total_messages_and_rounds(self, tmp_path):
        session = _make_session()
        storage = StorageService(db_path=str(tmp_path / "t.db"))

        with patch(
            "services.agent_chat.decision_log.get_storage_service",
            AsyncMock(return_value=storage),
        ):
            await persist_session(session)

        rows = await storage.get_agent_chat_decisions(ticker="005930")
        assert len(rows) == 1
        assert rows[0]["total_messages"] == 2
        assert rows[0]["total_rounds"] == 1

    @pytest.mark.asyncio
    async def test_preexisting_row_without_columns_reads_null_safely(self, tmp_path):
        """A row written before this migration (via the pre-P4-3 INSERT
        shape) has no total_messages/total_rounds -- _ensure_columns must
        add them as nullable so existing rows read back as NULL/None rather
        than erroring, and P4-4's list view is expected to 0-fallback that."""
        db_path = str(tmp_path / "t.db")
        storage = StorageService(db_path=db_path)
        await storage.initialize()

        import uuid

        import aiosqlite

        legacy_id = str(uuid.uuid4())
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute(
                """
                INSERT INTO agent_chat_decisions
                (id, ticker, stock_name, trade_date, status, action)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (legacy_id, "005930", "삼성전자", "2026-07-01", "decided", "BUY"),
            )
            await conn.commit()

        rows = await storage.get_agent_chat_decisions(ticker="005930")
        assert len(rows) == 1
        assert rows[0]["total_messages"] is None
        assert rows[0]["total_rounds"] is None
