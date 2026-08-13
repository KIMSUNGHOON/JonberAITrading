"""ExecutionCoordinator._add_position merge branch — final-review IMPORTANT
(I1, 2026-07-13).

The merge branch correctly folds an incoming tranche into `_state.positions`
(quantity summed, avg_price weighted), but registered the INCOMING DELTA
object with risk_monitor — RiskMonitor.add_position replaces WatchConfig
wholesale (services/trading/risk_monitor.py:126-148), so after several
incremental tranches the monitor watches only the LAST tranche's quantity
while the real position is the merged total. A stop-loss/take-profit trigger
would then sell only that last tranche instead of the whole position.
"""

from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import ManagedPosition


def _tranche(ticker="005930", quantity=48, avg_price=260000.0, **kw):
    return ManagedPosition(
        ticker=ticker,
        stock_name="삼성전자",
        quantity=quantity,
        avg_price=avg_price,
        current_price=avg_price,
        **kw,
    )


def test_incremental_tranches_watch_the_merged_quantity():
    """Three 48-share tranches (a 3-way split fill, F3's own live incident
    shape) must leave risk_monitor watching qty 144 — not 48."""
    coord = ExecutionCoordinator(kiwoom_client=None)

    coord._add_position(_tranche(quantity=48, avg_price=260000.0))
    coord._add_position(_tranche(quantity=48, avg_price=262000.0))
    coord._add_position(_tranche(quantity=48, avg_price=258000.0))

    state_position = coord._state.positions[0]
    assert state_position.quantity == 144

    watched = coord.risk_monitor._watching["005930"]
    assert watched.quantity == 144, (
        "risk_monitor is watching the last tranche's delta quantity, not "
        "the merged position — a stop trigger would only sell part of it"
    )
    # Weighted average of the three tranches.
    expected_avg = (48 * 260000.0 + 48 * 262000.0 + 48 * 258000.0) / 144
    assert watched.entry_price == expected_avg
    assert state_position.avg_price == expected_avg


def test_merge_keeps_existing_stops_when_delta_has_none():
    """A tranche fill usually carries no stop_loss/take_profit of its own —
    the existing position's stops must survive the merge and reach the
    monitor (not get wiped by the delta's None)."""
    coord = ExecutionCoordinator(kiwoom_client=None)

    coord._add_position(_tranche(
        quantity=48, avg_price=260000.0,
        stop_loss=246560.0, take_profit=289440.0,
    ))
    coord._add_position(_tranche(quantity=48, avg_price=262000.0))

    state_position = coord._state.positions[0]
    assert state_position.stop_loss == 246560.0
    assert state_position.take_profit == 289440.0

    watched = coord.risk_monitor._watching["005930"]
    assert watched.stop_loss == 246560.0
    assert watched.take_profit == 289440.0
    assert watched.quantity == 96


def test_merge_fills_stop_gap_from_incoming_delta():
    """If the EXISTING position has no stop yet but the incoming tranche
    does carry one, the gap is filled (existing's non-None values still
    win when both are set)."""
    coord = ExecutionCoordinator(kiwoom_client=None)

    coord._add_position(_tranche(quantity=48, avg_price=260000.0))
    coord._add_position(_tranche(
        quantity=48, avg_price=262000.0,
        stop_loss=246560.0, take_profit=289440.0,
    ))

    state_position = coord._state.positions[0]
    assert state_position.stop_loss == 246560.0
    assert state_position.take_profit == 289440.0

    watched = coord.risk_monitor._watching["005930"]
    assert watched.stop_loss == 246560.0
    assert watched.take_profit == 289440.0
