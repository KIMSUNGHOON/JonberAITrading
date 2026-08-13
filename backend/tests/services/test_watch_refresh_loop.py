"""Periodic watch-list price refresh (monitoring-cadence-tuning arc, MAIN BODY).

Root cause (verified in services/trading/coordinator.py): `WatchedStock.
current_price` for ACTIVE watch entries was only ever refreshed at
coordinator `start()` and on each trade approval (via `_refresh_account_info`
-> `_reprice_positions`, coordinator.py ~1199-1206) — there was no periodic
loop. `ChatCoordinator._check_watch_list`'s target-entry proximity check
therefore compared against a price frozen for the entire session, giving zero
responsiveness for entry candidates.

Fix: a new `_refresh_watch_prices` sweep (WATCH-only — position prices stay
owned by `_reprice_positions`/RiskMonitor) driven by a new background loop
`_watch_refresh_loop`, using the same start()/stop() lifecycle shape as the
existing `_queue_scheduler_task` (R5-P1), and a dynamic TTL
(`services.trading.cadence.compute_watch_ttl`) so the refresh cadence scales
with the ACTIVE watch count instead of hammering (or under-using) the shared
Kiwoom quote budget.
"""
from unittest.mock import AsyncMock

import pytest

from services.trading.cadence import compute_watch_ttl
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import ManagedPosition, WatchedStock, WatchStatus

pytestmark = pytest.mark.asyncio


def _watched(ticker="005930", current_price=71_000.0, status=WatchStatus.ACTIVE, **kw) -> WatchedStock:
    return WatchedStock(
        session_id="s1",
        ticker=ticker,
        stock_name="삼성전자",
        current_price=current_price,
        status=status,
        **kw,
    )


def _position(ticker="005930", quantity=10, avg_price=70_000.0, **kw) -> ManagedPosition:
    kw.setdefault("current_price", avg_price)
    return ManagedPosition(
        ticker=ticker,
        stock_name="삼성전자",
        quantity=quantity,
        avg_price=avg_price,
        **kw,
    )


# -------------------------------------------
# Test B — _refresh_watch_prices
# -------------------------------------------


@pytest.fixture(autouse=True)
def _market_open_default(monkeypatch):
    """E2-2: `_refresh_watch_prices` now gates on `is_krx_open_cached`
    (장외 완전 idle). Every pre-existing test below this point calls
    `_refresh_watch_prices()` directly and asserts on its price-fetch
    behavior, with no opinion on market hours — pin the gate open by
    default so they stay independent of real wall-clock KRX hours (same
    regression-fragility fix E2-1 applied to `PositionManager.
    _check_all_positions`'s pre-existing callers). The `closed_market`/
    `open_market` fixtures below (Test B2) explicitly request this same
    monkeypatch target afterward and win, since fixture teardown/override
    follows request order within a test — they are the ones actually
    exercising the gate."""
    import services.trading.coordinator as trading_coord_mod
    monkeypatch.setattr(trading_coord_mod, "is_krx_open_cached", lambda: True)


async def test_refresh_watch_prices_updates_active_entries():
    """Both ACTIVE entries get their current_price bumped to the fresh quote."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._get_current_price = AsyncMock(return_value=80_000.0)
    coord._state.watch_list.append(_watched(ticker="005930", current_price=71_000.0))
    coord._state.watch_list.append(_watched(ticker="000660", current_price=140_000.0))

    await coord._refresh_watch_prices()

    by_ticker = {w.ticker: w for w in coord._state.watch_list}
    assert by_ticker["005930"].current_price == 80_000.0
    assert by_ticker["000660"].current_price == 80_000.0
    assert by_ticker["005930"].last_checked is not None
    assert by_ticker["000660"].last_checked is not None


async def test_refresh_watch_prices_does_not_touch_non_active_entries():
    """A CONVERTED/REMOVED entry's price is historical — must not be repriced."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._get_current_price = AsyncMock(return_value=80_000.0)
    coord._state.watch_list.append(_watched(ticker="005930", current_price=71_000.0))
    coord._state.watch_list.append(
        _watched(ticker="035420", current_price=200_000.0, status=WatchStatus.CONVERTED)
    )

    await coord._refresh_watch_prices()

    by_ticker = {w.ticker: w for w in coord._state.watch_list}
    assert by_ticker["005930"].current_price == 80_000.0
    assert by_ticker["035420"].current_price == 200_000.0
    assert by_ticker["035420"].last_checked is None


