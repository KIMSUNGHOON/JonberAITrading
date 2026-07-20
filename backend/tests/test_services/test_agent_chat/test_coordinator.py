"""
Tests for ChatCoordinator

Unit tests for the ChatCoordinator that manages multiple chat rooms.
"""

import asyncio

import pandas as pd
import pytest
import pytest_asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from services.agent_chat.models import (
    SessionStatus,
    DecisionAction,
    MarketContext,
    ChatSession,
    TradeDecision,
)
from services.agent_chat.coordinator import (
    ChatCoordinator,
    get_chat_coordinator,
)
from services.trading.models import ActivityType, AllocationPlan, OrderSide


# -------------------------------------------
# Fixtures
# -------------------------------------------


@pytest.fixture
def coordinator():
    """Create a ChatCoordinator instance for testing."""
    return ChatCoordinator(
        check_interval_minutes=5,
        max_concurrent_discussions=3,
        min_discussion_interval_minutes=30,
    )


@pytest.fixture
def mock_market_context():
    """Create a mock market context."""
    return MarketContext(
        ticker="005930",
        stock_name="삼성전자",
        current_price=72500,
        price_change_pct=0.5,
    )


@pytest.fixture
def mock_session(mock_market_context):
    """Create a mock ChatSession."""
    session = ChatSession(
        ticker="005930",
        stock_name="삼성전자",
        context=mock_market_context,
    )
    session.status = SessionStatus.DECIDED
    session.decision = TradeDecision(
        action=DecisionAction.BUY,
        confidence=0.85,
        consensus_level=0.8,
        entry_price=72500,
        rationale="Test decision",
    )
    return session


# -------------------------------------------
# Initialization Tests
# -------------------------------------------


class TestCoordinatorInitialization:
    """Tests for ChatCoordinator initialization."""

    def test_create_coordinator(self):
        """Test creating a coordinator."""
        coord = ChatCoordinator(
            check_interval_minutes=10,
            max_concurrent_discussions=5,
        )

        assert coord.check_interval == 10
        assert coord.max_concurrent == 5
        assert not coord._running

    def test_default_values(self):
        """Test default values (monitoring-cadence tuning, 2026-07-15):
        watch-list checks now default to 60s (1 minute), not 5 minutes --
        the checks read already-fresh watch prices (periodic refresh loop)
        and make no Kiwoom call themselves, so tightening the cadence is
        safe; the discussion throttle (min_discussion_interval/
        max_concurrent) remains the real rate limit."""
        coord = ChatCoordinator()

        assert coord.check_interval == 1
        assert coord.max_concurrent == 3


# -------------------------------------------
# Lifecycle Tests
# -------------------------------------------


