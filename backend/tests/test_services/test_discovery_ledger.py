"""
Discovery ledger tests (DS-3): save/get roundtrip, trading-day-accurate
forward-return backfill (including a holiday gap), and the per-strategy-
tag performance summary.

Real DB schema via tmp-path StorageService (no mocking of storage) and a
tmp-seeded KRXHolidayService (no real network -- fetcher/aiohttp never
touched).
"""

from datetime import date, timedelta

import pytest

from services.storage_service import StorageService
from services.discovery.ledger import (
    backfill_forward_returns,
    get_discovery_performance,
)
from services.krx_holiday.service import KRXHolidayService
from services.krx_holiday.fetcher import HolidayInfo


@pytest.fixture
def holiday_svc(tmp_path):
    """A KRXHolidayService backed by a tmp sqlite file, pre-seeded with one
    explicit (non-weekend) holiday: 2026-06-03 (Wednesday). Never calls
    initialize()/update_holidays(), so the network-hitting fetcher is
    never touched."""
    svc = KRXHolidayService(db_path=str(tmp_path / "holidays.db"))
    svc.storage.save_holidays([
        HolidayInfo(date=date(2026, 6, 3), day_of_week="수", name="테스트임시공휴일", year=2026),
    ])
    return svc


def _nth_trading_day_after(svc: KRXHolidayService, start: date, n: int) -> date:
    """Walk `n` trading days forward from `start` using the service's own
    get_next_trading_day -- an independent code path from
    get_trading_days_in_range (which backfill_forward_returns uses), so
    this is a genuine cross-check rather than testing the SUT against
    itself."""
    current = start
    for _ in range(n):
        current = svc.get_next_trading_day(current)
    return current


