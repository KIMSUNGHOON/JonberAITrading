"""exposure_shadow 기록 경로 (레짐 인지 노출도 제어, 2026-08-07 개편).

⚠️ storage를 건드리는 테스트는 반드시 isolated_storage_service를 쓴다.
opt-in 격리 없는 테스트가 라이브 storage.db를 덮어써 코디네이터 상태를
훼손한 사고가 실제로 있었다.

2026-08-07: `compute_target_exposure`(M_evidence 기반)가
`compute_regime_target`(레짐 앵커 + 일일 변화 한도)으로 대체되면서
`coordinator._record_exposure_shadow`는 이제 `storage.get_equity_peak()`/
`storage.get_latest_regime_judgment()`/`storage.get_recent_macro_returns(
"SPY", ...)` 세 조회만 쓴다. 옛 `get_latest_regime_label`/
`count_round_trips`/`get_recent_index_returns` 경로는 더 이상 쓰이지
않는다(메서드 자체는 storage_service.py에 orphan으로 남아있지만, 이
파일은 실제로 쓰이는 새 경로만 검증한다 -- 죽은 경로를 검증하면 "이
파일을 보면 실제 배선을 알 수 있다"는 약속이 깨진다).

한때 이 파일 전체가 module-level `pytest.skip`으로 빠져 있었다 -- 옛
`compute_target_exposure` import가 깨져 test_trading/ 디렉터리 전체
collection이 중단됐기 때문이다. 근본 원인은
`storage_service.insert_exposure_shadow`가 `target.m_regime`/
`target.m_evidence`를 여전히 참조하던 결함이었다 -- `TargetExposure`에서
그 필드들이 지워지면서 실제로 호출되면 `AttributeError`가 나고, 그게
`_record_exposure_shadow`의 바깥 `try/except`에 조용히 삼켜져 관측 행
기록이 **아무 증상 없이** 전부 실패하고 있었다(리뷰 발견). 두 컬럼에
`None`을 직접 넣도록 `insert_exposure_shadow`를 고친 뒤(값은
`regime_judgment` 테이블로 이전, 컬럼은 하위호환을 위해 NULL로 유지)
이 파일을 새 계약에 맞게 다시 썼다.

그 회귀에 대한 실제 가드는 `isolated_storage_service`로 **진짜** 저장소를
타는 세 테스트(`test_insert_and_read_round_trip`/
`test_degraded_reasons_are_persisted`/
`test_empty_degraded_list_round_trips_as_empty_string_not_null`)다 --
`target.m_regime`/`target.m_evidence`로 되돌려서 직접 확인했다(RED:
`test_insert_and_read_round_trip`은 `assert False is True`, 나머지 둘은
행이 안 쓰여 `IndexError`). `TestExposureShadowRecording` 쪽 테스트들은
`storage.insert_exposure_shadow`가 `AsyncMock`이라 진짜 저장소 코드를
타지 않으므로 이 특정 회귀는 잡지 못한다 -- 대신 `_record_exposure_shadow`가
어떤 인자로 무엇을 부르는지(레짐 판정 조회·계산·None 배선)를 검증한다.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.trading.exposure_target import compute_regime_target


@pytest.mark.asyncio
async def test_insert_and_read_round_trip(isolated_storage_service):
    result = compute_regime_target(
        regime_label="neutral",
        prev_effective_pct=None,
        seed_actual_pct=49_426_800.0 / 497_403_042.0,
        index_returns=[],
        equity=497_403_042.0,
        equity_peak=497_403_042.0,
    )

    ok = await isolated_storage_service.insert_exposure_shadow(
        trade_date="2026-08-07",
        target=result,
        equity=497_403_042.0,
        stock_value=49_426_800.0,
        actual_pct=49_426_800.0 / 497_403_042.0,
        n_round_trips=None,
        e_base=None,
        e_max=None,
        equity_peak=497_403_042.0,
    )
    assert ok is True

    rows = await isolated_storage_service.get_exposure_shadow("2026-08-07")
    assert len(rows) == 1
    row = rows[0]
    assert row["target_pct"] == pytest.approx(result.target_pct)
    assert row["actual_pct"] == pytest.approx(0.0994, abs=1e-3)
    assert row["binding"] == result.binding
    assert row["equity_peak"] == pytest.approx(497_403_042.0)

    # ① 회귀 가드: 삭제된 필드(m_regime/m_evidence)는 0이 아니라 NULL로
    # 남아야 한다 -- 0을 넣으면 "배수가 0이었다"로 오독돼 사후 분석이
    # 오염된다. 값 자체는 regime_judgment 테이블로 이전됐다.
    assert row["m_regime"] is None
    assert row["m_evidence"] is None
    assert row["n_round_trips"] is None
    assert row["e_base"] is None
    assert row["e_max"] is None


@pytest.mark.asyncio
async def test_degraded_reasons_are_persisted(isolated_storage_service):
    """저하 사유가 사라지면 나중에 판정이 불가능하다."""
    result = compute_regime_target(
        regime_label="neutral",
        prev_effective_pct=0.65,
        seed_actual_pct=0.0994,
        index_returns=[-10.84, 17.91, -5.12, 1.62, 3.76, -6.36, -4.46],
        equity=497_403_042.0,
        equity_peak=497_403_042.0,
        series_stale=True,
    )
    assert "index_series_stale" in result.degraded

    await isolated_storage_service.insert_exposure_shadow(
        trade_date="2026-08-07",
        target=result,
        equity=497_403_042.0,
        stock_value=49_426_800.0,
        actual_pct=0.0994,
        n_round_trips=None,
    )
    row = (await isolated_storage_service.get_exposure_shadow("2026-08-07"))[0]
    assert "index_series_stale" in row["degraded"]
    assert row["index_vol_annualized"] > 60.0
    assert row["index_vol_n"] == 7


@pytest.mark.asyncio
async def test_empty_degraded_list_round_trips_as_empty_string_not_null(
    isolated_storage_service,
):
    """빈 리스트는 빈 문자열로 남아야 한다 -- NULL("기록 안 됨")과 구별되는
    "저하 없음"이라는 판정이다. 알려진 regime_label, 신선한(series_stale=False)
    변동성 표본(연율 약 18%), 그리고 prev_effective_pct를 앵커와 같게 줘서
    (ramped==anchor, daily_limit 안 걸림) degraded가 실제로 빌 조건을
    만든다."""
    result = compute_regime_target(
        regime_label="neutral",
        prev_effective_pct=0.65,
        seed_actual_pct=0.0994,
        index_returns=[1.14, -1.14] * 10,
        equity=497_403_042.0,
        equity_peak=497_403_042.0,
    )
    assert result.degraded == []

    await isolated_storage_service.insert_exposure_shadow(
        trade_date="2026-08-07",
        target=result,
        equity=497_403_042.0,
        stock_value=49_426_800.0,
        actual_pct=0.0994,
        n_round_trips=None,
    )
    row = (await isolated_storage_service.get_exposure_shadow("2026-08-07"))[0]
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


class TestGetEquityPeakFailsClosed:
    """`get_equity_peak`는 여전히 살아있는 배선이다 --
    `coordinator._record_exposure_shadow`가 지금도 이걸 부른다(옛
    `get_latest_regime_label`/`count_round_trips`/`get_recent_index_returns`와
    다르다 -- 그 셋은 `services/`를 grep해도 storage_service.py 밖에서
    더 이상 안 불려 진짜 orphan이라 이 파일에서 뺐다).

    조회 자체가 실패하면 그럴싸한 기본값(0.0 -- "낙폭 없음")이 아니라
    `None`을 돌려줘야 한다 -- 실패와 "스냅샷이 아직 없다"(진짜 0.0)를
    코디네이터가 구분할 수 있어야 하기 때문이다. 리뷰 발견: 이 파일을
    통째로 재작성하면서 진짜 orphan 3종과 함께 이 테스트까지 지워
    `get_equity_peak`가 나중에 `except: return 0.0`으로 바뀌어도 아무
    테스트도 못 잡는 상태가 됐었다."""

    @pytest.mark.asyncio
    async def test_returns_none_on_read_failure(
        self, isolated_storage_service, monkeypatch
    ):
        import services.storage_service as ss

        async def _boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(ss.aiosqlite, "connect", _boom)
        assert await isolated_storage_service.get_equity_peak() is None

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_snapshot_yet(self, isolated_storage_service):
        """스냅샷이 아직 없는 것(정상)과 조회 실패(비정상)는 다른 사실이다."""
        assert await isolated_storage_service.get_equity_peak() == 0.0


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


def _storage_double(**overrides):
    """_record_exposure_shadow가 실제로 부르는 세 조회 + insert를 채운 더블.

    옛 4-헬퍼(get_recent_index_returns/get_latest_regime_label/
    count_round_trips/get_equity_peak) 중 get_equity_peak만 남고 나머지는
    get_latest_regime_judgment/get_recent_macro_returns로 교체됐다."""
    storage = MagicMock()
    storage.insert_exposure_shadow = AsyncMock(return_value=True)
    storage.get_equity_peak = AsyncMock(return_value=497_403_042.0)
    storage.get_latest_regime_judgment = AsyncMock(
        return_value={"regime": "neutral", "prev_effective_pct": None}
    )
    storage.get_recent_macro_returns = AsyncMock(return_value=[])
    for key, value in overrides.items():
        setattr(storage, key, value)
    return storage


class TestExposureShadowRecording:
    @pytest.mark.asyncio
    async def test_skips_when_market_closed(self):
        """장외에는 행을 쓰지 않는다 — 기존 감시 루프의 idle 규약과 동일."""
        coord = _coord_for_shadow()
        storage = _storage_double()

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=False), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(return_value=storage)):
            await coord._record_exposure_shadow()

        storage.get_latest_regime_judgment.assert_not_awaited()
        storage.insert_exposure_shadow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_when_equity_is_zero(self):
        """0으로 채운 행은 나중에 진짜 0과 구분되지 않는다."""
        from services.trading.models import AccountInfo

        coord = _coord_for_shadow()
        coord._state.account = AccountInfo(total_equity=0.0, available_cash=0.0)
        storage = _storage_double()

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=True), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(return_value=storage)):
            await coord._record_exposure_shadow()

        storage.get_latest_regime_judgment.assert_not_awaited()
        storage.insert_exposure_shadow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_records_a_row_during_market_hours(self):
        """`_record_exposure_shadow`가 계산·인자 배선을 올바르게 하는지
        본다. ⚠️ 여기서 `storage.insert_exposure_shadow`는 `AsyncMock`이라
        진짜 저장소 코드를 타지 않는다 -- ①(`target.m_regime`/
        `target.m_evidence`) 회귀는 이 테스트로 잡히지 않는다(직접
        검증해봤다: `storage_service.insert_exposure_shadow`를 일부러
        되돌려도 이 테스트는 계속 통과했다 -- mock이 실제 구현을 가린다).
        그 회귀의 실제 가드는 `isolated_storage_service`로 진짜
        저장소를 타는 `test_insert_and_read_round_trip`/
        `test_degraded_reasons_are_persisted`/
        `test_empty_degraded_list_round_trips_as_empty_string_not_null`이다
        -- 되돌려서 확인해보면 세 테스트 다 RED가 된다(`assert False is
        True` / `IndexError`)."""
        coord = _coord_for_shadow()
        storage = _storage_double()

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=True), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(return_value=storage)):
            await coord._record_exposure_shadow()

        storage.insert_exposure_shadow.assert_awaited_once()
        kwargs = storage.insert_exposure_shadow.await_args.kwargs
        assert kwargs["n_round_trips"] is None
        assert kwargs["e_base"] is None
        assert kwargs["e_max"] is None
        assert kwargs["target"].anchor_pct == pytest.approx(0.65)  # neutral

    @pytest.mark.asyncio
    async def test_storage_failure_never_propagates(self):
        """관측 실패가 코디네이터 루프를 죽이면 본말전도다."""
        coord = _coord_for_shadow()

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=True), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(side_effect=RuntimeError("db down"))):
            await coord._record_exposure_shadow()   # raise 하면 실패

    @pytest.mark.asyncio
    async def test_missing_regime_judgment_falls_back_to_bear_not_a_crash(self):
        """아직 레짐 판정이 한 번도 안 돈 상태(judgment=None)에서도 행을
        쓴다 -- 가장 보수적인 bear 앵커로 떨어져야지, 죽거나 중간값을
        고르면 안 된다. "bear"는 알려진 라벨이므로 regime_unknown이
        아니라는 점도 함께 확인한다(조회/파싱 실패와 정당한 bear 판정은
        다른 사실이다)."""
        coord = _coord_for_shadow()
        storage = _storage_double(
            get_latest_regime_judgment=AsyncMock(return_value=None),
        )

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=True), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(return_value=storage)):
            await coord._record_exposure_shadow()

        storage.insert_exposure_shadow.assert_awaited_once()
        kwargs = storage.insert_exposure_shadow.await_args.kwargs
        assert kwargs["target"].anchor_pct == pytest.approx(0.55)  # bear
        assert "regime_unknown" not in kwargs["target"].degraded


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
        쓰기 때문이다. coord._state의 불변은 아래
        test_recording_does_not_mutate_coordinator_state가 따로 담당한다
        -- 두 테스트는 서로 다른 갭을 막는다."""
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
        storage = _storage_double()
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

        `_coord_for_shadow()`가 실제로 넣는 값을 리터럴 상수로 못박아 두고
        호출 후 그 상수와 비교한다(account가 인플레이스로 바뀌면 참조
        비교는 자기 자신과 비교하는 꼴이 되어 항상 통과해버린다)."""
        coord = _coord_for_shadow()
        storage = _storage_double()

        with patch("services.trading.coordinator.is_krx_open_cached", return_value=True), \
             patch("services.storage_service.get_storage_service",
                   new=AsyncMock(return_value=storage)):
            await coord._record_exposure_shadow()

        assert coord._state.account.total_equity == pytest.approx(497_403_042.0)
        assert coord._state.account.available_cash == pytest.approx(449_360_601.0)
        assert coord._state.positions == []

    def test_exposure_target_module_does_not_import_execution_paths(self):
        """순수 계산 모듈이 실행 경로를 import하면 '관측 전용'이 깨진다.

        cwd에 의존하지 않도록 모듈의 __file__로 경로를 잡는다. 각 별칭을
        `node.module`과 합성한 `"{module}.{alias.name}"`도 함께 검사해
        `from services.trading import coordinator`나 `from . import
        coordinator`(node.module이 None인 상대 import) 형태도 잡는다.

        ⚠️ 알려진 한계: 문자열로 모듈 경로를 조립하는 완전 동적 import
        (`importlib.import_module(...)`, `__import__(...)`)는 `ast.Import`/
        `ast.ImportFrom` 노드로 나타나지 않아 이 정적 분석으로는 못 잡는다.
        exposure_target.py에는 현재 그런 메커니즘이 없다.
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
