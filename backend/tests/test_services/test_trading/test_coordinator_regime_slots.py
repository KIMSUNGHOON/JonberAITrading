"""레짐 슬롯 배선 — 상향과 **되돌리기**.

2026-08-07 최종 리뷰 이후 이 경로는 두 방향을 갖는다:

- 검사 8이 구속력을 가질 때(킬스위치 on + 유효한 판정) → 슬롯 상향
- 검사 8이 구속력을 잃을 때(킬스위치 off / 판정 부재·만료) → **baseline 복원**

두 번째가 없으면 킬스위치가 롤백이 아니라 완화 동작이 된다(C-2).

2026-08-08: **`max_single_position_pct`(종목당 상한)의 소유권을 전략 패널에게
돌려줬다.** `apply_regime_slots`는 더 이상 그 필드를 건드리지 않는다 — 슬롯
수만 올린다(`slots_for_target`은 `REGIME_PER_POSITION_PCT`를 기본 인자로 직접
쓰지 `risk_params`를 읽지 않는다). baseline 저장·복원도 `max_open_positions`
하나만 다룬다. 그렇지 않으면 패널이 0.10으로 올려도 킬스위치 off나 판정
만료로 되돌리기가 돌 때마다 `min(0.10, baseline 0.03)`으로 조용히 깎인다 —
브레이크(슬롯 상한)가 우연히 가리고 있던, 진입 경로의 같은 결함(대입이
ADD/BUY 어느 쪽에서도 실효값에 못 미치던 문제)의 세 번째 판.

⚠️ 이 테스트들은 실제 `StorageService`를 탄다(baseline은 별도 app_setting
키에 산다). 반드시 `temp_storage`로 격리한다 -- 이 리포는 테스트가 라이브
`storage.db`에 쓴 전력이 있다.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

import services.storage_service as ss
from services.storage_service import StorageService
from services.trading.coordinator import ExecutionCoordinator

pytestmark = pytest.mark.asyncio

# 2026-08-08 이후의 baseline 형태 — max_open_positions만 갖는다.
_BASELINE = {"max_open_positions": 7}

# 하위호환 테스트 전용 — 수정 이전에 저장됐을 수 있는 옛 형태(`
# max_single_position_pct` 키 포함). 복원 코드가 이 키를 무시하고도
# 깨지지 않아야 한다.
_BASELINE_LEGACY = {"max_open_positions": 7, "max_single_position_pct": 0.03}


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    storage = StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


def _coord(slots: int = 7, pct: float = 0.03, persistence: bool = True):
    """라이브 값(슬롯 7 × 종목당 3%)을 든 코디네이터.

    `_persistence_active=True`가 기본인 것은 의도다 -- 08:05 사이클이 실제로
    도는 상태(`start()`를 거쳐 `_restore_state()`가 라이브 risk_params를
    되살린 상태)가 그것이다. False는 I-1 테스트에서만 명시적으로 쓴다.
    """
    c = ExecutionCoordinator(kiwoom_client=None)
    c.risk_params.max_open_positions = slots
    c.risk_params.max_single_position_pct = pct
    c._persistence_active = persistence
    return c


def _settings(enabled: bool):
    gs = patch("services.trading.coordinator.get_settings")
    return gs, enabled


async def _seed_baseline(storage, coord, baseline=None):
    await storage.set_app_setting(
        coord._REGIME_BASELINE_KEY, json.dumps(baseline or _BASELINE)
    )


# -------------------------------------------
# 상향 (기존 계약 — 불변)
# -------------------------------------------


@pytest.mark.parametrize("panel_pct", [0.03, 0.10])
async def test_target_raises_slots_without_touching_per_position(
    temp_storage, panel_pct
):
    """**핵심 속성 ①.** 레짐 채널은 슬롯만 올린다 — 종목당 상한은 이제
    전략 패널 소유이고, 패널이 뭘 정했든(0.03이든 0.10이든) 이 경로가 절대
    덮어쓰지 않는다."""
    c = _coord(pct=panel_pct)
    with patch("services.trading.coordinator.get_settings") as gs, \
         patch("services.trading.regime_judge.get_effective_target",
               AsyncMock(return_value=0.55)):
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        out = await c.apply_regime_slots()
    assert out == {"max_open_positions": 11}
    assert c.risk_params.max_open_positions == 11
    assert c.risk_params.max_single_position_pct == panel_pct


async def test_slots_never_decrease(temp_storage):
    """목표가 내려가도 슬롯은 그대로 — 줄이면 집중도가 오른다."""
    c = _coord(slots=16, pct=0.05)
    with patch("services.trading.coordinator.get_settings") as gs, \
         patch("services.trading.regime_judge.get_effective_target",
               AsyncMock(return_value=0.20)):
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        out = await c.apply_regime_slots()
    assert out["max_open_positions"] == 16
    assert c.risk_params.max_open_positions == 16


# -------------------------------------------
# C-2 — 상향은 검사 8과 생사를 같이한다
# -------------------------------------------


async def test_first_raise_saves_the_pre_branch_baseline(temp_storage):
    """baseline에는 `max_open_positions`만 적힌다 — 종목당 상한은 이 경로가
    상향하지 않으므로 되돌릴 것도 없다."""
    c = _coord()
    with patch("services.trading.coordinator.get_settings") as gs, \
         patch("services.trading.regime_judge.get_effective_target",
               AsyncMock(return_value=0.55)):
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        await c.apply_regime_slots()

    saved = json.loads(await temp_storage.get_app_setting(c._REGIME_BASELINE_KEY))
    assert saved == _BASELINE


async def test_baseline_is_never_overwritten_by_a_later_raise(temp_storage):
    """두 번째 상향이 baseline을 첫 상향값으로 굳히면 "브랜치 이전 값으로
    돌아간다"는 약속이 래칫으로 바뀐다."""
    c = _coord()
    with patch("services.trading.coordinator.get_settings") as gs, \
         patch("services.trading.regime_judge.get_effective_target",
               AsyncMock(side_effect=[0.55, 0.80])):
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        await c.apply_regime_slots()   # 7 → 11
        await c.apply_regime_slots()   # 11 → 16

    assert c.risk_params.max_open_positions == 16
    saved = json.loads(await temp_storage.get_app_setting(c._REGIME_BASELINE_KEY))
    assert saved == _BASELINE


