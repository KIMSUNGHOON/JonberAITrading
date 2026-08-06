"""Task 5 (Phase1 C3b): EOD daily performance snapshot + market-close trigger.

Equity/realized-P&L/win-rate were only ever recomputed live from
ka10074+kt00004, which have a rolling broker query window — once a day
scrolls out of that window its performance numbers are gone for good. This
covers `write_daily_snapshot`: it reads the day's realized P&L (ka10074) +
account equity (kt00004) off the coordinator's kiwoom client, counts
win/loss trades from the `kr_realized_pnl` ledger (Phase1 C3a), and persists
one row per trade_date into `daily_perf_snapshot` (INSERT OR IGNORE, so a
second write for the same day is a silent no-op). Failure-harmless — any
data-fetch exception must be swallowed and reported as `False`, never raised
(this runs off the market-close scheduler edge and must never break the
tick).
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from services.kiwoom.models import (
    AccountBalance,
    DailyRealizedPnlRow,
    Holding,
    RealizedPnl,
)
from services.storage_service import StorageService
from services.trading.eod_snapshot import _BACKFILL_STK_CD_SENTINEL, write_daily_snapshot

pytestmark = pytest.mark.asyncio


class _StubClient:
    """Stand-in for the Kiwoom client the coordinator holds as `._kiwoom`."""

    def __init__(self, pnl: RealizedPnl, balance: AccountBalance):
        self.get_realized_pnl = AsyncMock(return_value=pnl)
        self.get_account_balance = AsyncMock(return_value=balance)


class _StubCoordinator:
    """Minimal stand-in for ExecutionCoordinator — only `._kiwoom` is read."""

    def __init__(self, kiwoom):
        self._kiwoom = kiwoom


def _pnl(realized=50000, commission=500, tax=284, dt="20260715") -> RealizedPnl:
    return RealizedPnl(
        strt_dt=dt,
        end_dt=dt,
        total_buy_amount=1_000_000,
        total_sell_amount=1_050_000,
        realized_pnl=realized,
        commission=commission,
        tax=tax,
        daily=[
            DailyRealizedPnlRow(
                dt=dt,
                buy_amount=1_000_000,
                sell_amount=1_050_000,
                sell_pnl=realized,
                commission=commission,
                tax=tax,
            )
        ],
    )


def _balance(evlu_amt=500_500_000, d2=10_000_000, holdings=None) -> AccountBalance:
    return AccountBalance(
        pchs_amt=490_000_000,
        evlu_amt=evlu_amt,
        evlu_pfls_amt=evlu_amt - 490_000_000,
        evlu_pfls_rt=1.0,
        d2_ord_psbl_amt=d2,
        holdings=holdings if holdings is not None else [],
    )


async def _seed_kr_realized_pnl(storage: StorageService, trade_date: str) -> None:
    """One winning and one losing matched-close row stamped on trade_date."""
    await storage.save_kr_realized_pnl(
        {
            "id": str(uuid.uuid4()),
            "stk_cd": "005930",
            "entry_price": 70000,
            "exit_price": 72000,
            "quantity": 10,
            "realized_amount": 20000.0,
            "created_at": f"{trade_date} 10:00:00",
        }
    )
    await storage.save_kr_realized_pnl(
        {
            "id": str(uuid.uuid4()),
            "stk_cd": "000660",
            "entry_price": 100000,
            "exit_price": 95000,
            "quantity": 5,
            "realized_amount": -25000.0,
            "created_at": f"{trade_date} 11:00:00",
        }
    )
    # A row from a DIFFERENT day must not be counted.
    await storage.save_kr_realized_pnl(
        {
            "id": str(uuid.uuid4()),
            "stk_cd": "035420",
            "entry_price": 200000,
            "exit_price": 210000,
            "quantity": 1,
            "realized_amount": 10000.0,
            "created_at": "2020-01-01 09:00:00",
        }
    )


async def test_write_daily_snapshot_writes_one_row(tmp_path):
    trade_date = "2026-07-15"
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    await _seed_kr_realized_pnl(storage, trade_date)

    coordinator = _StubCoordinator(_StubClient(_pnl(), _balance()))

    ok = await write_daily_snapshot(coordinator, storage, trade_date)
    assert ok is True

    rows = await storage.get_daily_perf_snapshots()
    assert len(rows) == 1
    row = rows[0]
    assert row["trade_date"] == trade_date
    assert row["equity"] == 510_500_000  # evlu_amt + d2_ord_psbl_amt
    assert row["realized_pnl"] == 50000
    assert row["net_pnl"] == 50000
    assert row["commission"] == 500
    assert row["tax"] == 284
    assert row["win_trades"] == 1
    assert row["loss_trades"] == 1
    assert row["cumulative_return_pct"] is not None
    assert row["regime_snapshot_id"] is None


async def test_write_daily_snapshot_persists_nonnull_stock_value(tmp_path):
    """stock_value는 Task 3에서 컬럼만 추가되고 아무도 쓰지 않아 한 달 뒤
    전량 NULL이 될 판이었다(리뷰 반영, 2026-08-06) -- 이 테스트는 실제로
    보유종목 평가금액 합계가 저장되는지 잠근다."""
    trade_date = "2026-07-15"
    storage = StorageService(db_path=str(tmp_path / "t.db"))

    holdings = [
        Holding(
            stk_cd="005930", stk_nm="삼성전자", hldg_qty=10,
            avg_buy_prc=70000, cur_prc=72000, evlu_amt=720_000,
            evlu_pfls_amt=20000, evlu_pfls_rt=2.86,
        ),
        Holding(
            stk_cd="000660", stk_nm="SK하이닉스", hldg_qty=5,
            avg_buy_prc=100000, cur_prc=95000, evlu_amt=475_000,
            evlu_pfls_amt=-25000, evlu_pfls_rt=-5.0,
        ),
    ]
    coordinator = _StubCoordinator(
        _StubClient(_pnl(), _balance(holdings=holdings))
    )

    ok = await write_daily_snapshot(coordinator, storage, trade_date)
    assert ok is True

    rows = await storage.get_daily_perf_snapshots()
    assert len(rows) == 1
    assert rows[0]["stock_value"] is not None
    assert rows[0]["stock_value"] == pytest.approx(1_195_000)


async def test_write_daily_snapshot_second_call_same_date_is_noop(tmp_path):
    trade_date = "2026-07-15"
    storage = StorageService(db_path=str(tmp_path / "t.db"))

    coordinator1 = _StubCoordinator(
        _StubClient(_pnl(realized=1000, commission=10, tax=5), _balance())
    )
    assert await write_daily_snapshot(coordinator1, storage, trade_date) is True

    # Second call, same trade_date, with DIFFERENT underlying numbers — must
    # not create a duplicate row or overwrite the first (INSERT OR IGNORE).
    coordinator2 = _StubCoordinator(
        _StubClient(
            _pnl(realized=99999, commission=1, tax=1),
            _balance(evlu_amt=999_999_999),
        )
    )
    assert await write_daily_snapshot(coordinator2, storage, trade_date) is True

    rows = await storage.get_daily_perf_snapshots()
    assert len(rows) == 1
    assert rows[0]["realized_pnl"] == 1000


async def test_write_daily_snapshot_returns_false_when_fetch_raises(tmp_path):
    trade_date = "2026-07-15"
    storage = StorageService(db_path=str(tmp_path / "t.db"))

    client = _StubClient(_pnl(), _balance())
    client.get_realized_pnl = AsyncMock(side_effect=RuntimeError("kiwoom boom"))
    coordinator = _StubCoordinator(client)

    ok = await write_daily_snapshot(coordinator, storage, trade_date)
    assert ok is False

    rows = await storage.get_daily_perf_snapshots()
    assert len(rows) == 0


async def test_write_daily_snapshot_returns_false_when_coordinator_has_no_client(tmp_path):
    trade_date = "2026-07-15"
    storage = StorageService(db_path=str(tmp_path / "t.db"))

    class _NoClientCoordinator:
        _kiwoom = None

    ok = await write_daily_snapshot(_NoClientCoordinator(), storage, trade_date)
    assert ok is False


async def test_write_daily_snapshot_ignores_backfill_all_sentinel_in_win_loss_count(
    tmp_path,
):
    """E1-6 리뷰픽스 (Critical): scripts/backfill_realized_pnl.py writes
    account-wide aggregate rows with stk_cd="ALL" (ka10074 has no per-stock
    breakdown) into kr_realized_pnl for historical dates. Such a row is NOT
    a matched-close trade (no entry/exit price/quantity at all) and must
    never be counted as an extra win or loss here — otherwise an operator
    backfilling the past would silently skew every future day's win/loss
    ratio the moment that data enters the scan window.
    """
    trade_date = "2026-07-15"
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    await _seed_kr_realized_pnl(storage, trade_date)  # baseline: 1 win, 1 loss

    # A backfill aggregate row for the SAME trade_date, with a realized
    # amount that would flip the count (positive → would count as an extra
    # win) if the sentinel filter were missing.
    await storage.save_kr_realized_pnl(
        {
            "id": "backfill-20260715",
            "stk_cd": _BACKFILL_STK_CD_SENTINEL,
            "realized_amount": 999999.0,
            "created_at": f"{trade_date} 00:00:00",
        }
    )

    coordinator = _StubCoordinator(_StubClient(_pnl(), _balance()))
    ok = await write_daily_snapshot(coordinator, storage, trade_date)
    assert ok is True

    rows = await storage.get_daily_perf_snapshots()
    assert len(rows) == 1
    # Unchanged from the plain baseline (test_write_daily_snapshot_writes_
    # one_row) — the "ALL" row must not have been counted as a win.
    assert rows[0]["win_trades"] == 1
    assert rows[0]["loss_trades"] == 1