class TestCoordinatorLifecycle:
    """Tests for coordinator lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running(self, coordinator):
        """Test that start sets running flag."""
        with patch.object(coordinator, '_position_manager', None):
            with patch('services.agent_chat.coordinator.get_position_manager') as mock_pm:
                mock_pm.return_value = AsyncMock()
                mock_pm.return_value.start = AsyncMock()
                mock_pm.return_value.sync_from_account = AsyncMock()
                mock_pm.return_value.set_chat_coordinator = MagicMock()
                mock_pm.return_value.get_all_positions = MagicMock(return_value=[])

                await coordinator.start()

                assert coordinator._running
                assert coordinator._scheduler is not None

                # Cleanup
                await coordinator.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self, coordinator):
        """Test that stop clears running flag."""
        coordinator._running = True

        with patch.object(coordinator, '_position_manager', None):
            await coordinator.stop()

        assert not coordinator._running

    @pytest.mark.asyncio
    async def test_start_schedules_watch_list_check_every_60_seconds(self):
        """Monitoring-cadence tuning (2026-07-15): a coordinator built with
        no explicit check_interval_minutes (i.e. via the default, as the
        `get_chat_coordinator()` singleton does) must schedule the
        watch-list job on a 60s / 1-minute APScheduler interval -- not the
        old 5-minute one. Deliberately does NOT use the `coordinator`
        fixture, which pins check_interval_minutes=5 explicitly."""
        coord = ChatCoordinator()

        with patch.object(coord, '_position_manager', None):
            with patch('services.agent_chat.coordinator.get_position_manager') as mock_pm:
                mock_pm.return_value = AsyncMock()
                mock_pm.return_value.start = AsyncMock()
                mock_pm.return_value.sync_from_account = AsyncMock()
                mock_pm.return_value.set_chat_coordinator = MagicMock()
                mock_pm.return_value.get_all_positions = MagicMock(return_value=[])

                await coord.start()

                job = coord._scheduler.get_job('watch_list_check')
                assert job is not None
                assert job.trigger.interval == timedelta(minutes=1)

                await coord.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent(self, coordinator):
        """Test that calling start twice is safe."""
        with patch.object(coordinator, '_position_manager', None):
            with patch('services.agent_chat.coordinator.get_position_manager') as mock_pm:
                mock_pm.return_value = AsyncMock()
                mock_pm.return_value.start = AsyncMock()
                mock_pm.return_value.sync_from_account = AsyncMock()
                mock_pm.return_value.set_chat_coordinator = MagicMock()
                mock_pm.return_value.get_all_positions = MagicMock(return_value=[])

                await coordinator.start()
                scheduler1 = coordinator._scheduler

                await coordinator.start()  # Should be no-op
                scheduler2 = coordinator._scheduler

                assert scheduler1 == scheduler2

                await coordinator.stop()


# -------------------------------------------
# Callback Tests
# -------------------------------------------


class TestCoordinatorCallbacks:
    """Tests for coordinator callbacks."""

    def test_register_decision_callback(self, coordinator):
        """Test registering a decision callback."""
        callback = MagicMock()
        coordinator.on_decision(callback)

        assert callback in coordinator._on_decision_callbacks

    def test_register_session_complete_callback(self, coordinator):
        """Test registering a session complete callback."""
        callback = MagicMock()
        coordinator.on_session_complete(callback)

        assert callback in coordinator._on_session_complete_callbacks


# -------------------------------------------
# Discussion Management Tests
# -------------------------------------------


class TestDiscussionManagement:
    """Tests for discussion management.

    P4-4 (session-ssot): get_session_history/get_session_by_id no longer
    read the retired in-memory `_session_history` list -- they merge
    SessionManager (kind="discussion") with the durable ledger. The deeper
    merge/dedup/sort semantics (multiple sources, NULL-safety, restart
    simulation) are covered by test_history_merge.py against real SM/storage
    backends; this class keeps only shallow wiring-level checks (mocked
    sources) plus the _active_rooms fast-path, which is coordinator-local.
    """

    def test_get_active_discussions_empty(self, coordinator):
        """Test getting active discussions when none exist."""
        active = coordinator.get_active_discussions()

        assert active == []

    @pytest.mark.asyncio
    async def test_get_session_history_empty(self, coordinator, monkeypatch):
        """Test getting session history when both SM and the ledger are empty."""
        async def fake_get_session_manager():
            sm = AsyncMock()
            sm.get_all_sessions = AsyncMock(return_value={})
            return sm

        async def fake_get_storage_service():
            storage = AsyncMock()
            storage.get_agent_chat_decisions = AsyncMock(return_value=[])
            return storage

        monkeypatch.setattr(
            "services.agent_chat.coordinator.get_session_manager", fake_get_session_manager
        )
        monkeypatch.setattr(
            "services.agent_chat.coordinator.get_storage_service", fake_get_storage_service
        )

        history = await coordinator.get_session_history()

        assert history == []

    @pytest.mark.asyncio
    async def test_get_session_history_ledger_only_null_safe(self, coordinator, monkeypatch):
        """A legacy (pre-P4-3) ledger row with NULL total_messages/total_rounds
        0-falls-back, and the ledger's own status vocabulary passes through
        unchanged when SM has nothing for this ticker."""
        async def fake_get_session_manager():
            sm = AsyncMock()
            sm.get_all_sessions = AsyncMock(return_value={})
            return sm

        rows = [
            {
                "id": "d1",
                "ticker": "005930",
                "stock_name": "삼성전자",
                "status": "decided",
                "action": "BUY",
                "confidence": 0.8,
                "consensus_level": 0.9,
                "created_at": "2026-07-16 09:00:00",
                "total_messages": None,
                "total_rounds": None,
            }
        ]

        async def fake_get_storage_service():
            storage = AsyncMock()
            storage.get_agent_chat_decisions = AsyncMock(return_value=rows)
            return storage

        monkeypatch.setattr(
            "services.agent_chat.coordinator.get_session_manager", fake_get_session_manager
        )
        monkeypatch.setattr(
            "services.agent_chat.coordinator.get_storage_service", fake_get_storage_service
        )

        history = await coordinator.get_session_history()

        assert len(history) == 1
        assert history[0]["id"] == "d1"
        assert history[0]["status"] == "decided"
        assert history[0]["total_messages"] == 0
        assert history[0]["total_rounds"] == 0

    @pytest.mark.asyncio
    async def test_get_session_by_id_active_room_wins(self, coordinator, mock_session):
        """Tier 1: a live room in _active_rooms returns the exact object,
        without touching SM/storage at all."""
        room = MagicMock()
        room.session = mock_session
        coordinator._active_rooms[mock_session.ticker] = room

        found = await coordinator.get_session_by_id(mock_session.id)

        assert found is mock_session

    @pytest.mark.asyncio
    async def test_get_session_by_id_not_found(self, coordinator, monkeypatch):
        """No active room, no SM row, no ledger transcript -> None (not a raise)."""
        async def fake_get_session_manager():
            sm = AsyncMock()
            sm.get_session = AsyncMock(return_value=None)
            return sm

        async def fake_get_storage_service():
            storage = AsyncMock()
            storage.get_agent_chat_transcript = AsyncMock(return_value=None)
            return storage

        monkeypatch.setattr(
            "services.agent_chat.coordinator.get_session_manager", fake_get_session_manager
        )
        monkeypatch.setattr(
            "services.agent_chat.coordinator.get_storage_service", fake_get_storage_service
        )

        found = await coordinator.get_session_by_id("non-existent")

        assert found is None


# -------------------------------------------
# Manual Discussion Tests
# -------------------------------------------


class TestManualDiscussion:
    """Tests for manual discussion triggering."""

    @pytest.mark.asyncio
    async def test_start_manual_discussion(self, coordinator, mock_market_context):
        """Test starting a manual discussion."""
        with patch('services.agent_chat.coordinator.ChatRoom') as MockRoom:
            mock_session = MagicMock()
            mock_session.id = "test-session"
            mock_session.status = SessionStatus.DECIDED
            mock_session.decision = TradeDecision(
                action=DecisionAction.HOLD,
                confidence=0.7,
                consensus_level=0.75,
                rationale="Hold decision",
            )

            mock_room_instance = AsyncMock()
            mock_room_instance.start = AsyncMock(return_value=mock_session)
            mock_room_instance.session = mock_session
            MockRoom.return_value = mock_room_instance

            with patch.object(coordinator, '_fetch_market_context') as mock_context:
                # A real (non-stale) MarketContext — a bare AsyncMock() stood
                # in here before the 2026-07-14 CRITICAL safety fix, and its
                # auto-mocked `.is_stale` attribute is truthy, which would
                # now (correctly) make start_manual_discussion refuse to
                # start a discussion on "stale" data.
                mock_context.return_value = mock_market_context

                session = await coordinator.start_manual_discussion(
                    ticker="005930",
                    stock_name="삼성전자",
                )

                assert session is not None
                assert session.id == "test-session"

    @pytest.mark.asyncio
    async def test_manual_discussion_conflict(self, coordinator):
        """Test that concurrent discussions for same stock are prevented."""
        # Simulate active room
        coordinator._active_rooms["005930"] = MagicMock()

        with pytest.raises(ValueError, match="already in progress"):
            await coordinator.start_manual_discussion(
                ticker="005930",
                stock_name="삼성전자",
            )


# -------------------------------------------
# Stale Market Data Tests (CRITICAL safety fix, 2026-07-14)
# -------------------------------------------
#
# get_kr_stock_info now returns None on a real Kiwoom fetch failure instead
# of a fabricated np.random-seeded mock price. _fetch_market_context must
# translate that into an is_stale=True MarketContext, and both discussion
# entry points must refuse to start agents debating/voting on it.


class TestStaleMarketContext:
    """Tests for _fetch_market_context's handling of a failed quote fetch."""

    @pytest.mark.asyncio
    async def test_fetch_market_context_none_stock_info_is_stale(self, coordinator):
        with patch(
            "agents.tools.kr_market_data.get_kr_stock_info",
            AsyncMock(return_value=None),
        ):
            context = await coordinator._fetch_market_context("005930", "삼성전자")

        assert context.is_stale is True
        assert context.current_price == 0

    @pytest.mark.asyncio
    async def test_fetch_market_context_success_is_not_stale(self, coordinator):
        real_stock_info = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_prc": 72500,
            "prdy_ctrt": 0.5,
        }
        with (
            patch(
                "agents.tools.kr_market_data.get_kr_stock_info",
                AsyncMock(return_value=real_stock_info),
            ),
            patch(
                "agents.tools.kr_market_data.get_kr_daily_chart",
                AsyncMock(return_value=pd.DataFrame()),
            ),
            patch(
                "app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
                AsyncMock(side_effect=RuntimeError("no account access")),
            ),
        ):
            context = await coordinator._fetch_market_context("005930", "삼성전자")

        assert context.is_stale is False
        assert context.current_price == 72500


