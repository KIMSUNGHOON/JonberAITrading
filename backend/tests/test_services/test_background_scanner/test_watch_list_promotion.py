"""Scan-completion → watch-list auto-promotion (P1-5, discovery dead-end fix).

ROOT: `BackgroundScanner` scans all KOSPI/KOSDAQ stocks and stores results,
but nothing ever consumed them — a completed scan sat in memory/SQLite with
no downstream reader, so agent-chat's 5-minute watch monitor and
watch-to-queue conversion never picked up anything the scanner discovered.

FIX: on scan completion, `_promote_results_to_watch_list` pushes the top
BUY/WATCH results (by confidence) into `ExecutionCoordinator.add_to_watch_list`
— the same sink the WATCH-decision graph node and the
`/trading/watch-list/add` route already use. Auto-promotion is gated by
`_auto_promote_enabled` (default False — must be explicitly turned on).

These tests call `_promote_results_to_watch_list` directly (the method scan
completion invokes) with the coordinator dependency monkeypatched to a real
`ExecutionCoordinator(kiwoom_client=None)`, mirroring the pattern used in
`tests/test_kr_watch_list_addition.py` for the WATCH-decision path.
"""

from unittest.mock import AsyncMock

import pytest

from services.background_scanner.scanner import BackgroundScanner, ScanResult
from services.trading.coordinator import ExecutionCoordinator

# Note: no module-level `pytestmark = pytest.mark.asyncio` — pytest.ini sets
# asyncio_mode = auto, so `async def test_*` is picked up automatically. This
# module mixes a sync test (test_disabled_by_default) with async ones, and
# the blanket marker would spuriously tag the sync test too.


def _result(stk_cd, action="BUY", confidence=0.9, stk_nm=None) -> ScanResult:
    return ScanResult(
        stk_cd=stk_cd,
        stk_nm=stk_nm or f"종목{stk_cd}",
        action=action,
        signal=action.lower(),
        confidence=confidence,
        summary=f"{stk_cd} 분석 요약",
        key_factors=["factor1"],
        current_price=10_000,
        market_type="코스피",
    )


@pytest.fixture
def coordinator() -> ExecutionCoordinator:
    """Real coordinator (no kiwoom client) so add_to_watch_list's pydantic
    validation and the existing/dedup branch actually run, same as
    test_kr_watch_list_addition.py."""
    return ExecutionCoordinator(kiwoom_client=None)


@pytest.fixture
def scanner(monkeypatch, coordinator) -> BackgroundScanner:
    import app.dependencies as deps

    monkeypatch.setattr(
        deps, "get_trading_coordinator", AsyncMock(return_value=coordinator)
    )
    s = BackgroundScanner()
    return s


class TestAutoPromoteDefaultOff:
    def test_disabled_by_default(self, scanner):
        """A fresh scanner must not auto-promote until explicitly enabled."""
        assert scanner._auto_promote_enabled is False

    async def test_auto_promote_off_promotes_nothing(self, scanner, coordinator):
        scanner._results = [_result("005930", action="BUY", confidence=0.95)]
        # _auto_promote_enabled left at its default (False)

        promoted = await scanner._promote_results_to_watch_list("session-1")

        assert promoted == 0
        assert coordinator.get_watch_list() == []


class TestAutoPromoteEnabled:
    async def test_top_k_promoted_above_threshold(self, scanner, coordinator):
        scanner._auto_promote_enabled = True
        scanner._promote_confidence_threshold = 0.7
        scanner._promote_max_count = 2
        scanner._results = [
            _result("005930", action="BUY", confidence=0.95),
            _result("000660", action="WATCH", confidence=0.9),
            _result("035420", action="BUY", confidence=0.8),  # 3rd — beyond max_count
        ]

        promoted = await scanner._promote_results_to_watch_list("session-1")

        assert promoted == 2
        tickers = {w.ticker for w in coordinator.get_watch_list()}
        # The two highest-confidence candidates win the two available slots.
        assert tickers == {"005930", "000660"}

    async def test_below_threshold_excluded(self, scanner, coordinator):
        scanner._auto_promote_enabled = True
        scanner._promote_confidence_threshold = 0.7
        scanner._results = [
            _result("005930", action="BUY", confidence=0.5),  # below threshold
            _result("000660", action="WATCH", confidence=0.75),  # clears it
        ]

        promoted = await scanner._promote_results_to_watch_list("session-1")

        assert promoted == 1
        tickers = {w.ticker for w in coordinator.get_watch_list()}
        assert tickers == {"000660"}

    async def test_avoid_and_sell_never_promoted(self, scanner, coordinator):
        scanner._auto_promote_enabled = True
        scanner._promote_confidence_threshold = 0.5
        scanner._results = [
            _result("005930", action="AVOID", confidence=0.99),
            _result("000660", action="SELL", confidence=0.99),
            _result("035420", action="HOLD", confidence=0.99),
        ]

        promoted = await scanner._promote_results_to_watch_list("session-1")

        assert promoted == 0
        assert coordinator.get_watch_list() == []

    async def test_dedup_already_watched_ticker_not_doubled(self, scanner, coordinator):
        scanner._auto_promote_enabled = True
        scanner._promote_confidence_threshold = 0.7

        # Pre-existing watch-list entry for 005930 (e.g. from a prior scan or
        # a manual add).
        coordinator.add_to_watch_list(
            session_id="prior-session",
            ticker="005930",
            stock_name="삼성전자",
            signal="watch",
            confidence=0.8,
            current_price=70_000,
        )
        assert len(coordinator.get_watch_list()) == 1

        scanner._results = [
            _result("005930", action="BUY", confidence=0.95),  # already watched
            _result("000660", action="BUY", confidence=0.9),  # new
        ]

        promoted = await scanner._promote_results_to_watch_list("session-2")

        # Only the genuinely new ticker counts as a promotion.
        assert promoted == 1
        watch_list = coordinator.get_watch_list()
        assert len(watch_list) == 2
        tickers = [w.ticker for w in watch_list]
        assert tickers.count("005930") == 1, "existing ticker must not be duplicated"
        assert "000660" in tickers

    async def test_no_qualifying_candidates_returns_zero(self, scanner, coordinator):
        scanner._auto_promote_enabled = True
        scanner._promote_confidence_threshold = 0.9
        scanner._results = [_result("005930", action="BUY", confidence=0.5)]

        promoted = await scanner._promote_results_to_watch_list("session-1")

        assert promoted == 0
        assert coordinator.get_watch_list() == []
