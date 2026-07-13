"""
Pending Order Tracker

Pure-logic tracker for orders that have been placed but are not yet (fully)
filled. ka10076 (체결내역) returns a cumulative daily snapshot per order, not
incremental fills — so `apply_fills` must diff each new snapshot against the
order's own accumulated `filled_quantity`/`filled_amount` and emit only the
NEW portion. Re-applying the exact same snapshot must therefore emit nothing
(idempotent), which is the property later callers (the trading coordinator,
fill notifications, stop/take-profit registration) depend on to avoid
double-counting a fill that was already processed.

No I/O here — persistence (`to_payload`/`from_payload`) and wiring into the
coordinator's poll loop are handled by later tasks.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from services.kiwoom.models import FilledOrder


class TrackedOrderStatus(str, Enum):
    """Lifecycle of a tracked order."""

    TRACKING = "tracking"    # Placed, waiting for (more) fills
    FILLED = "filled"        # filled_quantity reached total_quantity
    EXPIRED = "expired"      # Stale — dropped by expire_stale without a fill
    CANCELLED = "cancelled"  # Cancelled before fully filling


class TrackedOrder(BaseModel):
    """A pending order being watched for fills via ka10076 snapshots."""

    model_config = ConfigDict(use_enum_values=True)

    ord_no: str
    ticker: str
    stock_name: str = ""
    side: str  # "buy" | "sell"
    total_quantity: int
    filled_quantity: int = 0
    # Cumulative filled amount (KRW) behind filled_quantity — internal
    # bookkeeping only, used to derive each new snapshot's weighted-average
    # fill price (see PendingOrderTracker.apply_fills). Serialized so a
    # restart doesn't lose the basis for that calculation mid-fill.
    filled_amount: float = 0
    limit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    source_queue_id: Optional[str] = None
    source_session_id: Optional[str] = None
    placed_at: datetime = Field(default_factory=datetime.now)
    trade_date: str = ""  # YYYYMMDD local
    status: TrackedOrderStatus = TrackedOrderStatus.TRACKING


class FillDelta(BaseModel):
    """The NEW portion of a fill discovered by a single apply_fills() call."""

    order: TrackedOrder
    new_fill_qty: int
    avg_fill_price: float


class PendingOrderTracker:
    """In-memory registry of TrackedOrders with diff-based fill application.

    Pure logic — no I/O, no locking. Callers own persistence and concurrency.
    """

    def __init__(self) -> None:
        self._orders: dict[str, TrackedOrder] = {}

    def register(self, order: TrackedOrder) -> None:
        """Start tracking an order. A duplicate ord_no is ignored — the first
        registration wins, since a later re-register would otherwise reset
        filled_quantity/filled_amount and break the fill diff."""
        if order.ord_no in self._orders:
            return
        self._orders[order.ord_no] = order

    def tracking(self) -> list[TrackedOrder]:
        """Orders still awaiting (more) fills."""
        return [
            o for o in self._orders.values()
            if o.status == TrackedOrderStatus.TRACKING
        ]

    def apply_fills(self, fills: list[FilledOrder]) -> list[FillDelta]:
        """Diff a ka10076 snapshot against tracked orders.

        `fills` is treated as the current cumulative-for-today snapshot per
        order (ka10076 semantics, not an incremental fill stream). For each
        TRACKING order with matching ord_no fills: sum the snapshot's
        ccld_qty/ccld_amt, subtract what was already applied
        (filled_quantity/filled_amount), and emit a FillDelta only for the
        remainder. The new portion's average price is
        (snapshot_amount - previous filled_amount) / new_qty — the snapshot
        already reflects the true cumulative average, so this recovers the
        weighted average of just the unseen fills without needing to have
        kept per-fill prices.

        Re-applying an identical snapshot yields new_qty <= 0 for every
        order, so nothing is emitted (idempotent).
        """
        by_order: dict[str, list[FilledOrder]] = {}
        for fill in fills:
            by_order.setdefault(fill.ord_no, []).append(fill)

        deltas: list[FillDelta] = []
        for ord_no, matching in by_order.items():
            order = self._orders.get(ord_no)
            if order is None or order.status != TrackedOrderStatus.TRACKING:
                continue

            snapshot_qty = sum(f.ccld_qty for f in matching)
            snapshot_amount = sum(f.ccld_qty * f.ccld_uv for f in matching)
            new_qty = snapshot_qty - order.filled_quantity
            if new_qty <= 0:
                continue

            new_amount = snapshot_amount - order.filled_amount
            avg_price = new_amount / new_qty

            order.filled_quantity = snapshot_qty
            order.filled_amount = snapshot_amount
            if order.filled_quantity >= order.total_quantity:
                order.status = TrackedOrderStatus.FILLED

            deltas.append(
                FillDelta(order=order, new_fill_qty=new_qty, avg_fill_price=avg_price)
            )

        return deltas

    def expire_stale(self, today: Optional[str]) -> list[TrackedOrder]:
        """Expire TRACKING orders that are stale.

        today=YYYYMMDD: expire only orders whose trade_date differs (carried
        over from a prior session, e.g. re-registered on startup).
        today=None: the market-close convention — expire every TRACKING
        order regardless of trade_date, since nothing placed today can fill
        any further once the market has closed.
        """
        expired: list[TrackedOrder] = []
        for order in self._orders.values():
            if order.status != TrackedOrderStatus.TRACKING:
                continue
            if today is not None and order.trade_date == today:
                continue
            order.status = TrackedOrderStatus.EXPIRED
            expired.append(order)
        return expired

    def to_payload(self) -> list[dict]:
        """JSON-safe snapshot of every tracked order (any status), for
        persistence by the caller."""
        return [o.model_dump(mode="json") for o in self._orders.values()]

    @classmethod
    def from_payload(cls, raw: list[dict]) -> "PendingOrderTracker":
        """Rebuild a tracker from a to_payload() snapshot."""
        tracker = cls()
        for item in raw:
            order = TrackedOrder.model_validate(item)
            tracker._orders[order.ord_no] = order
        return tracker