async def test_kill_switch_off_restores_the_pre_branch_ceiling(temp_storage):
    """킬스위치를 끄면 검사 8이 통째로 사라진다. 슬롯 상향만 남으면 실효
    천장이 부풀어 있는데 그것을 상쇄할 기계가 없다 -- 끄는 행위가 완화
    동작이 된다(C-2, 슬롯에 한정). 종목당 상한은 이제 패널 소유라 이
    경로가 건드리지 않는다 -- 아래 전용 테스트 참고."""
    c = _coord(slots=16, pct=0.05)
    await _seed_baseline(temp_storage, c)

    with patch("services.trading.coordinator.get_settings") as gs:
        gs.return_value.REGIME_EXPOSURE_ENABLED = False
        out = await c.apply_regime_slots()

    assert c.risk_params.max_open_positions == 7
    assert out["restored"] is True and out["reason"] == "kill_switch_off"


async def test_restore_never_touches_panel_per_position_pct(temp_storage):
    """**핵심 속성 ②.** 패널이 0.03보다 높게(예: 0.10) 올려 둔 종목당 상한은
    킬스위치 off나 판정 만료로 되돌리기가 돌아도 깎이지 않는다 -- 고쳐지기
    전이라면 `min(0.10, baseline 0.03) = 0.03`으로 조용히 되돌아갔을
    값이다(같은 버그의 두 번째 판)."""
    c = _coord(slots=16, pct=0.10)
    await _seed_baseline(temp_storage, c)

    with patch("services.trading.coordinator.get_settings") as gs:
        gs.return_value.REGIME_EXPOSURE_ENABLED = False
        out = await c.apply_regime_slots()

    assert c.risk_params.max_single_position_pct == 0.10
    assert "max_single_position_pct" not in out


