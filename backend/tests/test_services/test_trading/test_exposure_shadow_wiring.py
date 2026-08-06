"""exposure_shadow 기록 경로 (관측 단계, 2026-08-06).

⚠️ storage를 건드리는 테스트는 반드시 isolated_storage_service를 쓴다.
opt-in 격리 없는 테스트가 라이브 storage.db를 덮어써 코디네이터 상태를
훼손한 사고가 실제로 있었다.
"""
import pytest

from services.trading.exposure_target import compute_target_exposure


@pytest.mark.asyncio
async def test_insert_and_read_round_trip(isolated_storage_service):
    result = compute_target_exposure(
        equity=497_403_042.0,
        stock_value=49_426_800.0,
        index_returns=[],
        regime_label="neutral",
        n_round_trips=8,
        equity_peak=497_403_042.0,
    )

    ok = await isolated_storage_service.insert_exposure_shadow(
        trade_date="2026-08-06",
        target=result,
        equity=497_403_042.0,
        stock_value=49_426_800.0,
        actual_pct=49_426_800.0 / 497_403_042.0,
        n_round_trips=8,
    )
    assert ok is True

    rows = await isolated_storage_service.get_exposure_shadow("2026-08-06")
    assert len(rows) == 1
    row = rows[0]
    assert row["target_pct"] == pytest.approx(0.10)
    assert row["actual_pct"] == pytest.approx(0.0994, abs=1e-3)
    assert row["binding"] == "m_evidence"
    assert row["m_evidence"] == pytest.approx(0.20)


@pytest.mark.asyncio
async def test_degraded_reasons_are_persisted(isolated_storage_service):
    """중립 처리 사유가 사라지면 나중에 판정이 불가능하다."""
    result = compute_target_exposure(
        equity=497_403_042.0,
        stock_value=49_426_800.0,
        index_returns=[-10.84, 17.91, -5.12, 1.62, 3.76, -6.36, -4.46],
        regime_label="neutral",
        n_round_trips=8,
        equity_peak=497_403_042.0,
    )
    assert "index_vol_implausible" in result.degraded

    await isolated_storage_service.insert_exposure_shadow(
        trade_date="2026-08-06",
        target=result,
        equity=497_403_042.0,
        stock_value=49_426_800.0,
        actual_pct=0.0994,
        n_round_trips=8,
    )
    row = (await isolated_storage_service.get_exposure_shadow("2026-08-06"))[0]
    assert "index_vol_implausible" in row["degraded"]
    assert row["index_vol_annualized"] > 60.0
    assert row["index_vol_n"] == 7


@pytest.mark.asyncio
async def test_empty_degraded_list_round_trips_as_empty_string_not_null(
    isolated_storage_service,
):
    """빈 리스트는 빈 문자열로 남아야 한다 -- NULL("기록 안 됨")과 구별되는
    "저하 없음"이라는 판정이다. 모든 성분이 정상 신호를 가져야 degraded가
    비므로, 위생 게이트를 통과하는 변동성 표본(연율 약 18%, 5~60% 게이트
    안)과 알려진 regime_label을 함께 준다."""
    result = compute_target_exposure(
        equity=497_403_042.0,
        stock_value=49_426_800.0,
        index_returns=[1.14, -1.14] * 10,
        regime_label="neutral",
        n_round_trips=8,
        equity_peak=497_403_042.0,
    )
    assert result.degraded == []

    await isolated_storage_service.insert_exposure_shadow(
        trade_date="2026-08-06",
        target=result,
        equity=497_403_042.0,
        stock_value=49_426_800.0,
        actual_pct=0.0994,
        n_round_trips=8,
    )
    row = (await isolated_storage_service.get_exposure_shadow("2026-08-06"))[0]
    assert row["degraded"] == ""
    assert row["degraded"] is not None


@pytest.mark.asyncio
async def test_daily_perf_snapshot_has_stock_value_column(isolated_storage_service):
    """슬리브 변동성으로 갈아타기 위한 재료를 지금부터 쌓는다."""
    import aiosqlite

    async with aiosqlite.connect(str(isolated_storage_service.db_path)) as conn:
        cursor = await conn.execute("PRAGMA table_info(daily_perf_snapshot)")
        cols = {row[1] for row in await cursor.fetchall()}
    assert "stock_value" in cols


from unittest.mock import AsyncMock, MagicMock, patch


def _coord_for_shadow():
    """_record_exposure_shadow만 실행 가능한 최소 coordinator."""
    from services.trading.coordinator import ExecutionCoordinator
    from services.trading.models import AccountInfo

    c = ExecutionCoordinator.__new__(ExecutionCoordinator)
    c._state = MagicMock()
    c._state.account = AccountInfo(
        total_equity=497_403_042.0, available_cash=449_360_601.0
    )
    c._state.positions = []
    return c


class TestExposureShadowRecording:
    @pytest.mark.asyncio
    async def test_skips_when_market_closed(self):
        """장외에는 행을 쓰지 않는다 — 기존 감시 루프의 idle 규약과 동일."""
        coord = _coord_for_shadow()
        storage = MagicMock()
        storage.insert_exposure_shadow = AsyncMock(return_value=True)

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=False), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(return_value=storage)):
            await coord._record_exposure_shadow()

        storage.insert_exposure_shadow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_when_equity_is_zero(self):
        """0으로 채운 행은 나중에 진짜 0과 구분되지 않는다."""
        from services.trading.models import AccountInfo

        coord = _coord_for_shadow()
        coord._state.account = AccountInfo(total_equity=0.0, available_cash=0.0)
        storage = MagicMock()
        storage.insert_exposure_shadow = AsyncMock(return_value=True)

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=True), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(return_value=storage)):
            await coord._record_exposure_shadow()

        storage.insert_exposure_shadow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_records_a_row_during_market_hours(self):
        coord = _coord_for_shadow()
        storage = MagicMock()
        storage.insert_exposure_shadow = AsyncMock(return_value=True)
        storage.get_recent_index_returns = AsyncMock(return_value=[])
        storage.get_latest_regime_label = AsyncMock(return_value="neutral")
        storage.count_round_trips = AsyncMock(return_value=8)
        storage.get_equity_peak = AsyncMock(return_value=497_403_042.0)

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=True), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(return_value=storage)):
            await coord._record_exposure_shadow()

        storage.insert_exposure_shadow.assert_awaited_once()
        kwargs = storage.insert_exposure_shadow.await_args.kwargs
        assert kwargs["target"].target_pct == pytest.approx(0.10)
        assert kwargs["n_round_trips"] == 8

    @pytest.mark.asyncio
    async def test_storage_failure_never_propagates(self):
        """관측 실패가 코디네이터 루프를 죽이면 본말전도다."""
        coord = _coord_for_shadow()

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=True), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(side_effect=RuntimeError("db down"))):
            await coord._record_exposure_shadow()   # raise 하면 실패
