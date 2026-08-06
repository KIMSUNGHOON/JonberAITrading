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


class TestExposureReadHelpersFailClosed:
    """세 조회 헬퍼(get_latest_regime_label/count_round_trips/
    get_equity_peak)는 조회 자체가 실패하면 그럴싸한 기본값("neutral"/0/
    0.0)이 아니라 None을 돌려줘야 한다 -- 실패와 진짜 값을 코디네이터가
    구분할 수 있어야 하기 때문이다(_record_exposure_shadow의
    degraded 태깅이 이 None에 의존한다)."""

    @pytest.mark.asyncio
    async def test_get_latest_regime_label_returns_none_when_table_empty(
        self, isolated_storage_service
    ):
        """레짐 기록이 아직 없는 것과 진짜 'neutral' 레짐은 다른 사실이다."""
        assert await isolated_storage_service.get_latest_regime_label() is None

    @pytest.mark.asyncio
    async def test_get_latest_regime_label_returns_none_on_read_failure(
        self, isolated_storage_service, monkeypatch
    ):
        import services.storage_service as ss

        async def _boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(ss.aiosqlite, "connect", _boom)
        assert await isolated_storage_service.get_latest_regime_label() is None

    @pytest.mark.asyncio
    async def test_count_round_trips_returns_none_on_read_failure(
        self, isolated_storage_service, monkeypatch
    ):
        import services.storage_service as ss

        async def _boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(ss.aiosqlite, "connect", _boom)
        assert await isolated_storage_service.count_round_trips() is None

    @pytest.mark.asyncio
    async def test_get_equity_peak_returns_none_on_read_failure(
        self, isolated_storage_service, monkeypatch
    ):
        import services.storage_service as ss

        async def _boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(ss.aiosqlite, "connect", _boom)
        assert await isolated_storage_service.get_equity_peak() is None


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
        """장외에는 행을 쓰지 않는다 — 기존 감시 루프의 idle 규약과 동일.

        storage는 test_records_a_row_during_market_hours와 동일하게 4개
        조회 헬퍼를 전부 채운 완전한 더블을 쓴다 -- 그래야 이 게이트가
        지워졌을 때 실제로 이 테스트가 실패한다. (리뷰 발견: 이전 버전은
        빈 MagicMock을 썼는데, 게이트가 지워지면
        `await storage.get_recent_index_returns(...)`가 awaitable이 아닌
        MagicMock을 await하려다 TypeError를 내고 그게 바깥 except에
        먹혀서 insert_exposure_shadow가 여전히 호출 안 된 것처럼 보였다 --
        즉 게이트 없이도 이 assert가 통과했다.)
        """
        coord = _coord_for_shadow()
        storage = MagicMock()
        storage.insert_exposure_shadow = AsyncMock(return_value=True)
        storage.get_recent_index_returns = AsyncMock(return_value=[])
        storage.get_latest_regime_label = AsyncMock(return_value="neutral")
        storage.count_round_trips = AsyncMock(return_value=8)
        storage.get_equity_peak = AsyncMock(return_value=497_403_042.0)

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=False), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(return_value=storage)):
            await coord._record_exposure_shadow()

        storage.get_recent_index_returns.assert_not_awaited()
        storage.insert_exposure_shadow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_when_equity_is_zero(self):
        """0으로 채운 행은 나중에 진짜 0과 구분되지 않는다.

        storage는 완전한 더블을 쓴다 -- 그래야 이 게이트가 지워졌을 때
        `stock_value / equity`의 ZeroDivisionError가 바깥 except에 먹혀
        거짓 통과하는 일이 없다(위 test_skips_when_market_closed과 같은
        리뷰 발견의 두 번째 사례).
        """
        from services.trading.models import AccountInfo

        coord = _coord_for_shadow()
        coord._state.account = AccountInfo(total_equity=0.0, available_cash=0.0)
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

        storage.get_recent_index_returns.assert_not_awaited()
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

    @pytest.mark.asyncio
    async def test_regime_read_failure_is_recorded_as_degraded(self):
        """get_latest_regime_label이 실패해서 None을 돌려줘도 행은 쓴다 --
        'neutral'로 조용히 뭉개면 진짜 neutral 레짐과 조회 실패를 나중에
        구분할 수 없다. m_regime 자체는 중립값(1.0)으로 계산하되
        degraded에 원인을 남긴다."""
        coord = _coord_for_shadow()
        storage = MagicMock()
        storage.insert_exposure_shadow = AsyncMock(return_value=True)
        storage.get_recent_index_returns = AsyncMock(return_value=[])
        storage.get_latest_regime_label = AsyncMock(return_value=None)
        storage.count_round_trips = AsyncMock(return_value=8)
        storage.get_equity_peak = AsyncMock(return_value=497_403_042.0)

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=True), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(return_value=storage)):
            await coord._record_exposure_shadow()

        storage.insert_exposure_shadow.assert_awaited_once()
        kwargs = storage.insert_exposure_shadow.await_args.kwargs
        assert "regime_read_failed" in kwargs["target"].degraded
        assert kwargs["target"].m_regime == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_round_trips_read_failure_is_recorded_as_degraded(self):
        """count_round_trips이 실패해서 None을 돌려줘도 행은 쓴다 -- 0으로
        뭉개면 m_evidence가 바닥(EXPOSURE_FLOOR 클램프)으로 떨어져 '증거가
        얇다'는 진짜 신호와 '조회가 실패했다'가 똑같이 보인다. 대신
        EVIDENCE_TARGET_TRIPS(annualized_vol이 표본 부족일 때 m_vol=1.0을
        쓰는 것과 같은 중립 관례)를 넣어 m_evidence=1.0으로 계산하고
        degraded에 원인을 남긴다."""
        from services.trading.exposure_target import EVIDENCE_TARGET_TRIPS

        coord = _coord_for_shadow()
        storage = MagicMock()
        storage.insert_exposure_shadow = AsyncMock(return_value=True)
        storage.get_recent_index_returns = AsyncMock(return_value=[])
        storage.get_latest_regime_label = AsyncMock(return_value="neutral")
        storage.count_round_trips = AsyncMock(return_value=None)
        storage.get_equity_peak = AsyncMock(return_value=497_403_042.0)

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=True), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(return_value=storage)):
            await coord._record_exposure_shadow()

        storage.insert_exposure_shadow.assert_awaited_once()
        kwargs = storage.insert_exposure_shadow.await_args.kwargs
        assert "round_trips_read_failed" in kwargs["target"].degraded
        assert kwargs["target"].m_evidence == pytest.approx(1.0)
        assert kwargs["n_round_trips"] == EVIDENCE_TARGET_TRIPS

    @pytest.mark.asyncio
    async def test_equity_peak_read_failure_is_recorded_as_degraded(self):
        """get_equity_peak이 실패해서 None을 돌려줘도 행은 쓴다 -- 0.0으로
        뭉개도 결과적으로 max(equity, 0.0)=equity라 계산 자체는 중립과
        같지만, degraded 없이는 '진짜 낙폭이 없다'와 '고점을 못 읽었다'가
        똑같이 보인다."""
        coord = _coord_for_shadow()
        storage = MagicMock()
        storage.insert_exposure_shadow = AsyncMock(return_value=True)
        storage.get_recent_index_returns = AsyncMock(return_value=[])
        storage.get_latest_regime_label = AsyncMock(return_value="neutral")
        storage.count_round_trips = AsyncMock(return_value=8)
        storage.get_equity_peak = AsyncMock(return_value=None)

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=True), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(return_value=storage)):
            await coord._record_exposure_shadow()

        storage.insert_exposure_shadow.assert_awaited_once()
        kwargs = storage.insert_exposure_shadow.await_args.kwargs
        assert "equity_peak_read_failed" in kwargs["target"].degraded
        assert kwargs["target"].m_drawdown == pytest.approx(1.0)


