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
