"""Task 3 (autonomous-sizing arc): risk_params SQLite persistence.

Positions/trade_queue/watch_list/daily_count/tracked_orders already survive a
restart via ``ExecutionCoordinator._persist_state`` / ``_restore_state``
(R5-P1 A4 + P2 SSOT prep) — but ``risk_params`` (sizing/gate knobs, now
including T1's ``max_trade_notional_pct``) was never included in that blob,
so a restart silently reverted any live risk-params tuning back to the
``RiskParameters()`` defaults.

``_restore_state`` must apply the restored risk_params IN-PLACE via
``setattr`` rather than rebinding ``self.risk_params`` — the same
``RiskParameters`` instance is reference-shared with ``PortfolioAgent``,
``RiskMonitor``, and ``TradingState`` (all captured in ``__init__``), so a
rebind would desync those holders from the coordinator's own copy.

Patch target note (mirrors test_strategy_restore.py, verified by reading
``_persist_state``/``_restore_state``): both do their
``get_storage_service`` import LOCALLY inside the method body, which
re-fetches the name from ``services.storage_service`` at call time —
patching ``services.storage_service.get_storage_service`` (the source) is
required; patching the coordinator module's copy would not be seen.
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.storage_service import StorageService
from services.trading.coordinator import ExecutionCoordinator

pytestmark = pytest.mark.asyncio


def _make_coordinator() -> ExecutionCoordinator:
    """Mirrors test_watch_list_persistence.py / test_strategy_restore.py's
    bare-construction convention — persist/restore never touch the broker."""
    return ExecutionCoordinator(kiwoom_client=None)


async def test_risk_params_survive_persist_restore(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    coord._persistence_active = True
    coord.risk_params.max_trade_notional_pct = 22.0
    ref = coord.risk_params  # reference identity check

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coord._persist_state()
        coord.risk_params.max_trade_notional_pct = 15.0  # restore must overwrite
        await coord._restore_state()

    assert coord.risk_params.max_trade_notional_pct == 22.0
    assert coord.risk_params is ref  # in-place, not rebound


async def test_restore_without_risk_params_key_leaves_defaults(tmp_path):
    """A blob persisted before this change (no 'risk_params' key) must not
    blow up restore — best-effort, same contract as the rest of the blob."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    coord._persistence_active = True

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        # Seed a pre-T3 blob shape directly (no risk_params key).
        import json
        await storage.set_app_setting(
            coord._STATE_KEY,
            json.dumps({
                "positions": [], "trade_queue": [], "watch_list": [],
                "daily_trades_count": 0, "daily_count_date": "2000-01-01",
                "tracked_orders": [],
            }),
        )
        default_value = coord.risk_params.max_trade_notional_pct
        await coord._restore_state()

    assert coord.risk_params.max_trade_notional_pct == default_value
