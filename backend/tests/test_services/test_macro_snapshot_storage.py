import aiosqlite
import pytest

from services.storage_service import get_storage_service

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


@pytest.mark.asyncio
async def test_insert_and_get_roundtrip():
    storage = await get_storage_service()
    ok = await storage.insert_macro_snapshot(
        trade_date="2026-08-07",
        quotes={"SPY": {"chg_pct": -0.16, "prev_close": 769.8}},
        missing=["USO"],
    )
    assert ok is True

    row = await storage.get_macro_snapshot("2026-08-07")
    assert row is not None
    assert row["quotes"]["SPY"]["chg_pct"] == pytest.approx(-0.16)
    assert row["missing"] == ["USO"]


@pytest.mark.asyncio
async def test_get_absent_row_returns_none_not_error():
    """행 없음은 None이다. 조회 실패와 절대 합치지 않는다."""
    storage = await get_storage_service()
    assert await storage.get_macro_snapshot("1999-01-01") is None


@pytest.mark.asyncio
async def test_recent_returns_are_oldest_first():
    storage = await get_storage_service()
    for d, v in [("2026-08-05", 1.0), ("2026-08-06", 2.0), ("2026-08-07", 3.0)]:
        await storage.insert_macro_snapshot(
            trade_date=d, quotes={"SPY": {"chg_pct": v, "prev_close": 100.0}}, missing=[]
        )
    got = await storage.get_recent_macro_returns("SPY", limit=20)
    assert got == [1.0, 2.0, 3.0], "annualized_vol은 시간 오름차순을 기대한다"


@pytest.mark.asyncio
async def test_recent_returns_skips_snapshots_missing_that_ticker():
    storage = await get_storage_service()
    await storage.insert_macro_snapshot(
        trade_date="2026-08-05", quotes={"SPY": {"chg_pct": 1.0, "prev_close": 100.0}}, missing=[]
    )
    await storage.insert_macro_snapshot(
        trade_date="2026-08-06", quotes={"EWY": {"chg_pct": 9.0, "prev_close": 160.0}}, missing=["SPY"]
    )
    assert await storage.get_recent_macro_returns("SPY") == [1.0]


@pytest.mark.asyncio
async def test_recent_returns_empty_when_no_rows():
    storage = await get_storage_service()
    assert await storage.get_recent_macro_returns("SPY") == []


@pytest.mark.asyncio
async def test_get_macro_snapshot_db_error_propagates(monkeypatch):
    """'행 없음'(None)과 '조회 실패'(예외)를 절대 합치지 않는다 -- DB 오류는
    삼키지 않고 그대로 raise돼야 한다(2026-08-06 /exposure 사고 재발 방지).
    이 테스트는 구현이 `try/except: return None`으로 바뀌는 회귀를 잡기
    위한 가드다 -- 행이 존재하는 케이스에서 연결 자체를 실패시킨다."""
    storage = await get_storage_service()
    await storage.insert_macro_snapshot(
        trade_date="2026-08-07",
        quotes={"SPY": {"chg_pct": 1.0, "prev_close": 100.0}},
        missing=[],
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(aiosqlite, "connect", _boom)

    with pytest.raises(RuntimeError, match="simulated DB failure"):
        await storage.get_macro_snapshot("2026-08-07")


@pytest.mark.asyncio
async def test_get_recent_macro_returns_db_error_propagates(monkeypatch):
    """get_recent_macro_returns도 동일한 계약이다 -- DB 오류는 raise한다.
    가드가 없으면 `annualized_vol`이 '데이터 없음'과 '조회 실패'를 구별
    못 해 레짐 게이트가 조용히 fail-open으로 뒤집힐 수 있다."""
    storage = await get_storage_service()
    await storage.insert_macro_snapshot(
        trade_date="2026-08-07",
        quotes={"SPY": {"chg_pct": 1.0, "prev_close": 100.0}},
        missing=[],
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(aiosqlite, "connect", _boom)

    with pytest.raises(RuntimeError, match="simulated DB failure"):
        await storage.get_recent_macro_returns("SPY")