class TestStaleMarketContextBlocksDiscussion:
    """Both discussion entry points must refuse to proceed on stale data."""

    @pytest.mark.asyncio
    async def test_start_manual_discussion_raises_on_stale_context(self, coordinator):
        stale_context = MarketContext(
            ticker="005930",
            stock_name="삼성전자",
            current_price=0,
            price_change_pct=0,
            is_stale=True,
        )
        with patch.object(coordinator, "_fetch_market_context") as mock_context:
            mock_context.return_value = stale_context

            with pytest.raises(ValueError, match="stale"):
                await coordinator.start_manual_discussion(
                    ticker="005930",
                    stock_name="삼성전자",
                )

        # No room should have been created/left active for this ticker.
        assert "005930" not in coordinator._active_rooms

    @pytest.mark.asyncio
    async def test_start_discussion_skips_room_on_stale_context(self, coordinator):
        """The auto watch-list path (_start_discussion) must skip creating a
        ChatRoom on stale data — no exception, just a no-op (it will be
        retried on the next _check_watch_list pass)."""
        stale_context = MarketContext(
            ticker="005930",
            stock_name="삼성전자",
            current_price=0,
            price_change_pct=0,
            is_stale=True,
        )
        with (
            patch.object(coordinator, "_fetch_market_context") as mock_context,
            patch("services.agent_chat.coordinator.ChatRoom") as MockRoom,
        ):
            mock_context.return_value = stale_context

            await coordinator._start_discussion(
                {"ticker": "005930", "stock_name": "삼성전자"}
            )

        MockRoom.assert_not_called()
        assert "005930" not in coordinator._active_rooms


