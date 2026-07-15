"""Phase3 T4: strategy consensus orchestrator — the never-raise EOD chain
step: context -> panel -> consensus -> deterministic apply -> revision +
active pointer -> coordinator.set_strategy. Plus the coordinator
market-close wiring pin (inspect.getsource, mirroring
test_eod_orchestrator.py:227's convention).
"""

import inspect
import json
from unittest.mock import AsyncMock

import pytest

from services.storage_service import StorageService
from services.trading import strategy_orchestrator
from services.trading.strategy import TradingStrategy
from services.trading.strategy_orchestrator import (
    ACTIVE_STRATEGY_REVISION_KEY,
    run_strategy_consensus,
)

pytestmark = pytest.mark.asyncio

_TRADE_DATE = "2026-07-15"


class _StubCoordinator:
    def __init__(self, strategy=None):
        self._strategy = strategy
        self.set_calls = []

    def get_strategy(self):
        return self._strategy

    def set_strategy(self, strategy):
        self._strategy = strategy
        self.set_calls.append(strategy)


def _votes(stance="defensive", n=3):
    return [
        {"panelist": f"p{i}", "stance": stance, "confidence": 0.8,
         "reasoning": "r", "key_factors": [],
         "adjustments": {"stop_loss_pct": 0.06}}
        for i in range(n)
    ]


async def _seed_review(storage):
    await storage.save_eod_review({
        "trade_date": _TRADE_DATE,
        "report_json": json.dumps({
            "trade_date": _TRADE_DATE,
            "portfolio": {"equity": 1.0, "net_pnl": 0.0},
            "per_stock": [], "agents": [], "regime": {},
        }),
    })


async def test_consensus_reached_full_chain(tmp_path, monkeypatch):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_review(storage)
    coordinator = _StubCoordinator(strategy=TradingStrategy())
    monkeypatch.setattr(
        strategy_orchestrator, "run_strategy_panel", AsyncMock(return_value=_votes())
    )

    result = await run_strategy_consensus(coordinator, storage, _TRADE_DATE)

    assert result["ok"] is True
    assert result["stance"] == "defensive"
    assert result["changed"] is True
    rows = await storage.get_strategy_revisions()
    assert len(rows) == 1 and rows[0]["id"] == result["revision_id"]
    assert rows[0]["source"] == "eod_consensus"
    pointer = await storage.get_app_setting(ACTIVE_STRATEGY_REVISION_KEY)
    assert pointer == result["revision_id"]
    assert len(coordinator.set_calls) == 1
    applied = coordinator.set_calls[0]
    assert applied.exit_conditions.stop_loss_pct == pytest.approx(0.06)
    # revision의 strategy_json == 적용된 전략 (포인터 불변식)
    assert json.loads(rows[0]["strategy_json"])["id"] == applied.id == result["revision_id"]


async def test_no_change_with_current_records_but_skips_apply(tmp_path, monkeypatch):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_review(storage)
    current = TradingStrategy()
    coordinator = _StubCoordinator(strategy=current)
    # 3-way split → no_change
    votes = [
        {"panelist": "a", "stance": "defensive", "confidence": 0.8, "reasoning": "r"},
        {"panelist": "b", "stance": "neutral", "confidence": 0.8, "reasoning": "r"},
        {"panelist": "c", "stance": "aggressive", "confidence": 0.8, "reasoning": "r"},
    ]
    monkeypatch.setattr(
        strategy_orchestrator, "run_strategy_panel", AsyncMock(return_value=votes)
    )

    result = await run_strategy_consensus(coordinator, storage, _TRADE_DATE)

    assert result["ok"] is True and result["stance"] == "no_change"
    assert result["changed"] is False
    rows = await storage.get_strategy_revisions()
    assert len(rows) == 1 and rows[0]["changed"] == 0
    assert json.loads(rows[0]["strategy_json"])["name"] == current.name
    assert await storage.get_app_setting(ACTIVE_STRATEGY_REVISION_KEY) == rows[0]["id"]
    assert coordinator.set_calls == []  # 내용 동일 → 재적용 생략