def _candidate_row(**overrides) -> dict:
    row = {
        "trade_date": "2026-06-01",
        "ticker": "005930",
        "name": "삼성전자",
        "composite_score": 0.5,
        "strategy_scores_json": {"momentum": 0.8, "pullback": 0.1, "flow": 0.1, "meanrev": 0.0},
        "regime_label": "bull",
        "rank": 1,
        "llm_verdict_json": None,
        "promoted": 0,
        "skip_reason": None,
        "close_price": 70000.0,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# 1) save/get roundtrip -- lossless
# ---------------------------------------------------------------------------


class TestSaveGetRoundtrip:
    @pytest.mark.asyncio
    async def test_roundtrip_lossless(self, tmp_path):
        import json

        st = StorageService(db_path=str(tmp_path / "storage.db"))
        row = _candidate_row(
            composite_score=0.82,
            llm_verdict_json={"verdict": "promote", "reason": "돌파"},
            promoted=1,
        )
        ok = await st.save_discovery_candidates([row])
        assert ok is True
        assert row["id"]  # uuid auto-assigned in place

        # reopen -> durable across connections
        st2 = StorageService(db_path=str(tmp_path / "storage.db"))
        got = await st2.get_discovery_candidates(trade_date="2026-06-01")
        assert len(got) == 1
        r = got[0]

        assert r["id"] == row["id"]
        assert r["trade_date"] == "2026-06-01"
        assert r["ticker"] == "005930"
        assert r["name"] == "삼성전자"
        assert r["composite_score"] == pytest.approx(0.82)
        assert json.loads(r["strategy_scores_json"]) == row["strategy_scores_json"]
        assert r["regime_label"] == "bull"
        assert r["rank"] == 1
        assert json.loads(r["llm_verdict_json"]) == row["llm_verdict_json"]
        assert r["promoted"] == 1
        assert r["skip_reason"] is None
        assert r["close_price"] == pytest.approx(70000.0)
        assert r["fwd_1d"] is None
        assert r["fwd_5d"] is None
        assert r["fwd_20d"] is None
        assert r["created_at"] is not None

        got_by_ticker = await st2.get_discovery_candidates(ticker="005930")
        assert len(got_by_ticker) == 1 and got_by_ticker[0]["id"] == row["id"]

        got_unfilled = await st2.get_discovery_candidates(unfilled_fwd_only=True)
        assert len(got_unfilled) == 1

    @pytest.mark.asyncio
    async def test_multiple_rows_batch_and_limit(self, tmp_path):
        st = StorageService(db_path=str(tmp_path / "storage.db"))
        rows = [
            _candidate_row(ticker=f"00{i}", name=f"n{i}", rank=i)
            for i in range(1, 4)
        ]
        assert await st.save_discovery_candidates(rows) is True
        assert len({r["id"] for r in rows}) == 3  # distinct uuids

        got = await st.get_discovery_candidates(trade_date="2026-06-01", limit=2)
        assert len(got) == 2

        empty = await st.save_discovery_candidates([])
        assert empty is True  # no-op, not an error


# ---------------------------------------------------------------------------
# 2) backfill_forward_returns -- exact trading-day slots (holiday gap),
#    missing-ticker skip, already-filled no-overwrite
# ---------------------------------------------------------------------------


class TestBackfillForwardReturns:
    @pytest.mark.asyncio
    async def test_fills_exact_1_5_20_slots_across_a_holiday_gap(self, tmp_path, holiday_svc):
        st = StorageService(db_path=str(tmp_path / "storage.db"))
        start = date(2026, 6, 1)
        row = _candidate_row(trade_date=start.isoformat(), close_price=70000.0)
        await st.save_discovery_candidates([row])

        day1 = _nth_trading_day_after(holiday_svc, start, 1)
        day2 = _nth_trading_day_after(holiday_svc, start, 2)
        day5 = _nth_trading_day_after(holiday_svc, start, 5)  # crosses the 6/3 holiday
        day20 = _nth_trading_day_after(holiday_svc, start, 20)

        filled = await backfill_forward_returns(
            st, {"005930": 70700.0}, day1.isoformat(), holiday_service=holiday_svc
        )
        assert filled == 1
        got = (await st.get_discovery_candidates(ticker="005930"))[0]
        assert got["fwd_1d"] == pytest.approx(0.01)
        assert got["fwd_5d"] is None
        assert got["fwd_20d"] is None

        # elapsed==2 (not an exact 1/5/20 slot) -> nothing filled
        filled = await backfill_forward_returns(
            st, {"005930": 71000.0}, day2.isoformat(), holiday_service=holiday_svc
        )
        assert filled == 0

        # elapsed==5, crossing the seeded 6/3 holiday -- proves trading-day
        # (not naive weekday) counting: a weekend-only counter would land
        # on a different calendar date for "5 trading days out" here.
        filled = await backfill_forward_returns(
            st, {"005930": 72100.0}, day5.isoformat(), holiday_service=holiday_svc
        )
        assert filled == 1
        got = (await st.get_discovery_candidates(ticker="005930"))[0]
        assert got["fwd_5d"] == pytest.approx(72100.0 / 70000.0 - 1.0)
        assert got["fwd_1d"] == pytest.approx(0.01)  # untouched by the fwd_5d fill

        filled = await backfill_forward_returns(
            st, {"005930": 75000.0}, day20.isoformat(), holiday_service=holiday_svc
        )
        assert filled == 1
        got = (await st.get_discovery_candidates(ticker="005930"))[0]
        assert got["fwd_20d"] == pytest.approx(75000.0 / 70000.0 - 1.0)

        # every slot filled -> no longer surfaced by unfilled_fwd_only
        still_unfilled = await st.get_discovery_candidates(
            ticker="005930", unfilled_fwd_only=True
        )
        assert still_unfilled == []

    @pytest.mark.asyncio
    async def test_missing_ticker_in_price_lookup_is_skipped(self, tmp_path, holiday_svc):
        st = StorageService(db_path=str(tmp_path / "storage.db"))
        start = date(2026, 6, 1)
        row = _candidate_row(
            trade_date=start.isoformat(), ticker="000660", name="SK하이닉스",
            close_price=100000.0,
        )
        await st.save_discovery_candidates([row])
        day1 = _nth_trading_day_after(holiday_svc, start, 1)

        # price_lookup has an unrelated ticker only -> 000660 must be skipped
        filled = await backfill_forward_returns(
            st, {"005930": 1.0}, day1.isoformat(), holiday_service=holiday_svc
        )
        assert filled == 0
        got = (await st.get_discovery_candidates(ticker="000660"))[0]
        assert got["fwd_1d"] is None

    @pytest.mark.asyncio
    async def test_already_filled_slot_is_never_overwritten(self, tmp_path, holiday_svc):
        st = StorageService(db_path=str(tmp_path / "storage.db"))
        start = date(2026, 6, 1)
        row = _candidate_row(trade_date=start.isoformat(), close_price=70000.0)
        await st.save_discovery_candidates([row])
        day1 = _nth_trading_day_after(holiday_svc, start, 1)

        filled = await backfill_forward_returns(
            st, {"005930": 70700.0}, day1.isoformat(), holiday_service=holiday_svc
        )
        assert filled == 1
        got = (await st.get_discovery_candidates(ticker="005930"))[0]
        assert got["fwd_1d"] == pytest.approx(0.01)

        # storage-level no-clobber: a direct update with a different value
        # for an already-filled slot must not change it.
        ok = await st.update_discovery_forward_returns(got["id"], fwd_1d=0.99)
        assert ok is True
        got2 = (await st.get_discovery_candidates(ticker="005930"))[0]
        assert got2["fwd_1d"] == pytest.approx(0.01)

        # ledger-level no-clobber: re-running backfill for the very same
        # elapsed==1 day again must not touch the already-filled slot,
        # and must not count it as filled.
        filled_again = await backfill_forward_returns(
            st, {"005930": 999.0}, day1.isoformat(), holiday_service=holiday_svc
        )
        assert filled_again == 0
        got3 = (await st.get_discovery_candidates(ticker="005930"))[0]
        assert got3["fwd_1d"] == pytest.approx(0.01)

    @pytest.mark.asyncio
    async def test_no_candidates_returns_zero(self, tmp_path, holiday_svc):
        st = StorageService(db_path=str(tmp_path / "storage.db"))
        filled = await backfill_forward_returns(
            st, {"005930": 1.0}, "2026-06-02", holiday_service=holiday_svc
        )
        assert filled == 0


# ---------------------------------------------------------------------------
# 3+4) get_discovery_performance -- strategy-tag grouping + hit rate,
#      and the empty-ledger no-raise case
# ---------------------------------------------------------------------------


class TestGetDiscoveryPerformance:
    @pytest.mark.asyncio
    async def test_empty_ledger_returns_empty_no_raise(self, tmp_path):
        st = StorageService(db_path=str(tmp_path / "storage.db"))
        summary = await get_discovery_performance(st, days=14)
        assert summary == {}

    @pytest.mark.asyncio
    async def test_groups_by_top_strategy_and_computes_hit_rate(self, tmp_path):
        st = StorageService(db_path=str(tmp_path / "storage.db"))
        d0 = (date.today() - timedelta(days=2)).isoformat()

        rows = [
            _candidate_row(  # momentum-led, promoted, hit (fwd_5d>0)
                trade_date=d0, ticker="A1", name="A1", rank=1, promoted=1,
                strategy_scores_json={"momentum": 0.9, "pullback": 0.1, "flow": 0.2, "meanrev": 0.0},
                close_price=100.0,
            ),
            _candidate_row(  # momentum-led, not promoted, miss (fwd_5d<0)
                trade_date=d0, ticker="A2", name="A2", rank=2, promoted=0,
                strategy_scores_json={"momentum": 0.7, "pullback": 0.2, "flow": 0.1, "meanrev": 0.0},
                close_price=50.0,
            ),
            _candidate_row(  # flow-led, promoted, no fwd backfilled yet
                trade_date=d0, ticker="B1", name="B1", rank=3, promoted=1,
                strategy_scores_json={"momentum": 0.1, "pullback": 0.1, "flow": 0.8, "meanrev": 0.0},
                close_price=200.0,
            ),
        ]
        await st.save_discovery_candidates(rows)

        by_ticker = {r["ticker"]: r["id"] for r in rows}
        await st.update_discovery_forward_returns(by_ticker["A1"], fwd_1d=0.01, fwd_5d=0.05)
        await st.update_discovery_forward_returns(by_ticker["A2"], fwd_1d=-0.02, fwd_5d=-0.03)
        # B1 stays fully unfilled

        summary = await get_discovery_performance(st, days=14)

        assert set(summary.keys()) == {"momentum", "flow"}

        mom = summary["momentum"]
        assert mom["candidates"] == 2
        assert mom["promoted"] == 1
        assert mom["avg_fwd_1d"] == pytest.approx((0.01 + -0.02) / 2)
        assert mom["avg_fwd_5d"] == pytest.approx((0.05 + -0.03) / 2)
        assert mom["hit_rate_5d"] == pytest.approx(0.5)  # 1 of 2 has fwd_5d>0

        flow = summary["flow"]
        assert flow["candidates"] == 1
        assert flow["promoted"] == 1
        assert flow["avg_fwd_1d"] is None
        assert flow["avg_fwd_5d"] is None
        assert flow["hit_rate_5d"] is None

    @pytest.mark.asyncio
    async def test_candidates_outside_window_are_excluded(self, tmp_path):
        st = StorageService(db_path=str(tmp_path / "storage.db"))
        old_date = (date.today() - timedelta(days=30)).isoformat()
        row = _candidate_row(trade_date=old_date, ticker="OLD", name="OLD")
        await st.save_discovery_candidates([row])

        summary = await get_discovery_performance(st, days=14)
        assert summary == {}

    @pytest.mark.asyncio
    async def test_malformed_strategy_scores_json_falls_back_to_unknown(self, tmp_path):
        st = StorageService(db_path=str(tmp_path / "storage.db"))
        d0 = (date.today() - timedelta(days=1)).isoformat()
        row = _candidate_row(
            trade_date=d0, ticker="BAD", name="BAD", strategy_scores_json="not json",
        )
        await st.save_discovery_candidates([row])

        summary = await get_discovery_performance(st, days=14)
        assert "unknown" in summary
        assert summary["unknown"]["candidates"] == 1
