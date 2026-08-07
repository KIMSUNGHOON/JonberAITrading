from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.storage_service import get_storage_service
from services.trading.index_series import (
    INDEX_SOURCE,
    closes_to_returns,
    is_series_stale,
    refresh_index_daily,
)

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


# ---- 순수 함수 ----

def test_closes_to_returns_basic():
    got = closes_to_returns([100.0, 110.0, 99.0])
    assert got == pytest.approx([10.0, -10.0])


def test_closes_to_returns_skips_unusable_pairs():
    """0·비유한 종가가 끼면 그 쌍만 건너뛴다 — 조용히 0을 만들지 않는다."""
    got = closes_to_returns([100.0, 0.0, 110.0, 121.0])
    assert got == pytest.approx([10.0])


def test_closes_to_returns_short_input():
    assert closes_to_returns([]) == []
    assert closes_to_returns([100.0]) == []


def test_is_series_stale_boundary():
    today = date(2026, 8, 14)
    assert is_series_stale("2026-08-07", today) is False   # 7일 == 경계, 신선
    assert is_series_stale("2026-08-06", today) is True    # 8일


def test_is_series_stale_survives_long_holiday():
    """설·추석 연휴(최대 5거래일 공백)에서 오탐이 나면 안 된다."""
    assert is_series_stale("2026-02-13", date(2026, 2, 18)) is False


def test_is_series_stale_unparseable_is_stale():
    """모르는 것을 신선하다고 보면 안 된다."""
    assert is_series_stale("not-a-date", date(2026, 8, 7)) is True


# ---- 수집 ----

def _fake_history(dates_closes):
    """yfinance history() 흉내 — .index와 ["Close"]만 쓴다."""
    import pandas as pd

    idx = pd.to_datetime([d for d, _ in dates_closes])
    return pd.DataFrame({"Close": [c for _, c in dates_closes]}, index=idx)


@pytest.mark.asyncio
async def test_refresh_writes_rows_and_reports_count():
    hist = _fake_history([("2026-08-05", 6598.26), ("2026-08-06", 6296.38)])
    tk = MagicMock()
    tk.history = MagicMock(return_value=hist)
    with patch("services.trading.index_series.yf.Ticker", return_value=tk):
        n = await refresh_index_daily(lookback_days=40)
    assert n == 2

    storage = await get_storage_service()
    got = await storage.get_recent_index_closes()
    assert [d for d, _ in got] == ["2026-08-05", "2026-08-06"]


@pytest.mark.asyncio
async def test_refresh_empty_history_writes_nothing():
    tk = MagicMock()
    tk.history = MagicMock(return_value=_fake_history([]))
    with patch("services.trading.index_series.yf.Ticker", return_value=tk):
        assert await refresh_index_daily() is None

    storage = await get_storage_service()
    assert await storage.get_recent_index_closes() == []


@pytest.mark.asyncio
async def test_refresh_never_raises():
    """스케줄 잡이 직접 부른다 — 예외가 새면 잡이 죽는다."""
    with patch(
        "services.trading.index_series.yf.Ticker",
        side_effect=RuntimeError("yahoo down"),
    ):
        assert await refresh_index_daily() is None


@pytest.mark.asyncio
async def test_refresh_reports_none_when_persist_fails():
    """upsert가 실패-무해(0 반환)라 반환값을 안 보면 거짓 성공을 보고하게 된다."""
    hist = _fake_history([("2026-08-07", 6258.77)])
    tk = MagicMock()
    tk.history = MagicMock(return_value=hist)
    storage = await get_storage_service()
    with patch("services.trading.index_series.yf.Ticker", return_value=tk), patch.object(
        type(storage), "upsert_index_daily", AsyncMock(return_value=0)
    ):
        assert await refresh_index_daily() is None


@pytest.mark.asyncio
async def test_refresh_uses_the_designed_source_label():
    hist = _fake_history([("2026-08-07", 6258.77)])
    tk = MagicMock()
    tk.history = MagicMock(return_value=hist)
    storage = await get_storage_service()
    captured = {}

    # ⚠️ 클래스 메서드를 갈아끼우므로 `self`가 첫 인자로 들어온다.
    async def _spy(self, rows, source):
        captured["source"] = source
        return len(rows)

    with patch("services.trading.index_series.yf.Ticker", return_value=tk), patch.object(
        type(storage), "upsert_index_daily", _spy
    ):
        await refresh_index_daily()
    assert captured["source"] == INDEX_SOURCE
