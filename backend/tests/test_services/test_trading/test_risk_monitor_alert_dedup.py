"""G-2 (gap discipline, 2026-07-20): false "Executed" alert squash + coordinator
`_state.pending_alerts` dedup.

Background (spec docs/superpowers/specs/2026-07-20-gap-discipline-design.md
§N2, real incident): `RiskMonitor._execute_stop_loss`/`_execute_take_profit`
called `coordinator._execute_order_from_monitor` (which returned nothing) and
then generated a "Stop-Loss Executed"/"Take-Profit Executed" ORDER_FILLED
alert UNCONDITIONALLY -- even when the autonomy gate denied the sell or a
concurrent in-flight guard skipped it (both silent no-ops at the
coordinator). Under `/halt` (or any persistent gate denial) with price still
past the stop, this fired a FALSE "Executed" notification on every 1s
monitor tick, and `coordinator._on_alert` appended every one of them to
`_state.pending_alerts` with no dedup -- unbounded growth for as long as the
denial persisted.

This file exercises the fix end-to-end through the REAL
`ExecutionCoordinator` + `RiskMonitor` wiring (as opposed to
test_risk_monitor_defensive_market_order.py's direct-RiskMonitor unit tests
of the same fix, and test_r5_p0_autotrade_safety.py's direct
`_execute_order_from_monitor` bool-return tests) -- i.e. the actual
`order_executor=self._execute_order_from_monitor` /
`alert_sender=self._on_alert` callables the coordinator wires into
`RiskMonitor.__init__` (coordinator.py `ExecutionCoordinator.__init__`).
"""

import asyncio

import pytest
import pytest_asyncio