async def test_restore_ignores_legacy_baseline_pct_key(temp_storage):
    """하위호환: 이 수정 이전에 저장된 baseline 행에는 `max_single_position_pct`
    키가 남아 있을 수 있다. 복원 코드가 그 키를 참조하지 않아야 하고(참조하면
    패널 값이 다시 깎인다), 키가 있다는 사실 자체로 깨지지도 않아야 한다."""
    c = _coord(slots=16, pct=0.10)
    await _seed_baseline(temp_storage, c, baseline=_BASELINE_LEGACY)

    with patch("services.trading.coordinator.get_settings") as gs:
        gs.return_value.REGIME_EXPOSURE_ENABLED = False
        out = await c.apply_regime_slots()

    assert c.risk_params.max_open_positions == 7
    assert c.risk_params.max_single_position_pct == 0.10
    assert out["restored"] is True


async def test_expired_or_absent_judgment_restores_the_pre_branch_ceiling(temp_storage):
    """판정 5역일 만료·매크로 수집 연속 실패도 검사 8을 스킵시킨다 --
    `get_effective_target()`이 `None`을 돌려주는 그 경우 전부. 슬롯만
    되돌아가고 종목당 상한(패널 소유)은 그대로다."""
    c = _coord(slots=16, pct=0.05)
    await _seed_baseline(temp_storage, c)

    with patch("services.trading.coordinator.get_settings") as gs, \
         patch("services.trading.regime_judge.get_effective_target",
               AsyncMock(return_value=None)):
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        out = await c.apply_regime_slots()

    assert c.risk_params.max_open_positions == 7
    assert c.risk_params.max_single_position_pct == 0.05
    assert out["reason"] == "judgment_absent_or_stale"


async def test_read_failure_does_not_restore_because_the_gate_fails_closed(temp_storage):
    """DB 오류는 검사 8을 **더** 구속력 있게 만든다(fail-closed deny). 되돌려야
    하는 것은 검사가 조용히 스킵되는 경우뿐이다 -- 여기서 되돌리면 오류가
    오히려 노출도를 흔든다."""
    c = _coord(slots=16, pct=0.05)
    await _seed_baseline(temp_storage, c)

    with patch("services.trading.coordinator.get_settings") as gs, \
         patch("services.trading.regime_judge.get_effective_target",
               AsyncMock(side_effect=RuntimeError("db down"))):
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        assert await c.apply_regime_slots() is None

    assert c.risk_params.max_open_positions == 16
    assert c.risk_params.max_single_position_pct == 0.05


async def test_restore_without_a_baseline_changes_nothing(temp_storage):
    """한 번도 상향한 적이 없으면 되돌릴 것도 없다 -- 킬스위치 off가
    기본 배포에서 아무 값도 건드리지 않아야 한다(현행 동작과 동일)."""
    c = _coord()
    with patch("services.trading.coordinator.get_settings") as gs:
        gs.return_value.REGIME_EXPOSURE_ENABLED = False
        assert await c.apply_regime_slots() is None
    assert c.risk_params.max_open_positions == 7
    assert c.risk_params.max_single_position_pct == 0.03


async def test_restore_never_raises_the_ceiling(temp_storage):
    """되돌리기는 슬롯을 **내리기만** 한다. 운영자가 baseline보다 더 낮춰 둔
    값을 복원이 도로 올리면 그것도 "장애가 노출도를 위로 여는" 형태다.
    **회귀 가드 ③** — `max_open_positions`의 상향·되돌리기가 여전히
    작동하는지."""
    c = _coord(slots=4, pct=0.02)
    await _seed_baseline(temp_storage, c)

    with patch("services.trading.coordinator.get_settings") as gs:
        gs.return_value.REGIME_EXPOSURE_ENABLED = False
        await c.apply_regime_slots()

    assert c.risk_params.max_open_positions == 4
    assert c.risk_params.max_single_position_pct == 0.02


async def test_restore_is_persisted_so_a_restart_keeps_it(temp_storage):
    c = _coord(slots=16, pct=0.05)
    await _seed_baseline(temp_storage, c)

    with patch("services.trading.coordinator.get_settings") as gs:
        gs.return_value.REGIME_EXPOSURE_ENABLED = False
        await c.apply_regime_slots()

    blob = json.loads(await temp_storage.get_app_setting(c._STATE_KEY))
    assert blob["risk_params"]["max_open_positions"] == 7
    assert blob["risk_params"]["max_single_position_pct"] == 0.05


