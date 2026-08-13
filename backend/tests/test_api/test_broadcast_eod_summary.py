"""E3-3: `broadcast_eod_summary(digest, narrative)` WS notification.

Mirrors broadcast_trade_executed/broadcast_watch_added/broadcast_position_
event's TradeNotificationManager convention exactly (app/api/routes/
websocket.py) -- this is the SAME manager, just a new message `type`. No
mocking of the manager itself: subscribe a fake WebSocket the same way
`websocket_trade_notifications` does, call the real broadcast helper, and
assert on what actually arrived over the wire -- proving the FE contract
(type="eod_summary", data.trade_date/headline/has_narrative/timestamp)
end-to-end rather than just that some function got called.
"""

import pytest

from app.api.routes.websocket import (
    broadcast_eod_summary,
    trade_notification_manager,
)

pytestmark = pytest.mark.asyncio


class _FakeWebSocket:
    """Minimal stand-in matching TradeNotificationManager's usage: only
    send_json is called (subscribe()/accept() aren't exercised here since
    we register directly into .subscribers, mirroring how the manager's
    own broadcast() iterates that set)."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, message: dict):
        self.sent.append(message)


@pytest.fixture(autouse=True)
def _clean_subscribers():
    """TradeNotificationManager is a module-level singleton -- isolate each
    test's subscriber set so broadcasts from one test can't leak into
    another."""
    trade_notification_manager.subscribers.clear()
    yield
    trade_notification_manager.subscribers.clear()


_DIGEST = {
    "trade_date": "2026-07-17",
    "watch": [],
    "account": {
        "deposit": 10_000_000,
        "total_equity": 52_000_000,
        "daily_realized_pnl": 350_000,
        "cumulative_return_pct": 4.2,
    },
    "holdings": [],
    "strategy": None,
    "regime": {"label": "risk_on", "index_kospi_chg_pct": 0.8, "index_kosdaq_chg_pct": 1.1},
}


async def test_broadcast_eod_summary_shape_and_headline():
    ws = _FakeWebSocket()
    trade_notification_manager.subscribers.add(ws)

    await broadcast_eod_summary(_DIGEST, narrative="오늘 요약 브리핑")

    assert len(ws.sent) == 1
    message = ws.sent[0]
    assert message["type"] == "eod_summary"

    data = message["data"]
    assert data["trade_date"] == "2026-07-17"
    assert data["has_narrative"] is True
    assert "timestamp" in data
    # Headline carries the key figures, human-readable.
    assert "350,000" in data["headline"]
    assert "52,000,000" in data["headline"]
    assert "risk_on" in data["headline"]


async def test_broadcast_eod_summary_no_narrative_sets_has_narrative_false():
    ws = _FakeWebSocket()
    trade_notification_manager.subscribers.add(ws)

    await broadcast_eod_summary(_DIGEST, narrative=None)

    data = ws.sent[0]["data"]
    assert data["has_narrative"] is False


async def test_broadcast_eod_summary_blank_narrative_treated_as_absent():
    ws = _FakeWebSocket()
    trade_notification_manager.subscribers.add(ws)

    await broadcast_eod_summary(_DIGEST, narrative="   ")

    data = ws.sent[0]["data"]
    assert data["has_narrative"] is False


async def test_broadcast_eod_summary_empty_digest_headline_falls_back():
    ws = _FakeWebSocket()
    trade_notification_manager.subscribers.add(ws)

    empty_digest = {"trade_date": None, "watch": [], "account": {}, "holdings": [], "strategy": None, "regime": None}
    await broadcast_eod_summary(empty_digest, narrative=None)

    data = ws.sent[0]["data"]
    assert data["headline"] == "데이터 없음"
    assert data["trade_date"] is None


async def test_broadcast_eod_summary_no_subscribers_does_not_raise():
    # No subscriber added -- must be a safe no-op, matching every other
    # broadcast_* helper's early-return on an empty subscriber set.
    await broadcast_eod_summary(_DIGEST, narrative="x")