import services.autonomy as autonomy_pkg
import services.storage_service as ss
from services.autonomy import GateDecision
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import (
    AlertType,
    ManagedPosition,
    StopLossMode,
    TradingAlert,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _isolated_storage(tmp_path, monkeypatch):
    """Same isolation as test_r5_p0_autotrade_safety.py -- none of these
    tests call coordinator.start(), so _schedule_persist is a no-op
    regardless (`_persistence_active` stays False), but this keeps the file
    consistent with sibling ExecutionCoordinator-based test modules and
    guarantees the real data/storage.db is never touched even if that
    invariant ever changes."""
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


def _coordinator_with_watched_position() -> ExecutionCoordinator:
    """A coordinator with one AGENT_AUTO position tracked + watched by its
    OWN RiskMonitor -- same shape as test_r5_p0_autotrade_safety.py's helper
    of the same name, duplicated locally to keep this file self-contained."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    position = ManagedPosition(
        ticker="005930",
        stock_name="삼성전자",
        quantity=10,
        avg_price=72_500,
        current_price=68_000,
        stop_loss=68_000,
        take_profit=79_750,
        stop_loss_mode=StopLossMode.AGENT_AUTO,
    )
    coord._add_position(position)
    return coord


# -------------------------------------------
# ① deny gate -> zero false "Executed" alerts + exactly one gate-denied
# notice, through the REAL RiskMonitor -> _execute_order_from_monitor ->
# _on_alert wiring.
# -------------------------------------------


async def test_deny_gate_no_false_executed_alert_via_real_wiring(monkeypatch):
    coord = _coordinator_with_watched_position()
    config = coord.risk_monitor._watching["005930"]

    async def deny_gate(market, **kwargs):
        return GateDecision(allowed=False, reason="trading_mode:kiwoom is 'hitl'", check="market_mode")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", deny_gate)

    notices = []

    async def spy_notify(order, gate_reason):
        notices.append(order.ticker)

    coord._notify_monitor_gate_denied = spy_notify

    # Three ticks below the stop, denied every time (position never gets
    # removed from watching since nothing was actually sold).
    await coord.risk_monitor._execute_stop_loss("005930", config, 67_000)
    await coord.risk_monitor._execute_stop_loss("005930", config, 67_000)
    await coord.risk_monitor._execute_stop_loss("005930", config, 67_000)

    executed = [
        a for a in coord._state.pending_alerts if a.alert_type == AlertType.ORDER_FILLED
    ]
    assert executed == [], "gate-denied ticks must never produce a false Executed alert"
    assert notices == ["005930"], "gate-denied notice must fire exactly once per episode"


async def test_inflight_skip_no_false_executed_alert_via_real_wiring(monkeypatch):
    """②: a second RiskMonitor-triggered execution for the same ticker while
    the first is still in flight (S-2's `_acquire_defensive_exit_guard`)
    must also produce zero false Executed alerts for the skipped call."""
    coord = _coordinator_with_watched_position()
    config = coord.risk_monitor._watching["005930"]

    entered = asyncio.Event()
    hold = asyncio.Event()

    async def slow_execute(order):
        entered.set()
        await hold.wait()
        from services.trading.models import OrderResult

        return OrderResult(
            order_id="o1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=order.price or 68_000,
            status="filled",
        )

    coord._execute_order = slow_execute

    async def allow_gate(market, **kwargs):
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

    task1 = asyncio.create_task(
        coord.risk_monitor._execute_stop_loss("005930", config, 67_000)
    )
    await entered.wait()

    # Second trigger arrives while the first is still awaiting its broker
    # call -- must be skipped as a no-op, no false alert.
    await coord.risk_monitor._execute_stop_loss("005930", config, 67_000)

    hold.set()
    await task1

    executed = [
        a for a in coord._state.pending_alerts if a.alert_type == AlertType.ORDER_FILLED
    ]
    # Exactly ONE real Executed alert (from the first, non-skipped call) --
    # not two, not zero.
    assert len(executed) == 1


# -------------------------------------------
# ③ gate allows -> the existing Executed alert is byte-unchanged, through
# the real wiring.
# -------------------------------------------


async def test_gate_allowed_executed_alert_unchanged_via_real_wiring(monkeypatch):
    coord = _coordinator_with_watched_position()
    config = coord.risk_monitor._watching["005930"]

    async def executor(order):
        from services.trading.models import OrderResult

        return OrderResult(
            order_id="o1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=order.price or 68_000,
            status="filled",
        )

    coord._execute_order = executor

    async def allow_gate(market, **kwargs):
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

    await coord.risk_monitor._execute_stop_loss("005930", config, 67_000)

    executed = [
        a for a in coord._state.pending_alerts if a.alert_type == AlertType.ORDER_FILLED
    ]
    assert len(executed) == 1
    assert executed[0].title == "Stop-Loss Executed: 005930"
    assert executed[0].message == "Sold 10 shares at ₩67,000"
    assert executed[0].action_required is False


# -------------------------------------------
# ④ coordinator._on_alert: dedup pending_alerts by (ticker, alert_type)
# while unresolved; a fresh alert for the same key may append again once
# the prior one resolves.
# -------------------------------------------


def _alert(alert_id: str, ticker="005930", alert_type=AlertType.ORDER_FILLED) -> TradingAlert:
    return TradingAlert(
        id=alert_id,
        alert_type=alert_type,
        ticker=ticker,
        title="t",
        message="m",
    )


async def test_on_alert_dedup_skips_duplicate_unresolved():
    coord = ExecutionCoordinator(kiwoom_client=None)

    await coord._on_alert(_alert("a1"))
    await coord._on_alert(_alert("a2"))

    matching = [
        a for a in coord._state.pending_alerts
        if a.ticker == "005930" and a.alert_type == AlertType.ORDER_FILLED
    ]
    assert len(matching) == 1, "a second unresolved duplicate must not be appended"
    assert matching[0].id == "a1", "the FIRST (still unresolved) entry is kept, not replaced"


async def test_on_alert_dedup_allows_reappend_after_resolved():
    coord = ExecutionCoordinator(kiwoom_client=None)

    alert1 = _alert("a1")
    await coord._on_alert(alert1)

    # Resolve the first entry (mirrors handle_alert_action's resolution
    # convention -- setting .resolved on the object already sitting in
    # _state.pending_alerts).
    alert1.resolved = True

    await coord._on_alert(_alert("a2"))

    matching = [
        a for a in coord._state.pending_alerts
        if a.ticker == "005930" and a.alert_type == AlertType.ORDER_FILLED
    ]
    ids = {a.id for a in matching}
    assert "a2" in ids, "a fresh alert for the same key must append once the prior one resolved"
    assert len(matching) == 2, "the resolved original is not removed, just no longer blocks appends"


async def test_on_alert_dedup_is_scoped_to_ticker_and_type():
    """A different ticker, or a different alert_type for the SAME ticker,
    must not be deduped against each other -- only an exact (ticker,
    alert_type) match with an unresolved entry blocks the append."""
    coord = ExecutionCoordinator(kiwoom_client=None)

    await coord._on_alert(_alert("a1", ticker="005930", alert_type=AlertType.ORDER_FILLED))
    await coord._on_alert(_alert("a2", ticker="000660", alert_type=AlertType.ORDER_FILLED))
    await coord._on_alert(_alert("a3", ticker="005930", alert_type=AlertType.STOP_LOSS_TRIGGERED))

    ids = {a.id for a in coord._state.pending_alerts}
    assert ids == {"a1", "a2", "a3"}, "distinct (ticker, alert_type) keys must not dedup each other"