# -------------------------------------------
# Opportunity Detection Tests
# -------------------------------------------


class TestOpportunityDetection:
    """Tests for opportunity detection logic."""

    @pytest.mark.asyncio
    async def test_detect_opportunity_target_price_hit(self, coordinator):
        """Test opportunity detection when target price is near."""
        stock = {
            "ticker": "005930",
            "current_price": 72000,
            "target_entry_price": 72500,
            "confidence": 0.8,
        }

        should_discuss = await coordinator._detect_opportunity(stock)

        # Within 3% of target should trigger
        # Implementation may vary, check both cases
        assert should_discuss is True or should_discuss is False

    @pytest.mark.asyncio
    async def test_detect_opportunity_low_confidence(self, coordinator):
        """Test that low confidence doesn't trigger discussion."""
        stock = {
            "ticker": "005930",
            "current_price": 72500,
            "target_entry_price": 80000,  # Far from current price (>3%)
            "confidence": 0.5,  # Low confidence
        }

        should_discuss = await coordinator._detect_opportunity(stock)

        # Low confidence + price far from target = no trigger
        assert should_discuss is False


# -------------------------------------------
# Discussion Interval Tests
# -------------------------------------------


class TestDiscussionInterval:
    """Tests for discussion interval enforcement."""

    def test_was_recently_discussed_recent(self, coordinator):
        """Test that recently discussed stocks are detected."""
        ticker = "005930"

        # Set last discussion to recent time
        coordinator._last_discussion[ticker] = datetime.now()

        was_recent = coordinator._was_recently_discussed(ticker)

        assert was_recent is True

    def test_was_recently_discussed_old(self, coordinator):
        """Test that old discussions are not flagged."""
        ticker = "005930"

        # Set last discussion to past interval
        coordinator._last_discussion[ticker] = datetime.now() - timedelta(minutes=60)

        was_recent = coordinator._was_recently_discussed(ticker)

        assert was_recent is False

    def test_was_recently_discussed_never(self, coordinator):
        """Test that never discussed stocks are allowed."""
        ticker = "005930"

        # No previous discussion
        was_recent = coordinator._was_recently_discussed(ticker)

        assert was_recent is False