async def test_start_reconciles_slots_with_the_gate(temp_storage):
    """배선 카나리 -- 킬스위치가 off면 08:05 스케줄러가 **아예 안 뜨므로**
    되돌리기가 스케줄러 안에만 있으면 영원히 실행되지 않는다. 코디네이터
    기동은 킬스위치와 무관하게 돌기 때문에 여기가 유일하게 확실한 지점이다.

    `start()`가 `_restore_state()`로 블롭의 (상향된) risk_params를 되살린
    **뒤**에 화해가 일어나는지까지 함께 잠근다. **회귀 가드 ③.**
    """
    c = ExecutionCoordinator(kiwoom_client=None)
    await _seed_baseline(temp_storage, c)
    await temp_storage.set_app_setting(
        c._STATE_KEY,
        json.dumps(
            {
                "positions": [],
                "trade_queue": [],
                "watch_list": [],
                "daily_trades_count": 0,
                "daily_count_date": "2026-08-07",
                "risk_params": {
                    "max_open_positions": 16,
                    "max_single_position_pct": 0.05,
                },
                "mode": "active",
            }
        ),
    )

    with patch("services.trading.coordinator.get_settings") as gs:
        gs.return_value.REGIME_EXPOSURE_ENABLED = False
        await c.start(drain_queue=False)
        try:
            assert c.risk_params.max_open_positions == 7
            assert c.risk_params.max_single_position_pct == 0.05
        finally:
            await c.stop()


# -------------------------------------------
# I-1 — 라이브 리스크 파라미터를 기본값으로 덮어쓰지 않는다
# -------------------------------------------


async def test_persistence_inactive_skips_entirely_and_preserves_live_params(
    temp_storage,
):
    """`_persistence_active=False`면 `self.risk_params`는 `RiskParameters()`
    **기본값**이지 라이브 값이 아니다(`resume_if_persisted()`가 저장된
    mode≠active면 `_restore_state()` 없이 no-op하는 실재 경로).

    그 상태에서 계산도 쓰기도 하면 안 된다. 예전 구현은
    `_persist_fields(risk_params=...)`로 블롭의 `risk_params` 최상위 키를
    **통째로 교체**해서, 운영자가 트레이딩을 정지시켜 둔 채 재시작한 다음날
    아침 08:05에 `max_trade_notional_pct` 10.0 → 15.0(자율 게이트 검사 7의
    안전 레일이 50% 완화)이 조용히 일어났다.
    """
    live = {
        "max_open_positions": 7,
        "max_single_position_pct": 0.03,
        "max_trade_notional_pct": 10.0,
        "min_cash_ratio": 0.30,
    }
    c = _coord(persistence=False)
    await temp_storage.set_app_setting(
        c._STATE_KEY, json.dumps({"risk_params": dict(live), "mode": "stopped"})
    )

    with patch("services.trading.coordinator.get_settings") as gs, \
         patch("services.trading.regime_judge.get_effective_target",
               AsyncMock(return_value=0.55)) as get_target:
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        assert await c.apply_regime_slots() is None

    # 목표를 조회조차 하지 않는다 -- 입력이 틀렸으므로 쓰기만 고칠 문제가 아니다.
    get_target.assert_not_awaited()
    blob = json.loads(await temp_storage.get_app_setting(c._STATE_KEY))
    assert blob["risk_params"] == live


async def test_persistence_active_uses_the_full_snapshot(temp_storage):
    """`_persistence_active=True`(= `_restore_state()`가 이미 돌아 `_state`가
    진짜 데이터) 일 때만 전체 스냅샷을 쓴다 -- 2026-07-29의 "빈 스냅샷이 실
    포지션 손절가를 덮어씀" 사고는 False에서만 성립한다."""
    c = _coord()
    c._persist_state = AsyncMock()
    c._persist_fields = AsyncMock()
    with patch("services.trading.coordinator.get_settings") as gs, \
         patch("services.trading.regime_judge.get_effective_target",
               AsyncMock(return_value=0.55)):
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        out = await c.apply_regime_slots()

    assert out == {"max_open_positions": 11}
    c._persist_state.assert_awaited_once()
    c._persist_fields.assert_not_called()
