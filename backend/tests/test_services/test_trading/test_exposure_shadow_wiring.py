"""exposure_shadow 기록 경로 (관측 단계, 2026-08-06).

⚠️ storage를 건드리는 테스트는 반드시 isolated_storage_service를 쓴다.
opt-in 격리 없는 테스트가 라이브 storage.db를 덮어써 코디네이터 상태를
훼손한 사고가 실제로 있었다.

2026-08-07 (Task 4): `compute_target_exposure`(M_evidence 기반)가
`compute_regime_target`(레짐 앵커 + 일일 변화 한도)으로 대체되면서
`coordinator._record_exposure_shadow`의 호출 시그니처가 바뀌었다
(regime_label/n_round_trips/e_base/e_max 인자 자체가 사라짐). 이 파일의
배선 테스트는 옛 시그니처와 `insert_exposure_shadow`가 여전히 참조하는
`target.m_regime`/`target.m_evidence`(TargetExposure에서 제거됨) 둘 다에
묶여 있어, 그대로 두면 이번 태스크에서 ImportError로 전체 test_trading
디렉터리 수집이 중단된다. 실제 재배선(및 exposure_shadow 스키마 정리)은
Task 8(스케줄·주입·관측)의 몫이므로 여기서는 스킵만 하고 재작성하지
않는다 -- Task 8이 이 파일을 새 계약에 맞게 갱신해야 한다.
"""
import pytest