# -------------------------------------------
# Max Concurrent Tests
# -------------------------------------------


class TestMaxConcurrent:
    """Tests for maximum concurrent discussions limit."""

    def test_respects_max_concurrent(self, coordinator):
        """Test that max concurrent limit is respected."""
        # Fill up active rooms
        for i in range(coordinator.max_concurrent):
            coordinator._active_rooms[f"ticker_{i}"] = MagicMock()

        # Should not allow more
        at_limit = len(coordinator._active_rooms) >= coordinator.max_concurrent

        assert at_limit is True


# -------------------------------------------
# Singleton Tests
# -------------------------------------------


class TestCoordinatorSingleton:
    """Tests for singleton pattern."""

    @pytest.mark.asyncio
    async def test_get_coordinator_returns_same_instance(self):
        """Test that get_chat_coordinator returns the same instance."""
        coord1 = await get_chat_coordinator()
        coord2 = await get_chat_coordinator()

        assert coord1 is coord2


# -------------------------------------------
# P2 SSOT prep (2026-07-14): autonomous execution must flip the watch entry
# -------------------------------------------
#
# _execute_trade never went through ExecutionCoordinator.convert_watch_to_queue
# (it calls on_trade_approved directly), so a watch-list item that got
# autonomously executed stayed ACTIVE forever — the 5-min watch-list check
# could re-detect the same "opportunity" and trigger a duplicate discussion/
# execution on the same ticker.


def _allocation(
    quantity: int,
    rationale: str,
    ticker: str = "005930",
    entry_price: float = 72_500,
) -> AllocationPlan:
    """Build a real AllocationPlan shaped like on_trade_approved's actual
    return value for the given scenario (see services/trading/coordinator.py
    on_trade_approved: TRADE_QUEUED/TRADE_REJECTED/order-result branches all
    return this exact model)."""
    return AllocationPlan(
        ticker=ticker,
        side=OrderSide.BUY,
        quantity=quantity,
        entry_price=entry_price,
        estimated_amount=quantity * entry_price,
        position_pct=1.0,
        rationale=rationale,
    )


