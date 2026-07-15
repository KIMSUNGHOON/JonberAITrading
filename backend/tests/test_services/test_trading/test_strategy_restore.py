"""Phase3 T5a: strategy restore on restart — the active-revision pointer is
the single source of truth; a corrupt/missing pointer or row starts clean
(best-effort, mirrors _restore_state's contract).

Coordinator construction follows the neighboring persistence-test convention
(tests/test_services/test_trading/test_watch_list_persistence.py): bare
``ExecutionCoordinator(kiwoom_client=None)`` — no broker calls are made by
``_restore_strategy``, so a mock broker isn't needed.

Patch target note: ``_restore_strategy`` (like ``_restore_state`` before it)
does its ``get_storage_service`` import LOCALLY inside the method body
(``from services.storage_service import get_storage_service``), which
re-fetches the name from ``services.storage_service`` at call time. Patching
``services.trading.coordinator.get_storage_service`` (a module-level
attribute) would NOT be seen by that local import — only patching the
attribute at its source, ``services.storage_service.get_storage_service``,
takes effect. Verified by reading coordinator.py's existing
``_restore_state`` (same local-import pattern) before writing these tests.
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.storage_service import StorageService
from services.trading.coordinator import ExecutionCoordinator
from services.trading.strategy import TradingStrategy
from services.trading.strategy_orchestrator import ACTIVE_STRATEGY_REVISION_KEY

pytestmark = pytest.mark.asyncio


def _make_coordinator() -> ExecutionCoordinator:
    """Mirrors test_watch_list_persistence.py's bare-construction convention —
    ``_restore_strategy`` never touches the broker, so kiwoom_client=None."""
    return ExecutionCoordinator(kiwoom_client=None)


async def _seed_active_revision(storage, strategy: TradingStrategy) -> str:
    rid = "rev-restore-1"
    await storage.save_strategy_revision({
        "id": rid, "trade_date": "2026-07-15", "source": "eod_consensus",
        "stance": "defensive", "consensus_level": 0.8, "changed": 1,
        "strategy_json": strategy.model_dump_json(),
        "parent_revision_id": None, "rationale": "seed",
        "votes_json": None, "regime_snapshot_id": None,
    })
    await storage.set_app_setting(ACTIVE_STRATEGY_REVISION_KEY, rid)
    return rid


async def test_restore_strategy_applies_pointed_revision(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    saved = TradingStrategy(name="복원 전략")
    saved.exit_conditions.stop_loss_pct = 0.05
    await _seed_active_revision(storage, saved)
    coordinator = _make_coordinator()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coordinator._restore_strategy()

    restored = coordinator.get_strategy()
    assert restored is not None and restored.name == "복원 전략"
    assert restored.exit_conditions.stop_loss_pct == pytest.approx(0.05)


async def test_restore_no_pointer_or_empty_is_clean_start(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coordinator = _make_coordinator()
    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coordinator._restore_strategy()          # 포인터 없음
        assert coordinator.get_strategy() is None
        await storage.set_app_setting(ACTIVE_STRATEGY_REVISION_KEY, "")
        await coordinator._restore_strategy()          # 빈 센티널(DELETE 후)
        assert coordinator.get_strategy() is None


async def test_restore_corrupt_json_never_raises(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await storage.save_strategy_revision({
        "id": "rev-bad", "trade_date": "2026-07-15", "source": "manual",
        "stance": None, "consensus_level": None, "changed": 0,
        "strategy_json": "{not json", "parent_revision_id": None,
        "rationale": None, "votes_json": None, "regime_snapshot_id": None,
    })
    await storage.set_app_setting(ACTIVE_STRATEGY_REVISION_KEY, "rev-bad")
    coordinator = _make_coordinator()
    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coordinator._restore_strategy()  # raise 없이 클린 스타트
    assert coordinator.get_strategy() is None


def test_start_calls_restore_strategy_after_restore_state():
    import inspect

    from services.trading.coordinator import ExecutionCoordinator

    source = inspect.getsource(ExecutionCoordinator.start)
    assert "_restore_strategy(" in source
    assert source.index("_restore_state(") < source.index("_restore_strategy(")