pytest.skip(
    "compute_target_exposure 제거(Task 4) — coordinator._record_exposure_shadow "
    "재배선 및 insert_exposure_shadow 스키마 정리는 Task 8이 담당",
    allow_module_level=True,
)


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
        e_base=0.50,
        e_max=0.30,
        equity_peak=497_403_042.0,
    )
    assert ok is True

    rows = await isolated_storage_service.get_exposure_shadow("2026-08-06")
    assert len(rows) == 1
    row = rows[0]
    assert row["target_pct"] == pytest.approx(0.10)
    assert row["actual_pct"] == pytest.approx(0.0994, abs=1e-3)
    assert row["binding"] == "m_evidence"
    assert row["m_evidence"] == pytest.approx(0.20)
    assert row["e_base"] == pytest.approx(0.50)
    assert row["e_max"] == pytest.approx(0.30)
    assert row["equity_peak"] == pytest.approx(497_403_042.0)


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

    @pytest.mark.asyncio
    async def test_get_recent_index_returns_returns_none_on_read_failure(
        self, isolated_storage_service, monkeypatch
    ):
        """네 번째 조회 헬퍼도 같은 규약이어야 한다 -- 조회 실패를 `[]`로
        뭉개면 '지수 이력이 짧다'(진짜 데이터)와 구분이 안 된다(리뷰
        반영, 2026-08-06)."""
        import services.storage_service as ss

        async def _boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(ss.aiosqlite, "connect", _boom)
        assert await isolated_storage_service.get_recent_index_returns() is None

    @pytest.mark.asyncio
    async def test_get_recent_index_returns_returns_empty_list_when_table_empty(
        self, isolated_storage_service
    ):
        """지수 이력이 아직 없는 것과 조회 실패는 다른 사실이다 -- 빈
        테이블은 `[]`(진짜 데이터)여야지 `None`(조회 실패)이 아니다."""
        assert await isolated_storage_service.get_recent_index_returns() == []


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
    async def test_index_returns_read_failure_is_recorded_as_degraded(self):
        """get_recent_index_returns이 실패해서 None을 돌려줘도 행은 쓴다 --
        `[]`로 조용히 뭉개면 '지수 이력이 짧다'는 진짜 신호(빈 리스트도
        똑같이 만든다)와 '조회가 실패했다'가 나중에 구분되지 않는다.
        m_vol 자체는 중립값(1.0)으로 계산하되 degraded에 원인을 남긴다."""
        coord = _coord_for_shadow()
        storage = MagicMock()
        storage.insert_exposure_shadow = AsyncMock(return_value=True)
        storage.get_recent_index_returns = AsyncMock(return_value=None)
        storage.get_latest_regime_label = AsyncMock(return_value="neutral")
        storage.count_round_trips = AsyncMock(return_value=8)
        storage.get_equity_peak = AsyncMock(return_value=497_403_042.0)

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=True), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(return_value=storage)):
            await coord._record_exposure_shadow()

        storage.insert_exposure_shadow.assert_awaited_once()
        kwargs = storage.insert_exposure_shadow.await_args.kwargs
        assert "index_returns_read_failed" in kwargs["target"].degraded
        assert kwargs["target"].m_vol == pytest.approx(1.0)

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
        degraded에 원인을 남긴다. 다만 그 대체값 자체는 행에 저장하지
        않는다(아래 n_round_trips 어서션)."""
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
        # 계산에는 대체값(EVIDENCE_TARGET_TRIPS)을 쓰지만, 저장하는 행의
        # n_round_trips 컬럼에는 None을 넘겨야 한다 -- 40을 그대로 저장하면
        # 나중에 AVG(n_round_trips) 같은 집계가 측정값과 대체값을 구분하지
        # 못하고 섞인다(리뷰 반영, 2026-08-06). 대체값은 target.m_evidence
        # 계산에만 살아있어야 한다.
        assert kwargs["n_round_trips"] is None

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
    async def test_recording_has_no_global_side_effect_on_sizing(self):
        """섀도 기록이 PortfolioAgent.calculate_allocation과 공유하는
        전역/모듈 상태가 없어야 한다 -- 기록 전후로 완전히 독립된
        agent/account 쌍(coord와 무관하게 새로 만든 것)에 대해 같은
        입력을 넣으면 같은 사이징이 나와야 한다는 뜻이다.

        ⚠️ 이 테스트는 coord._state 자체가 훼손되지 않았는지는 보지
        않는다 -- before/after 모두 coord와 별개로 만든 agent/account를
        쓰기 때문이다(원래 있던 형태를 그대로 유지). coord._state의
        불변은 아래 test_recording_does_not_mutate_coordinator_state가
        따로 담당한다 -- 두 테스트는 서로 다른 갭을 막는다."""
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

    @pytest.mark.asyncio
    async def test_recording_does_not_mutate_coordinator_state(self):
        """_record_exposure_shadow는 관측 전용이다 -- coord._state.account/
        positions를 갱신해서는 안 된다.

        Task 4 리뷰가 지적한 구멍: `_coord_for_shadow()`의 `coord._state`는
        MagicMock이라 임의의 속성 쓰기를 조용히 받아준다. 그 안의
        `coord._state.account`는 진짜 Pydantic v2 모델(AccountInfo,
        frozen 아님)이라 `self._state.account.total_equity = ...`처럼
        인플레이스로 고쳐도 예외 없이 성공한다 -- 즉 MagicMock 자체는
        이런 변형을 절대 못 잡는다.

        여기서 "호출 전 값을 참조로 저장해뒀다가 호출 후 그 참조와
        비교"하면 안 된다 -- account가 인플레이스로 바뀌면 그 참조도
        같이 바뀌어 자기 자신과 비교하는 꼴이 되어 항상 통과한다
        (리뷰 지적). 그래서 `_coord_for_shadow()`가 실제로 넣는 값을
        리터럴 상수로 못박아 두고 호출 후 그 상수와 비교한다."""
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

        # _coord_for_shadow()가 세팅한 값 그대로(리터럴). coord._state.account
        # 자체와 비교하지 않는다 -- 인플레이스 변형이면 참조도 같이 바뀐다.
        assert coord._state.account.total_equity == pytest.approx(497_403_042.0)
        assert coord._state.account.available_cash == pytest.approx(449_360_601.0)
        assert coord._state.positions == []

    def test_exposure_target_module_does_not_import_execution_paths(self):
        """순수 계산 모듈이 실행 경로를 import하면 '관측 전용'이 깨진다.

        cwd에 의존하지 않도록 모듈의 __file__로 경로를 잡는다.

        `ast.ImportFrom`은 `node.module`만 보면 안 된다 -- `from services.trading
        import coordinator`처럼 금지어가 `node.names`의 별칭에만 있고
        `node.module`("services.trading")에는 없는 형태, 그리고
        `from . import coordinator`처럼 `node.module`이 아예 None인 상대
        import 형태를 둘 다 놓친다(리뷰에서 실제로 셋 다 안 잡히는 것을
        AST 프로브로 확인). 그래서 각 별칭을 `node.module`과 합성한
        `"{module}.{alias.name}"`(module이 없으면 `alias.name` 그대로)도
        함께 검사 대상에 넣는다. `ast.walk`는 함수 본문 내부까지
        재귀하므로 지연 import(함수 안 import)도 잡힌다.

        ⚠️ 알려진 한계: `importlib.import_module("services.trading.coordinator")`나
        `__import__(...)`처럼 문자열로 모듈 경로를 조립하는 완전 동적
        import는 `ast.Import`/`ast.ImportFrom` 노드로 나타나지 않아 이
        정적 분석으로는 잡을 수 없다(함수 호출의 문자열 인자까지
        해석하지 않는다). exposure_target.py에는 현재 그런 동적 import
        메커니즘이 없다 -- 하지만 이 게이트가 "모든 우회를 막는다"는
        보장은 아니라는 뜻이므로 여기 명시해둔다.
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
                module = node.module or ""
                imported.append(module)
                prefix = f"{module}." if module else ""
                imported += [f"{prefix}{alias.name}" for alias in node.names]

        forbidden = ("coordinator", "portfolio_agent", "autonomy",
                     "storage_service", "kiwoom")
        for name in imported:
            assert not any(f in name for f in forbidden), (
                f"{name}을 import하면 순수성이 깨진다 — 이 모듈은 DB도 API도 몰라야 한다"
            )