class TestAutonomousExecutionMarksWatchConverted:
    """_execute_trade must mark the originating watch entry CONVERTED --
    but ONLY when on_trade_approved's return shows a trade genuinely
    executed or was queued (T2 review gap, 2026-07-14: on_trade_approved has
    non-exception TRADE_REJECTED/ORDER_FAILED outcomes where no trade
    resulted at all, and converting the watch entry on those retires a real
    signal that was never acted on)."""

    async def _run(self, coordinator, allocation, activity_log=None):
        """Run _execute_trade with `trading_coord.on_trade_approved`
        returning `allocation`, and return the fake coordinator so the
        caller can assert on mark_watch_converted."""
        import app.dependencies as deps_module

        fake_trading_coord = MagicMock()
        fake_trading_coord.on_trade_approved = AsyncMock(return_value=allocation)
        fake_trading_coord.mark_watch_converted = MagicMock(return_value=True)
        fake_trading_coord.get_activity_log = MagicMock(
            return_value=activity_log if activity_log is not None else []
        )

        async def fake_get_trading_coordinator():
            return fake_trading_coord

        with patch.object(
            deps_module, "get_trading_coordinator", fake_get_trading_coordinator
        ):
            decision = TradeDecision(
                action=DecisionAction.BUY,
                confidence=0.9,
                consensus_level=0.9,
                rationale="워치리스트 목표가 도달",
                quantity=10,
                entry_price=72_500,
            )
            session = ChatSession(ticker="005930", stock_name="삼성전자")

            await coordinator._execute_trade("005930", decision, session)

        return fake_trading_coord

    @pytest.mark.asyncio
    async def test_execute_trade_marks_watch_converted_on_filled_order(
        self, coordinator
    ):
        """A genuinely filled order (quantity>0, ORDER_EXECUTED logged)
        flips the watch entry to CONVERTED so it is never re-discussed."""
        allocation = _allocation(10, "정상 매수: 10주 매수 (risk-based sizing)")
        activity_log = [
            SimpleNamespace(ticker="005930", activity_type=ActivityType.ORDER_EXECUTED),
        ]

        fake_trading_coord = await self._run(coordinator, allocation, activity_log)

        fake_trading_coord.on_trade_approved.assert_awaited_once()
        fake_trading_coord.mark_watch_converted.assert_called_once_with("005930")

    @pytest.mark.asyncio
    async def test_execute_trade_marks_watch_converted_when_queued(self, coordinator):
        """A trade that gets queued (market closed / system paused-stopped)
        is a real, actionable outcome even though quantity=0 -- it must
        still flip the watch entry to CONVERTED."""
        allocation = _allocation(
            0, "Trade queued: Market closed (Queue ID: queue_20260714120000)"
        )

        fake_trading_coord = await self._run(coordinator, allocation)

        fake_trading_coord.mark_watch_converted.assert_called_once_with("005930")

    @pytest.mark.asyncio
    async def test_execute_trade_skips_mark_when_daily_limit_rejected(
        self, coordinator
    ):
        """TRADE_REJECTED via the daily trade limit (quantity=0, non-queued
        rationale) must NOT convert -- the limit resets tomorrow and the
        watch item should stay eligible for re-evaluation."""
        allocation = _allocation(0, "Daily trade limit reached (10/10)")

        fake_trading_coord = await self._run(coordinator, allocation)

        fake_trading_coord.on_trade_approved.assert_awaited_once()
        fake_trading_coord.mark_watch_converted.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_trade_skips_mark_when_allocation_sized_to_zero(
        self, coordinator
    ):
        """TRADE_REJECTED via portfolio sizing to <=0 shares must NOT
        convert -- sizing may succeed later (e.g. after cash frees up)."""
        allocation = _allocation(0, "Allocation rejected: insufficient buying power")

        fake_trading_coord = await self._run(coordinator, allocation)

        fake_trading_coord.mark_watch_converted.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_trade_skips_mark_when_order_failed(self, coordinator):
        """ORDER_FAILED: the order was placed (quantity>0, same
        AllocationPlan shape as a genuine fill) but the broker filled 0
        shares. A broker blip shouldn't retire the signal -- must NOT
        convert. Distinguishing this from a real fill requires the activity
        log on_trade_approved wrote synchronously before returning."""
        allocation = _allocation(10, "정상 매수: 10주 매수 (risk-based sizing)")
        activity_log = [
            SimpleNamespace(ticker="005930", activity_type=ActivityType.ORDER_FAILED),
        ]

        fake_trading_coord = await self._run(coordinator, allocation, activity_log)

        fake_trading_coord.on_trade_approved.assert_awaited_once()
        fake_trading_coord.mark_watch_converted.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_trade_skips_mark_when_action_unmapped(self, coordinator):
        """No action_map entry (HOLD/WATCH/NO_ACTION) means no order was placed
        — the watch entry must NOT be marked converted for a no-op decision."""
        import app.dependencies as deps_module

        fake_trading_coord = MagicMock()
        fake_trading_coord.on_trade_approved = AsyncMock(return_value=None)
        fake_trading_coord.mark_watch_converted = MagicMock(return_value=True)

        async def fake_get_trading_coordinator():
            return fake_trading_coord

        with patch.object(
            deps_module, "get_trading_coordinator", fake_get_trading_coordinator
        ):
            decision = TradeDecision(
                action=DecisionAction.HOLD,
                confidence=0.9,
                consensus_level=0.9,
                rationale="관망",
            )
            session = ChatSession(ticker="005930", stock_name="삼성전자")

            await coordinator._execute_trade("005930", decision, session)

        fake_trading_coord.on_trade_approved.assert_not_awaited()
        fake_trading_coord.mark_watch_converted.assert_not_called()


