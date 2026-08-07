import aiosqlite
import pytest

from services.storage_service import get_storage_service

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


async def _insert(storage, trade_date, regime, effective):
    return await storage.insert_regime_judgment(
        trade_date=trade_date,
        regime=regime,
        confidence=0.72,
        rationale="EWY -2.97%",
        key_drivers=["EWY -2.97%", "VIXY +12%"],
        anchor_target_pct=0.55,
        effective_target_pct=effective,
        prev_effective_pct=0.0855,
        degraded=["index_vol_insufficient"],
        macro_snapshot_id=None,
    )


@pytest.mark.asyncio
async def test_roundtrip_preserves_lists():
    storage = await get_storage_service()
    assert await _insert(storage, "2026-08-07", "bear", 0.2355) is True

    row = await storage.get_latest_regime_judgment()
    assert row is not None
    assert row["regime"] == "bear"
    assert row["key_drivers"] == ["EWY -2.97%", "VIXY +12%"]
    assert row["degraded"] == ["index_vol_insufficient"]
    assert row["effective_target_pct"] == pytest.approx(0.2355)
    assert row["trade_date"] == "2026-08-07"


@pytest.mark.asyncio
async def test_latest_is_by_trade_date_not_insert_order():
    """늦게 넣은 오래된 날짜가 '최신'이 되면 안 된다."""
    storage = await get_storage_service()
    await _insert(storage, "2026-08-07", "bear", 0.2355)
    await _insert(storage, "2026-08-05", "bull", 0.80)
    row = await storage.get_latest_regime_judgment()
    assert row["trade_date"] == "2026-08-07"


@pytest.mark.asyncio
async def test_absent_returns_none():
    storage = await get_storage_service()
    assert await storage.get_latest_regime_judgment() is None


@pytest.mark.asyncio
async def test_get_latest_regime_judgment_db_error_propagates(monkeypatch):
    """'행 없음'(None)과 '조회 실패'(예외)를 절대 합치지 않는다 -- DB 오류는
    삼키지 않고 그대로 raise돼야 한다. 뒤에 오는 자율매매 게이트가 이 구별에
    의존한다: 부재는 검사 스킵, 오류는 fail-closed 거절이어야 하는데, 여기서
    `try/except: return None`으로 바뀌면 게이트가 조용히 fail-open으로
    뒤집힌다. 이 테스트는 그 회귀를 잡기 위한 가드다 -- 행이 존재하는
    케이스에서 연결 자체를 실패시킨다."""
    storage = await get_storage_service()
    await _insert(storage, "2026-08-07", "bear", 0.2355)

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(aiosqlite, "connect", _boom)

    with pytest.raises(RuntimeError, match="simulated DB failure"):
        await storage.get_latest_regime_judgment()