async def test_refresh_watch_prices_passes_dynamic_ttl_for_active_count():
    """W = 2 ACTIVE entries -> every fetch call uses ttl=compute_watch_ttl(2),
    not a fixed constant and not W including the non-ACTIVE entry."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    fetcher = AsyncMock(return_value=80_000.0)
    coord._get_current_price = fetcher
    coord._state.watch_list.append(_watched(ticker="005930"))
    coord._state.watch_list.append(_watched(ticker="000660"))
    coord._state.watch_list.append(_watched(ticker="035420", status=WatchStatus.REMOVED))

    await coord._refresh_watch_prices()

    expected_ttl = compute_watch_ttl(2)
    assert fetcher.await_count == 2
    for call in fetcher.await_args_list:
        args, kwargs = call
        assert kwargs.get("ttl") == expected_ttl


async def test_refresh_watch_prices_skips_falsy_price():
    """A falsy price (0/None — the fail-safe 'no fresh quote' signal) must
    never overwrite the last-known current_price (T2 stale-price contract)."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._get_current_price = AsyncMock(return_value=0)
    coord._state.watch_list.append(_watched(ticker="005930", current_price=71_000.0))

    await coord._refresh_watch_prices()

    watched = coord._state.watch_list[0]
    assert watched.current_price == 71_000.0
    assert watched.last_checked is None


async def test_refresh_watch_prices_survives_single_ticker_exception():
    """One ticker's fetch raising must not abort the sweep for the rest."""
    coord = ExecutionCoordinator(kiwoom_client=None)

    async def _flaky(ticker, ttl=None):
        if ticker == "005930":
            raise RuntimeError("kiwoom down")
        return 99_000.0

    coord._get_current_price = AsyncMock(side_effect=_flaky)
    coord._state.watch_list.append(_watched(ticker="005930", current_price=71_000.0))
    coord._state.watch_list.append(_watched(ticker="000660", current_price=140_000.0))

    await coord._refresh_watch_prices()

    by_ticker = {w.ticker: w for w in coord._state.watch_list}
    assert by_ticker["005930"].current_price == 71_000.0  # untouched, fetch raised
    assert by_ticker["000660"].current_price == 99_000.0  # sweep continued


async def test_refresh_watch_prices_skips_held_tickers():
    """A ticker that is BOTH held (open position) AND an ACTIVE watch entry
    must be SKIPPED by the watch sweep entirely — RiskMonitor already
    refreshes held tickers on its own tight `compute_held_ttl` cadence
    against the SAME `stock_info:<ticker>` cache key. If the watch loop also
    writes that key (on its much longer `compute_watch_ttl` TTL), it can
    clobber RiskMonitor's fresh read with a stale cached price for up to the
    watch TTL, delaying stop-loss/take-profit reaction (held+watched
    integration finding). W for the TTL formula must be the count of entries
    actually fetched (ACTIVE-and-not-held), so a held "AAA" + watched "BBB"
    fetches only "BBB" at ttl=compute_watch_ttl(1), not compute_watch_ttl(2)."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    fetcher = AsyncMock(return_value=80_000.0)
    coord._get_current_price = fetcher
    coord._state.positions.append(_position(ticker="AAA"))
    coord._state.watch_list.append(_watched(ticker="AAA", current_price=71_000.0))
    coord._state.watch_list.append(_watched(ticker="BBB", current_price=140_000.0))

    await coord._refresh_watch_prices()

    fetched_tickers = [call.args[0] for call in fetcher.await_args_list]
    assert "AAA" not in fetched_tickers
    assert fetched_tickers == ["BBB"]

    expected_ttl = compute_watch_ttl(1)
    for call in fetcher.await_args_list:
        _, kwargs = call
        assert kwargs.get("ttl") == expected_ttl

    by_ticker = {w.ticker: w for w in coord._state.watch_list}
    assert by_ticker["AAA"].current_price == 71_000.0  # untouched, held -> skipped
    assert by_ticker["AAA"].last_checked is None
    assert by_ticker["BBB"].current_price == 80_000.0


async def test_refresh_watch_prices_noop_on_empty_watch_list():
    """No ACTIVE entries -> no fetch calls, no error."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._get_current_price = AsyncMock(return_value=80_000.0)

    await coord._refresh_watch_prices()

    coord._get_current_price.assert_not_awaited()