# -------------------------------------------
# E-2: Vote Direction Bias Removal — market_cap correction + sentiment wiring
# -------------------------------------------
#
# 편향③(시총 미보정)+②(sentiment momentum 메아리) 관련 _fetch_market_context
# 회귀. NewsSentimentAnalyzer는 실 LLM/실 네트워크 금지 원칙에 따라 항상 목.


class TestMarketCapCorrection:
    """coordinator._fetch_market_context의 mrkt_tot_amt(억원 단위)를 원
    단위로 보정하는지 확인(scanner.py:852-856과 동일 근거). 무보정 시
    fundamental_agent가 왜소한 값으로 표시해 LLM이 "데이터 오류"를 매수
    보류 근거로 오용한다(편향③, 라이브 워치 레코드 실측)."""

    @pytest.mark.asyncio
    async def test_market_cap_scaled_by_1e8(self, coordinator):
        real_stock_info = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_prc": 72500,
            "prdy_ctrt": 0.5,
            "mrkt_tot_amt": 14_908_010,  # 억원 단위 (라이브 실측 2026-07-18)
        }
        with (
            patch(
                "agents.tools.kr_market_data.get_kr_stock_info",
                AsyncMock(return_value=real_stock_info),
            ),
            patch(
                "agents.tools.kr_market_data.get_kr_daily_chart",
                AsyncMock(return_value=pd.DataFrame()),
            ),
            patch(
                "app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
                AsyncMock(side_effect=RuntimeError("no account access")),
            ),
        ):
            context = await coordinator._fetch_market_context("005930", "삼성전자")

        assert context.market_cap == 14_908_010 * 100_000_000
        # 수기 대조: 14,908,010억원 -> 약 1,490.8조원
        assert round(context.market_cap / 1_000_000_000_000, 1) == 1490.8

    @pytest.mark.asyncio
    async def test_market_cap_none_when_source_missing(self, coordinator):
        real_stock_info = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_prc": 72500,
            "prdy_ctrt": 0.5,
        }
        with (
            patch(
                "agents.tools.kr_market_data.get_kr_stock_info",
                AsyncMock(return_value=real_stock_info),
            ),
            patch(
                "agents.tools.kr_market_data.get_kr_daily_chart",
                AsyncMock(return_value=pd.DataFrame()),
            ),
            patch(
                "app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
                AsyncMock(side_effect=RuntimeError("no account access")),
            ),
        ):
            context = await coordinator._fetch_market_context("005930", "삼성전자")

        assert context.market_cap is None


def _mock_news_service(article_count: int = 6):
    """뉴스 서비스 목 — providers 존재+search_stock_news가 기사 목록 반환."""
    from services.news.base import NewsArticle

    articles = [
        NewsArticle(
            title=f"뉴스 {i}",
            link=f"https://example.com/{i}",
            pub_date=datetime.now(),
        )
        for i in range(article_count)
    ]
    news_service = MagicMock()
    news_service.providers = ["mock_provider"]
    news_service.search_stock_news = AsyncMock(
        return_value=SimpleNamespace(articles=articles)
    )
    return news_service


