from unittest.mock import AsyncMock, patch

import pytest

from services.trading.models import RiskParameters


def _coord():
    from services.trading.coordinator import ExecutionCoordinator

    c = ExecutionCoordinator.__new__(ExecutionCoordinator)
    c.risk_params = RiskParameters()
    c.risk_params.max_open_positions = 7
    c.risk_params.max_single_position_pct = 0.03
    c._persistence_active = False
    return c


@pytest.mark.asyncio
async def test_target_raises_slots_and_sets_per_position():
    c = _coord()
    with patch("services.trading.coordinator.get_settings") as gs, \
         patch("services.trading.regime_judge.get_effective_target",
               AsyncMock(return_value=0.55)):
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        out = await c.apply_regime_slots()
    assert out == {"max_open_positions": 11, "max_single_position_pct": 0.05}
    assert c.risk_params.max_open_positions == 11
    assert c.risk_params.max_single_position_pct == 0.05


@pytest.mark.asyncio
async def test_slots_never_decrease():
    """목표가 내려가도 슬롯은 그대로 — 줄이면 집중도가 오른다."""
    c = _coord()
    c.risk_params.max_open_positions = 16
    with patch("services.trading.coordinator.get_settings") as gs, \
         patch("services.trading.regime_judge.get_effective_target",
               AsyncMock(return_value=0.20)):
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        out = await c.apply_regime_slots()
    assert out["max_open_positions"] == 16
    assert c.risk_params.max_open_positions == 16


@pytest.mark.asyncio
async def test_kill_switch_off_changes_nothing():
    c = _coord()
    with patch("services.trading.coordinator.get_settings") as gs:
        gs.return_value.REGIME_EXPOSURE_ENABLED = False
        assert await c.apply_regime_slots() is None
    assert c.risk_params.max_open_positions == 7
    assert c.risk_params.max_single_position_pct == 0.03


@pytest.mark.asyncio
async def test_no_judgment_changes_nothing():
    c = _coord()
    with patch("services.trading.coordinator.get_settings") as gs, \
         patch("services.trading.regime_judge.get_effective_target",
               AsyncMock(return_value=None)):
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        assert await c.apply_regime_slots() is None
    assert c.risk_params.max_open_positions == 7


@pytest.mark.asyncio
async def test_read_failure_does_not_raise_and_changes_nothing():
    c = _coord()
    with patch("services.trading.coordinator.get_settings") as gs, \
         patch("services.trading.regime_judge.get_effective_target",
               AsyncMock(side_effect=RuntimeError("db down"))):
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        assert await c.apply_regime_slots() is None
    assert c.risk_params.max_open_positions == 7


@pytest.mark.asyncio
async def test_persistence_active_uses_full_snapshot_not_partial_fields():
    """`_persistence_active=True`(즉 `_restore_state()`가 이미 돌아 `_state`가
    진짜 데이터를 담고 있음) 일 때는 전체 스냅샷 `_persist_state()`를 쓰고,
    부분 RMW `_persist_fields()`는 쓰지 않는다.

    리뷰 지적: 기존 5개 테스트는 픽스처가 `_persistence_active = False`로
    고정돼 있어 이 분기(`coordinator.py`의 `if self._persistence_active:`
    True 쪽)가 한 번도 실행되지 않았다 -- 방향이 맞다는 것을 소스 대조로만
    확인했지 테스트로 지키지는 못했다. 2026-07-29에 실제로 사고가 난 것이
    정확히 이 분기라 지금 계좌의 실 포지션 6종을 지킨다.
    """
    c = _coord()
    c._persistence_active = True
    c._persist_state = AsyncMock()
    c._persist_fields = AsyncMock()
    with patch("services.trading.coordinator.get_settings") as gs, \
         patch("services.trading.regime_judge.get_effective_target",
               AsyncMock(return_value=0.55)):
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        out = await c.apply_regime_slots()
    assert out == {"max_open_positions": 11, "max_single_position_pct": 0.05}
    c._persist_state.assert_awaited_once()
    c._persist_fields.assert_not_called()


@pytest.mark.asyncio
async def test_persistence_inactive_uses_partial_fields_not_full_snapshot():
    """`_persistence_active=False`(이 프로세스에서 `start()`를 거친 적 없어
    `_state`가 빈 기본값) 일 때는 부분 RMW `_persist_fields()`만 쓰고,
    전체 스냅샷 `_persist_state()`는 쓰지 않는다.

    반대 방향으로 뒤집으면 빈 `_state`가 블롭의 실 데이터(포지션·손절가
    포함)를 덮어쓴다 -- 2026-07-29 사고 그 자체.
    """
    c = _coord()
    assert c._persistence_active is False
    c._persist_state = AsyncMock()
    c._persist_fields = AsyncMock()
    with patch("services.trading.coordinator.get_settings") as gs, \
         patch("services.trading.regime_judge.get_effective_target",
               AsyncMock(return_value=0.55)):
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        out = await c.apply_regime_slots()
    assert out == {"max_open_positions": 11, "max_single_position_pct": 0.05}
    c._persist_fields.assert_awaited_once_with(
        risk_params=c.risk_params.model_dump()
    )
    c._persist_state.assert_not_called()
