from unittest.mock import AsyncMock, patch

import pytest

from services.storage_service import get_storage_service
from services.trading.macro_snapshot import MACRO_TICKERS, refresh_macro_snapshot

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


def test_ticker_list_is_exactly_the_designed_basket():
    assert MACRO_TICKERS == ["EWY", "SPY", "QQQ", "VIXY", "TLT", "UUP", "USO", "GLD"]


@pytest.mark.asyncio
async def test_partial_failure_records_what_is_missing():
    """받은 것만 저장하고 못 받은 티커를 남긴다. 0으로 채우지 않는다."""
    partial = {"SPY": {"chg_pct": -0.16, "prev_close": 769.8}}
    with patch(
        "services.trading.macro_snapshot.fetch_us_ai_overnight",
        AsyncMock(return_value=partial),
    ):
        out = await refresh_macro_snapshot()

    assert out is not None
    assert out["quotes"] == partial
    assert set(out["missing"]) == set(MACRO_TICKERS) - {"SPY"}

    storage = await get_storage_service()
    from datetime import date
    row = await storage.get_macro_snapshot(date.today().isoformat())
    assert row is not None
    assert "EWY" in row["missing"]
    assert "SPY" not in row["missing"]


@pytest.mark.asyncio
async def test_total_failure_writes_no_row():
    """8종 전부 실패하면 행을 만들지 않는다 — 빈 행은 진짜 데이터와
    구별되지 않는다."""
    with patch(
        "services.trading.macro_snapshot.fetch_us_ai_overnight",
        AsyncMock(return_value=None),
    ):
        assert await refresh_macro_snapshot() is None

    storage = await get_storage_service()
    from datetime import date
    assert await storage.get_macro_snapshot(date.today().isoformat()) is None


@pytest.mark.asyncio
async def test_fetch_exception_does_not_propagate():
    """never-raise: 수집 실패가 스케줄러를 죽이면 안 된다."""
    with patch(
        "services.trading.macro_snapshot.fetch_us_ai_overnight",
        AsyncMock(side_effect=RuntimeError("finnhub down")),
    ):
        assert await refresh_macro_snapshot() is None
