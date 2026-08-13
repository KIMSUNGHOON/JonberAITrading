"""Risk Monitor — pending_alerts dedup by (ticker, alert_type).

Root cause (monitoring-cadence-tuning arc, safety prerequisite): `_add_alert`
unconditionally appended every `action_required` alert to `_pending_alerts`
on each 1s monitor tick, and resolved alerts were never removed from that
list — it grew unbounded for the process lifetime (live `pending_alerts_count`
was observed at 1542). Tightening the monitor cadence would only make this
worse.

This suite pins the fix: an UNRESOLVED pending alert with the same
`(ticker, alert_type)` must not be duplicated — at most one such alert may
be pending at a time. A different `alert_type` for the same ticker is a
separate concern and must be kept separate. Once the prior alert for that
key is `resolved`, a fresh alert for the same key may be added again. The
full alert history (`_alerts`) is unaffected by dedup — every call must still
be recorded there.
"""

import pytest

from services.trading.models import AlertType, TradingAlert
from services.trading.risk_monitor import RiskMonitor


def _alert(ticker="005930", alert_type=AlertType.STOP_LOSS_TRIGGERED, alert_id=None, **kwargs):
    return TradingAlert(
        id=alert_id or f"alert-{ticker}-{alert_type}-{id(kwargs)}",
        alert_type=alert_type,
        ticker=ticker,
        title="Test Alert",
        message="test",
        action_required=True,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_duplicate_ticker_and_type_deduped_to_one_pending():
    monitor = RiskMonitor()

    await monitor._add_alert(_alert(alert_id="a1"))
    await monitor._add_alert(_alert(alert_id="a2"))
    await monitor._add_alert(_alert(alert_id="a3"))

    pending = monitor.get_pending_alerts()
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_same_ticker_different_alert_type_both_kept():
    monitor = RiskMonitor()

    await monitor._add_alert(
        _alert(alert_id="sl1", alert_type=AlertType.STOP_LOSS_TRIGGERED)
    )
    await monitor._add_alert(
        _alert(alert_id="tp1", alert_type=AlertType.TAKE_PROFIT_TRIGGERED)
    )

    pending = monitor.get_pending_alerts()
    assert len(pending) == 2
    assert {a.id for a in pending} == {"sl1", "tp1"}


@pytest.mark.asyncio
async def test_resolved_alert_allows_new_alert_for_same_key():
    monitor = RiskMonitor()

    await monitor._add_alert(_alert(alert_id="first"))
    monitor.resolve_alert("first")

    await monitor._add_alert(_alert(alert_id="second"))

    pending = monitor.get_pending_alerts()
    assert len(pending) == 1
    assert pending[0].id == "second"


@pytest.mark.asyncio
async def test_alert_history_records_every_call_regardless_of_dedup():
    monitor = RiskMonitor()

    await monitor._add_alert(_alert(alert_id="a1"))
    await monitor._add_alert(_alert(alert_id="a2"))
    await monitor._add_alert(_alert(alert_id="a3"))

    assert len(monitor._alerts) == 3
    assert [a.id for a in monitor._alerts] == ["a1", "a2", "a3"]
