"""E2-2: 장외에는 RiskMonitor의 1s 포지션 감시 사이클이 no-op이어야 한다.

Spec: docs/superpowers/specs/2026-07-17-three-issues-design.md §2 (E2-2)
Task: .superpowers/sdd/task-E2-2-brief.md

Gate point: `RiskMonitor._check_all_positions` — the per-cycle work body
that `_monitor_loop` calls before its 1s `asyncio.sleep` (the `while
self._running: ... asyncio.sleep(1) ... except CancelledError` loop
structure itself is unchanged per the brief; only the work body is gated,
same as E2-1's `PositionManager._check_all_positions`). Follows the
direct-RiskMonitor instantiation pattern already used by
test_risk_monitor_sudden_move.py (no full ExecutionCoordinator needed) and
the same no-op-cycle + transition-only-log pattern landed in E2-1
(`services/agent_chat/coordinator.py`, `services/agent_chat/
position_manager.py`): a monotonic-TTL cache
(`market_hours.is_krx_open_cached`) gates the cycle's work, with a
transition-only log helper (`_log_market_gate_once`) duplicated per-file by
design (YAGNI, not worth a shared util for a handful of call sites).

RiskMonitor has no heartbeat/liveness-tick recording of its own (verified:
no `_last_tick`-style field), so there is no ordering constraint on where
the gate sits relative to one — it can sit at the very head of the cycle's
work body.
"""
import logging

import pytest

from services.trading.models import ManagedPosition, RiskParameters, StopLossMode
from services.trading.risk_monitor import RiskMonitor

pytestmark = pytest.mark.asyncio


def _position(ticker="005930", avg_price=70_000.0, stop_loss=65_000.0, quantity=10):
    return ManagedPosition(
        ticker=ticker,
        stock_name=ticker,
        quantity=quantity,
        avg_price=avg_price,
        current_price=avg_price,
        stop_loss=stop_loss,
        stop_loss_mode=StopLossMode.AGENT_AUTO,
    )


def _monitor(**risk_kwargs):
    return RiskMonitor(risk_params=RiskParameters(**risk_kwargs))


@pytest.fixture
def closed_market(monkeypatch):
    import services.trading.risk_monitor as rm_mod
    monkeypatch.setattr(rm_mod, "is_krx_open_cached", lambda: False)


@pytest.fixture
def open_market(monkeypatch):
    import services.trading.risk_monitor as rm_mod
    monkeypatch.setattr(rm_mod, "is_krx_open_cached", lambda: True)


def _spy_check_position(monitor):
    """Replace `_check_position` with a spy recording every ticker it was
    called for, standing in for the real price-fetch entry point (parallel
    to E2-1's `_update_prices_spy` in test_afterhours_gate.py)."""
    checked = []

    async def _spy(ticker, config):
        checked.append(ticker)

    monitor._check_position = _spy
    return checked


async def test_check_all_positions_noop_when_closed(closed_market):
    """장 닫힘이면 _check_all_positions가 어떤 포지션의 가격도 조회하지 않고
    조기 반환한다."""
    monitor = _monitor()
    monitor.add_position(_position())
    checked = _spy_check_position(monitor)

    await monitor._check_all_positions()

    assert checked == []


async def test_check_all_positions_checks_every_ticker_when_open(open_market):
    """열림이면 기존 경로 그대로 진입 — 감시 중인 모든 종목이 조회된다(회귀)."""
    monitor = _monitor()
    monitor.add_position(_position(ticker="005930"))
    monitor.add_position(_position(ticker="000660"))
    checked = _spy_check_position(monitor)

    await monitor._check_all_positions()

    assert set(checked) == {"005930", "000660"}


async def test_gate_transition_logged_once_not_every_tick(closed_market, caplog):
    """상태 전이 시에만 1회 로그 — 1s 루프에서 매 틱 로그 스팸 방지."""
    monitor = _monitor()
    monitor.add_position(_position())

    with caplog.at_level(logging.INFO, logger="services.trading.risk_monitor"):
        await monitor._check_all_positions()
        await monitor._check_all_positions()
        await monitor._check_all_positions()

    gate_logs = [r for r in caplog.records if "market_gate" in r.getMessage()]
    assert len(gate_logs) == 1


async def test_gate_reopen_logged_once_on_transition(open_market, caplog):
    """닫힘→열림 전이도 1회만 로그된다 (재전이 시 재로그 확인)."""
    monitor = _monitor()
    monitor.add_position(_position())
    monitor._market_gate_closed = True  # simulate prior closed state

    with caplog.at_level(logging.INFO, logger="services.trading.risk_monitor"):
        await monitor._check_all_positions()
        await monitor._check_all_positions()

    gate_logs = [r for r in caplog.records if "market_gate" in r.getMessage()]
    assert len(gate_logs) == 1