async def test_no_change_without_current_skips_everything(tmp_path, monkeypatch):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_review(storage)
    coordinator = _StubCoordinator(strategy=None)
    monkeypatch.setattr(
        strategy_orchestrator, "run_strategy_panel",
        AsyncMock(return_value=_votes(n=1)),  # 1표 → min_valid 미달
    )

    result = await run_strategy_consensus(coordinator, storage, _TRADE_DATE)

    assert result["ok"] is False
    assert result["reason"] == "no_consensus_no_current"
    assert await storage.get_strategy_revisions() == []
    assert await storage.get_app_setting(ACTIVE_STRATEGY_REVISION_KEY) is None


async def test_consensus_bootstraps_default_baseline_when_no_current(tmp_path, monkeypatch):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_review(storage)
    coordinator = _StubCoordinator(strategy=None)
    monkeypatch.setattr(
        strategy_orchestrator, "run_strategy_panel", AsyncMock(return_value=_votes())
    )

    result = await run_strategy_consensus(coordinator, storage, _TRADE_DATE)

    assert result["ok"] is True and result["changed"] is True
    assert len(coordinator.set_calls) == 1  # 기본 TradingStrategy() 베이스라인에서 적응


async def test_disabled_gate_skips(tmp_path, monkeypatch):
    from app.config import get_settings

    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_review(storage)
    coordinator = _StubCoordinator(strategy=TradingStrategy())
    monkeypatch.setattr(get_settings(), "STRATEGY_CONSENSUS_ENABLED", False)
    panel = AsyncMock(return_value=_votes())
    monkeypatch.setattr(strategy_orchestrator, "run_strategy_panel", panel)

    result = await run_strategy_consensus(coordinator, storage, _TRADE_DATE)

    assert result["ok"] is False and result["reason"] == "disabled"
    panel.assert_not_awaited()
    # force=True는 게이트 우회 (수동 트리거 경로)
    result = await run_strategy_consensus(coordinator, storage, _TRADE_DATE, force=True)
    assert result["ok"] is True


async def test_missing_context_skips(tmp_path, monkeypatch):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))  # eod_review 없음
    coordinator = _StubCoordinator(strategy=TradingStrategy())
    panel = AsyncMock(return_value=_votes())
    monkeypatch.setattr(strategy_orchestrator, "run_strategy_panel", panel)

    result = await run_strategy_consensus(coordinator, storage, _TRADE_DATE)

    assert result["ok"] is False and result["reason"] == "no_context"
    panel.assert_not_awaited()


async def test_panel_timeout_is_failure_harmless(tmp_path, monkeypatch):
    import asyncio

    from app.config import get_settings

    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_review(storage)
    coordinator = _StubCoordinator(strategy=TradingStrategy())
    monkeypatch.setattr(get_settings(), "STRATEGY_CONSENSUS_TIMEOUT_SECONDS", 0.05)

    async def _slow_panel(context):
        await asyncio.sleep(1.0)

    monkeypatch.setattr(strategy_orchestrator, "run_strategy_panel", _slow_panel)

    result = await run_strategy_consensus(coordinator, storage, _TRADE_DATE)

    assert result["ok"] is False and result["reason"] == "timeout"
    assert coordinator.set_calls == []


async def test_any_exception_never_raises(tmp_path, monkeypatch):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_review(storage)
    coordinator = _StubCoordinator(strategy=TradingStrategy())
    monkeypatch.setattr(
        strategy_orchestrator, "run_strategy_panel",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    result = await run_strategy_consensus(coordinator, storage, _TRADE_DATE)

    assert result["ok"] is False and "boom" in (result["reason"] or "")


def test_coordinator_close_edge_calls_strategy_consensus_after_eod_review():
    """Phase2 핀 테스트(test_eod_orchestrator.py:227) 관례 미러 —
    run_eod_review 뒤(같은 마감엣지 분기 안)에 run_strategy_consensus."""
    from services.trading.coordinator import ExecutionCoordinator

    source = inspect.getsource(ExecutionCoordinator._check_queue_on_market_open)
    assert "run_strategy_consensus(" in source
    assert source.index("run_eod_review(") < source.index("run_strategy_consensus(")