# -------------------------------------------
# Test B2 — E2-2 after-hours gate (장외 완전 idle)
# -------------------------------------------
#
# `_watch_refresh_loop`/`_refresh_watch_prices` live here in
# `ExecutionCoordinator` (services/trading/coordinator.py) — NOT in
# `services/agent_chat/coordinator.py` as task-E2-2-brief.md's file list
# states (that module has no `_watch_refresh_loop`/`_refresh_watch_prices`
# symbol at all; verified by grep). These tests therefore live in THIS file
# (the existing convention/"관례" file for `_refresh_watch_prices`, per the
# brief's own Step 1 instruction to follow it) rather than in E2-1's
# test_afterhours_gate.py, which only imports agent_chat modules. Same
# no-op-cycle + transition-only-log pattern as E2-1
# (services/agent_chat/coordinator.py::_check_watch_list,
# services/agent_chat/position_manager.py) and E2-2's RiskMonitor gate: a
# monotonic-TTL cache (market_hours.is_krx_open_cached) gates the cycle's
# work at the head of `_refresh_watch_prices`, with a transition-only log
# helper (`_log_market_gate_once`) duplicated per-file by design (YAGNI).


@pytest.fixture
def closed_market(monkeypatch):
    import services.trading.coordinator as trading_coord_mod
    monkeypatch.setattr(trading_coord_mod, "is_krx_open_cached", lambda: False)


@pytest.fixture
def open_market(monkeypatch):
    import services.trading.coordinator as trading_coord_mod
    monkeypatch.setattr(trading_coord_mod, "is_krx_open_cached", lambda: True)


async def test_refresh_watch_prices_noop_when_closed(closed_market):
    """장 닫힘이면 _refresh_watch_prices가 어떤 가격도 조회하지 않고 조기
    반환한다."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._get_current_price = AsyncMock(return_value=80_000.0)
    coord._state.watch_list.append(_watched(ticker="005930", current_price=71_000.0))

    await coord._refresh_watch_prices()

    coord._get_current_price.assert_not_awaited()
    assert coord._state.watch_list[0].current_price == 71_000.0
    assert coord._state.watch_list[0].last_checked is None


async def test_refresh_watch_prices_unchanged_when_open(open_market):
    """열림이면 기존 경로 그대로 진입 — ACTIVE 워치 종목 가격이 갱신된다(회귀)."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._get_current_price = AsyncMock(return_value=80_000.0)
    coord._state.watch_list.append(_watched(ticker="005930", current_price=71_000.0))

    await coord._refresh_watch_prices()

    coord._get_current_price.assert_awaited()
    assert coord._state.watch_list[0].current_price == 80_000.0


async def test_gate_transition_logged_once_not_every_sweep(closed_market, caplog):
    """상태 전이 시에만 1회 로그 — 워치 갱신 사이클마다 로그 스팸 방지."""
    import logging

    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._get_current_price = AsyncMock(return_value=80_000.0)
    coord._state.watch_list.append(_watched(ticker="005930"))

    with caplog.at_level(logging.INFO, logger="services.trading.coordinator"):
        await coord._refresh_watch_prices()
        await coord._refresh_watch_prices()
        await coord._refresh_watch_prices()

    gate_logs = [r for r in caplog.records if "market_gate" in r.getMessage()]
    assert len(gate_logs) == 1


# -------------------------------------------
# Test C — start()/stop() lifecycle of _watch_refresh_task
# -------------------------------------------


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    """Isolated SQLite storage wired into the get_storage_service() singleton,
    same convention as test_watch_list_persistence.py — start()/stop() persist
    restart-critical state and must not touch the shared/production DB."""
    import services.storage_service as ss

    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


async def test_start_creates_watch_refresh_task(temp_storage):
    coord = ExecutionCoordinator(kiwoom_client=None)

    await coord.start()
    try:
        assert coord._watch_refresh_task is not None
        assert not coord._watch_refresh_task.done()
    finally:
        await coord.stop()


async def test_start_is_idempotent_for_watch_refresh_task(temp_storage):
    """Calling start() twice must not create a second task."""
    coord = ExecutionCoordinator(kiwoom_client=None)

    await coord.start()
    try:
        first_task = coord._watch_refresh_task
        await coord.start()
        assert coord._watch_refresh_task is first_task
    finally:
        await coord.stop()


async def test_stop_cancels_watch_refresh_task(temp_storage):
    coord = ExecutionCoordinator(kiwoom_client=None)

    await coord.start()
    task = coord._watch_refresh_task
    await coord.stop()

    assert coord._watch_refresh_task is None
    assert task.cancelled() or task.done()
