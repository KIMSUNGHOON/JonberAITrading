"""P2 funnel-consolidation prep (2026-07-14): server Watchlist durability.

Root causes (verified in services/trading/coordinator.py):
- R5-P1 (A4) persisted `positions`/`trade_queue`/`daily_trades_count` into the
  app_settings JSON blob and restored them on start, but `watch_list` was never
  added to that blob — a restart silently dropped every watched stock.
- `_reprice_positions` (DI2) repriced open positions' `current_price` from the
  live quote feed but never touched watch-list entries — a WATCH item kept its
  registration-time price forever, so the 5-min opportunity check
  (`ChatCoordinator._detect_opportunity`'s target-price proximity) judged
  against a stale price.

These tests mirror the A4 persist/restore round-trip conventions in
test_r5_p1_execution_reliability.py and the T2 stale-price-contract
conventions in test_position_reprice.py, applied to the watch list.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.kiwoom.models import AccountBalance, StockBasicInfo
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import WatchStatus

pytestmark = pytest.mark.asyncio


def _stock_info(cur_prc, stk_cd: str = "005930") -> StockBasicInfo:
    return StockBasicInfo(stk_cd=stk_cd, stk_nm="삼성전자", cur_prc=cur_prc)


def _balance() -> AccountBalance:
    return AccountBalance(
        pchs_amt=0,
        evlu_amt=0,
        evlu_pfls_amt=0,
        evlu_pfls_rt=0.0,
        d2_ord_psbl_amt=1_000_000,
        holdings=[],
    )


# -------------------------------------------
# Persist / restore round-trip (mirrors A4 positions/queue tests)
# -------------------------------------------


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    """Isolated SQLite storage wired into the get_storage_service() singleton."""
    import services.storage_service as ss

    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


async def test_persist_restore_round_trips_watch_list(temp_storage):
    """A watch-list entry added before a restart must still be there afterward —
    same contract as positions/trade_queue (R5-P1 A4)."""
    coord1 = ExecutionCoordinator(kiwoom_client=None)
    watched = coord1.add_to_watch_list(
        session_id="s-watch",
        ticker="005930",
        stock_name="삼성전자",
        signal="hold",
        confidence=0.6,
        current_price=71_000,
        target_entry_price=70_000,
        stop_loss=68_000,
        take_profit=79_000,
        analysis_summary="관망 추천",
        risk_score=6,
    )
    await coord1._persist_state()

    coord2 = ExecutionCoordinator(kiwoom_client=None)
    assert coord2.get_watch_list() == []
    await coord2._restore_state()

    restored_list = coord2.get_watch_list()
    assert len(restored_list) == 1
    restored = restored_list[0]
    assert restored.id == watched.id
    assert restored.ticker == "005930"
    assert restored.status == WatchStatus.ACTIVE
    assert restored.target_entry_price == 70_000
    assert restored.stop_loss == 68_000
    assert restored.risk_score == 6


async def test_persist_restore_preserves_converted_status(temp_storage):
    """A CONVERTED (or REMOVED) entry must round-trip with its terminal status —
    get_watch_list() only returns ACTIVE, so this pins the raw restore, not just
    the filtered view."""
    coord1 = ExecutionCoordinator(kiwoom_client=None)
    watched = coord1.add_to_watch_list(
        session_id="s-watch",
        ticker="005930",
        stock_name="삼성전자",
        signal="hold",
        confidence=0.6,
        current_price=71_000,
    )
    coord1.mark_watch_converted("005930")
    await coord1._persist_state()

    coord2 = ExecutionCoordinator(kiwoom_client=None)
    await coord2._restore_state()

    assert coord2.get_watch_list() == []
    all_restored = coord2._state.watch_list
    assert len(all_restored) == 1
    assert all_restored[0].id == watched.id
    assert all_restored[0].status == WatchStatus.CONVERTED


async def test_restore_noop_when_nothing_persisted_watch_list(temp_storage):
    """A first run (empty storage) restores cleanly to an empty watch list."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    await coord._restore_state()
    assert coord._state.watch_list == []


async def test_stop_persists_watch_list(temp_storage):
    """A graceful stop() persists the watch list so the next start() restores it
    — same lifecycle contract as positions (A4)."""
    coord1 = ExecutionCoordinator(kiwoom_client=None)
    await coord1.start()
    coord1.add_to_watch_list(
        session_id="s-watch",
        ticker="005930",
        stock_name="삼성전자",
        signal="hold",
        confidence=0.6,
        current_price=71_000,
    )
    await coord1.stop()

    coord2 = ExecutionCoordinator(kiwoom_client=None)
    await coord2._restore_state()
    assert len(coord2.get_watch_list()) == 1


# -------------------------------------------
# Reprice — watch-list entries follow the T2 stale-price contract too
# -------------------------------------------


async def test_reprice_updates_watch_list_current_price():
    """A live quote must update a watched stock's current_price, not just open
    positions' — otherwise the 5-min opportunity check judges target-price
    proximity against a stale, registration-time price."""
    client = MagicMock()
    client.get_account_balance = AsyncMock(return_value=_balance())
    client.get_stock_info = AsyncMock(return_value=_stock_info(75_000))
    coord = ExecutionCoordinator(kiwoom_client=client)
    coord.add_to_watch_list(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        signal="hold",
        confidence=0.6,
        current_price=71_000,
    )

    await coord._refresh_account_info()

    watched = coord.get_watch_list()[0]
    assert watched.current_price == 75_000


async def test_reprice_skips_watch_list_on_failed_quote():
    """T2 stale-price contract: a failed quote (fails safe to 0) must NOT
    overwrite a watch item's last-known current_price."""
    client = MagicMock()
    client.get_account_balance = AsyncMock(return_value=_balance())
    client.get_stock_info = AsyncMock(side_effect=RuntimeError("kiwoom down"))
    coord = ExecutionCoordinator(kiwoom_client=client)
    coord.add_to_watch_list(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        signal="hold",
        confidence=0.6,
        current_price=71_000,
    )

    await coord._refresh_account_info()

    watched = coord.get_watch_list()[0]
    assert watched.current_price == 71_000


async def test_reprice_skips_watch_list_when_quote_is_zero():
    """Belt-and-suspenders: an explicit 0 quote is also treated as 'no fresh
    data' for watch-list entries."""
    client = MagicMock()
    client.get_account_balance = AsyncMock(return_value=_balance())
    client.get_stock_info = AsyncMock(return_value=_stock_info(0))
    coord = ExecutionCoordinator(kiwoom_client=client)
    coord.add_to_watch_list(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        signal="hold",
        confidence=0.6,
        current_price=71_000,
    )

    await coord._refresh_account_info()

    watched = coord.get_watch_list()[0]
    assert watched.current_price == 71_000


async def test_reprice_does_not_touch_non_active_watch_entries():
    """A CONVERTED/REMOVED entry's price is historical, not live — repricing it
    would be misleading (and wasteful, extra quote calls for dead entries)."""
    client = MagicMock()
    client.get_account_balance = AsyncMock(return_value=_balance())
    client.get_stock_info = AsyncMock(return_value=_stock_info(75_000))
    coord = ExecutionCoordinator(kiwoom_client=client)
    coord.add_to_watch_list(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        signal="hold",
        confidence=0.6,
        current_price=71_000,
    )
    coord.mark_watch_converted("005930")

    await coord._refresh_account_info()

    converted = coord._state.watch_list[0]
    assert converted.current_price == 71_000
