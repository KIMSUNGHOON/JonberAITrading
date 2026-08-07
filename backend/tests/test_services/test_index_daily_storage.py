import pytest

from services.storage_service import get_storage_service

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


@pytest.mark.asyncio
async def test_upsert_and_read_roundtrip_is_oldest_first():
    storage = await get_storage_service()
    n = await storage.upsert_index_daily(
        [("2026-08-05", 6598.26), ("2026-08-06", 6296.38), ("2026-08-07", 6258.77)],
        source="yfinance:^KS11",
    )
    assert n == 3

    got = await storage.get_recent_index_closes(limit=21)
    assert [d for d, _ in got] == ["2026-08-05", "2026-08-06", "2026-08-07"], (
        "closes_to_returns가 시간 오름차순을 기대한다"
    )
    assert got[-1][1] == pytest.approx(6258.77)


@pytest.mark.asyncio
async def test_reupsert_same_date_overwrites_not_duplicates():
    """구멍 메우기의 근거 — 매 실행이 창 전체를 다시 쓴다."""
    storage = await get_storage_service()
    await storage.upsert_index_daily([("2026-08-07", 1.0)], source="a")
    await storage.upsert_index_daily([("2026-08-07", 6258.77)], source="b")

    got = await storage.get_recent_index_closes()
    assert len(got) == 1
    assert got[0][1] == pytest.approx(6258.77)


@pytest.mark.asyncio
async def test_limit_returns_the_newest_rows_still_oldest_first():
    storage = await get_storage_service()
    await storage.upsert_index_daily(
        [(f"2026-07-{d:02d}", float(d)) for d in range(1, 11)], source="s"
    )
    got = await storage.get_recent_index_closes(limit=3)
    assert [d for d, _ in got] == ["2026-07-08", "2026-07-09", "2026-07-10"]


@pytest.mark.asyncio
async def test_absent_returns_empty_list():
    storage = await get_storage_service()
    assert await storage.get_recent_index_closes() == []


@pytest.mark.asyncio
async def test_read_db_error_propagates(monkeypatch):
    """'행 없음'과 'DB 오류'를 절대 합치지 않는다. 나중에 누가
    try/except: return []를 넣으면 이 테스트가 잡는다."""
    import aiosqlite

    storage = await get_storage_service()
    await storage.upsert_index_daily([("2026-08-07", 6258.77)], source="s")

    def _boom(*a, **k):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(aiosqlite, "connect", _boom)
    with pytest.raises(RuntimeError, match="simulated DB failure"):
        await storage.get_recent_index_closes()


@pytest.mark.asyncio
async def test_upsert_failure_is_harmless_returns_zero(monkeypatch):
    import aiosqlite

    storage = await get_storage_service()
    await storage.initialize()

    def _boom(*a, **k):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(aiosqlite, "connect", _boom)
    assert await storage.upsert_index_daily([("2026-08-07", 1.0)], source="s") == 0