class TestObservationOnlyContract:
    """이 유닛은 사이징을 건드리지 않는다 -- 계약을 코드로 고정한다."""

    @pytest.mark.asyncio
    async def test_recording_does_not_change_allocation(self):
        """섀도 기록 전후로 사이징 결과가 동일해야 한다."""
        from services.trading.models import AccountInfo, RiskParameters
        from services.trading.portfolio_agent import PortfolioAgent

        agent = PortfolioAgent(risk_params=RiskParameters(max_single_position_pct=0.03))
        account = AccountInfo(total_equity=497_403_042.0, available_cash=449_360_601.0)

        before = agent.calculate_allocation(
            account=account, ticker="005930", stock_name="삼성전자",
            side="buy", entry_price=70_000.0, risk_score=3,
            stop_loss=65_000.0, take_profit=80_000.0, current_positions=[],
        )

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

        after = agent.calculate_allocation(
            account=account, ticker="005930", stock_name="삼성전자",
            side="buy", entry_price=70_000.0, risk_score=3,
            stop_loss=65_000.0, take_profit=80_000.0, current_positions=[],
        )

        assert before.quantity == after.quantity
        assert before.estimated_amount == pytest.approx(after.estimated_amount)

    def test_exposure_target_module_does_not_import_execution_paths(self):
        """순수 계산 모듈이 실행 경로를 import하면 '관측 전용'이 깨진다.

        cwd에 의존하지 않도록 모듈의 __file__로 경로를 잡는다.
        """
        import ast
        from pathlib import Path

        import services.trading.exposure_target as mod

        tree = ast.parse(Path(mod.__file__).read_text())
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")

        forbidden = ("coordinator", "portfolio_agent", "autonomy",
                     "storage_service", "kiwoom")
        for name in imported:
            assert not any(f in name for f in forbidden), (
                f"{name}을 import하면 순수성이 깨진다 — 이 모듈은 DB도 API도 몰라야 한다"
            )