class TestNewsSentimentWiring:
    """E-2 편향②: 뉴스 상위 5건을 NewsSentimentAnalyzer로 실분석해 실감성
    라벨을 쓰는지, 예외/타임아웃 시 기존 등락률 라벨로 안전 하강하는지
    확인한다(spec E-2 ③). 실 네트워크·실 LLM 금지 — analyzer는 항상 목."""

    @pytest.mark.asyncio
    async def test_analyzer_success_uses_real_label_over_price_fallback(self, coordinator):
        from services.news.sentiment import NewsSentimentResult

        # prdy_ctrt=-3.0%면 등락률 폴백 라벨은 negative가 될 상황 — analyzer
        # 성공 시 실라벨(positive)이 폴백에 덮이지 않고 그대로 쓰여야 한다.
        real_stock_info = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_prc": 72500,
            "prdy_ctrt": -3.0,
        }
        mock_news_service = _mock_news_service(article_count=6)

        with (
            patch(
                "agents.tools.kr_market_data.get_kr_stock_info",
                AsyncMock(return_value=real_stock_info),
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
                AsyncMock(return_value=mock_news_service),
            ),
            patch("services.news.sentiment.NewsSentimentAnalyzer") as MockAnalyzer,
        ):
            MockAnalyzer.return_value.analyze = AsyncMock(
                return_value=NewsSentimentResult(
                    sentiment="positive",
                    score=55,
                    confidence=0.8,
                    summary="긍정적 실적 발표",
                )
            )
            context = await coordinator._fetch_market_context("005930", "삼성전자")

        assert context.news_sentiment == "positive"

        # 상위 5건만 analyzer에 전달됐는지(전체 6건 중)
        _, call_kwargs = MockAnalyzer.return_value.analyze.call_args
        assert len(call_kwargs["articles"]) == 5

    @pytest.mark.asyncio
    async def test_analyzer_exception_falls_back_to_price_change_label(self, coordinator):
        real_stock_info = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_prc": 72500,
            "prdy_ctrt": 3.0,
        }
        mock_news_service = _mock_news_service()

        with (
            patch(
                "agents.tools.kr_market_data.get_kr_stock_info",
                AsyncMock(return_value=real_stock_info),
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
                AsyncMock(return_value=mock_news_service),
            ),
            patch("services.news.sentiment.NewsSentimentAnalyzer") as MockAnalyzer,
            patch("services.agent_chat.coordinator.logger") as mock_logger,
        ):
            MockAnalyzer.return_value.analyze = AsyncMock(
                side_effect=RuntimeError("llm backend down")
            )
            context = await coordinator._fetch_market_context("005930", "삼성전자")

        assert context.news_sentiment == "positive"  # 등락률 +3.0% 폴백 라벨

        fallback_calls = [
            c for c in mock_logger.warning.call_args_list
            if c.args and c.args[0] == "news_sentiment_fallback"
        ]
        assert len(fallback_calls) == 1

    @pytest.mark.asyncio
    async def test_analyzer_timeout_falls_back_to_price_change_label(self, coordinator):
        real_stock_info = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_prc": 72500,
            "prdy_ctrt": -3.0,
        }
        mock_news_service = _mock_news_service()

        with (
            patch(
                "agents.tools.kr_market_data.get_kr_stock_info",
                AsyncMock(return_value=real_stock_info),
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
                AsyncMock(return_value=mock_news_service),
            ),
            patch("services.news.sentiment.NewsSentimentAnalyzer") as MockAnalyzer,
        ):
            MockAnalyzer.return_value.analyze = AsyncMock(side_effect=asyncio.TimeoutError())
            context = await coordinator._fetch_market_context("005930", "삼성전자")

        assert context.news_sentiment == "negative"  # 등락률 -3.0% 폴백 라벨

    @pytest.mark.asyncio
    async def test_no_articles_skips_analyzer_and_leaves_sentiment_none(self, coordinator):
        real_stock_info = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_prc": 72500,
            "prdy_ctrt": 0.5,
        }
        mock_news_service = _mock_news_service(article_count=0)

        with (
            patch(
                "agents.tools.kr_market_data.get_kr_stock_info",
                AsyncMock(return_value=real_stock_info),
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
                AsyncMock(return_value=mock_news_service),
            ),
            patch("services.news.sentiment.NewsSentimentAnalyzer") as MockAnalyzer,
        ):
            context = await coordinator._fetch_market_context("005930", "삼성전자")

        assert context.news_sentiment is None
        MockAnalyzer.return_value.analyze.assert_not_called()
