"""Broker-local reconciler (F3 t6).

Kiwoom's account balance (`get_account_balance().holdings`) is the single
source of truth for what is actually held. Two independent engines watch
positions locally — `ExecutionCoordinator` (stops, autonomous execution) and
the agent-chat `PositionManager` (group-chat monitoring, its own
`sync_from_account`) — and each can drift from the broker and from each
other: an order placed outside this reconcile pass, a race between
`PositionManager.sync_from_account` (absolute) and the fill-tracker's
incremental `register_fill_as_position` calls, or a sell executed from
another client entirely.

`reconcile(coordinator)` runs three passes every 2nd tick of the coordinator's
30s queue-scheduler loop (wired in coordinator.py):

1. **Orphan adoption** — a broker holding neither engine knows about gets
   registered. "Known" = coordinator ∪ PositionManager (decision 1: whichever
   side is missing it gets registered so both sides converge). Stop-loss/
   take-profit provenance is tried in order:
     ① the ticker's most recent FILLED `TrackedOrder` in the fill tracker
     ② the ticker's most recent COMPLETED BUY entry in the trade queue with a
        stop_loss set
     ③ a default stop computed from `RiskParameters.default_stop_loss_pct` /
        `default_take_profit_pct` off the broker's average price

   When PositionManager already has the ticker (its own `sync_from_account`
   can populate a holding the coordinator never placed an order for) we do
   NOT route through `register_fill_as_position`: that helper treats
   `quantity` as an INCREMENTAL delta on the PM side
   (`existing.quantity + quantity`), so passing the full holding quantity
   would double-count a PM position that already reflects it. Instead the
   coordinator is registered directly with the full quantity (it has nothing
   to sum against) and PM only gets its stop levels backfilled if it doesn't
   have any yet; quantity convergence for that ticker is handled uniformly by
   the quantity-fix pass below. Conversely, when the coordinator already
   knows a ticker and only PM is missing it, PM is backfilled directly from
   the coordinator's own (already-trusted) data — no provenance chain needed
   there, and nothing is double-counted since PM starts from nothing.

2. **External-close detection** — a ticker either engine is watching that no
   longer appears in the broker's holdings gets removed from both. Exception:
   if the fill tracker has a TRACKING sell order for that ticker, the zero
   holding may just be an in-flight sell not yet confirmed — skip it this
   tick rather than risk a false-positive close.

3. **Quantity fix** — broker quantity is truth. For any ticker still present
   at the broker whose managed quantity disagrees, the coordinator's
   `ManagedPosition.quantity` is set directly (and the risk monitor
   re-registered so the watched size follows) and PM's quantity is set via
   `update_position(quantity=...)`, which assigns absolutely — the correct
   operation here regardless of how either side drifted (including the
   PM-absolute-vs-fill-tracker-incremental double-count race described
   above: whichever side over/under-counted converges to the broker value).

A broker query failure aborts the whole pass (log and return an all-zero
`ReconcileReport`) — managed state is left untouched for the next tick to
retry, exactly like `_poll_tracked_fills`.
"""
from datetime import datetime
from typing import Optional
import logging
import uuid

from pydantic import BaseModel

from .models import AlertType, ManagedPosition, QueueStatus, TradingAlert
from .pending_order_tracker import TrackedOrderStatus
from .position_registration import register_fill_as_position

logger = logging.getLogger(__name__)


class ReconcileReport(BaseModel):
    """One `reconcile()` run's outcome — for logs, notifications, and tests."""

    orphans_adopted: int = 0
    externally_closed: int = 0
    quantity_fixed: int = 0


def _find_position(positions, ticker: str) -> Optional[ManagedPosition]:
    return next((p for p in positions if p.ticker == ticker), None)


def _determine_stop_provenance(coordinator, ticker: str, holding):
    """① fill_tracker FILLED → ② trade_queue COMPLETED BUY → ③ default stop.

    Returns (stop_loss, take_profit, provenance_label, risk_score).
    """
    fill_candidates = [
        o
        for o in coordinator.fill_tracker.all_orders()
        if o.ticker == ticker
        and o.status == TrackedOrderStatus.FILLED
        and o.side == "buy"
    ]
    if fill_candidates:
        order = max(fill_candidates, key=lambda o: o.placed_at)
        return order.stop_loss, order.take_profit, "체결기록(fill_tracker)", order.risk_score

    queue_candidates = [
        t
        for t in coordinator.state.trade_queue
        if t.ticker == ticker
        and t.status == QueueStatus.COMPLETED
        and t.action == "BUY"
        and t.stop_loss is not None
    ]
    if queue_candidates:
        trade = max(queue_candidates, key=lambda t: t.queued_at)
        return trade.stop_loss, trade.take_profit, "체결완료 큐(trade_queue)", trade.risk_score

    pct_sl = coordinator.risk_params.default_stop_loss_pct
    pct_tp = coordinator.risk_params.default_take_profit_pct
    avg = float(holding.avg_buy_prc)
    stop_loss = avg * (1 - pct_sl / 100)
    take_profit = avg * (1 + pct_tp / 100)
    return stop_loss, take_profit, f"기본 스탑(평단 ±{pct_sl:.0f}%)", None


async def _get_position_manager(coordinator):
    """Lazy PM lookup — best-effort, `None` on any failure (PM not running,
    agent_chat not importable, etc). Same access pattern as
    position_registration.register_fill_as_position."""
    try:
        from services.agent_chat.coordinator import get_chat_coordinator

        chat_coordinator = await get_chat_coordinator()
        return chat_coordinator.position_manager
    except Exception as e:
        logger.warning(f"[Reconciler] PositionManager lookup failed: {e}")
        return None


async def _adopt_orphans(coordinator, pm, holdings_by_ticker: dict, report: ReconcileReport) -> None:
    for ticker, holding in holdings_by_ticker.items():
        coordinator_pos = _find_position(coordinator.state.positions, ticker)
        if coordinator_pos is not None:
            continue  # coordinator already knows this ticker

        pm_pos = pm.get_position(ticker) if pm is not None else None
        stop_loss, take_profit, provenance, risk_score = _determine_stop_provenance(
            coordinator, ticker, holding
        )

        if pm_pos is None:
            # True orphan — neither engine knows it. register_fill_as_position
            # is safe here: both sides start from nothing, so the full
            # holding quantity is the correct increment on both.
            await register_fill_as_position(
                coordinator,
                ticker=ticker,
                stock_name=holding.stk_nm,
                quantity=holding.hldg_qty,
                avg_price=float(holding.avg_buy_prc),
                stop_loss=stop_loss,
                take_profit=take_profit,
                source="reconciler",
                risk_score=risk_score,
            )
        else:
            # PM already tracks it (its own sync_from_account can populate a
            # ticker the coordinator never placed an order for) — see module
            # docstring for why register_fill_as_position is NOT used here.
            coordinator._add_position(
                ManagedPosition(
                    ticker=ticker,
                    stock_name=holding.stk_nm,
                    quantity=holding.hldg_qty,
                    avg_price=float(holding.avg_buy_prc),
                    current_price=float(holding.cur_prc),
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )
            )
            if pm_pos.stop_loss is None or pm_pos.take_profit is None:
                try:
                    pm.update_position(
                        ticker=ticker,
                        stop_loss=stop_loss if pm_pos.stop_loss is None else None,
                        take_profit=take_profit if pm_pos.take_profit is None else None,
                    )
                except Exception as e:
                    logger.warning(f"[Reconciler] PM stop backfill failed for {ticker}: {e}")

        report.orphans_adopted += 1
        await coordinator._on_alert(
            TradingAlert(
                id=str(uuid.uuid4())[:8],
                alert_type=AlertType.ORDER_FILLED,
                ticker=ticker,
                title="고아 포지션 채택",
                message=(
                    f"{holding.stk_nm or ticker} {holding.hldg_qty}주 — 브로커에만 "
                    f"존재하던 포지션을 채택했습니다 (스탑 출처: {provenance})"
                ),
                data={
                    "quantity": holding.hldg_qty,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "provenance": provenance,
                },
            )
        )

    if pm is None:
        return

    # Decision 1, reverse direction: the coordinator already knows a ticker
    # but PM doesn't. Not a broker "orphan" (already known/trusted by the
    # coordinator) so it isn't counted or notified — just mirrored so both
    # engines converge, same as PM's own sync would eventually do.
    for ticker, holding in holdings_by_ticker.items():
        coordinator_pos = _find_position(coordinator.state.positions, ticker)
        if coordinator_pos is None:
            continue
        if pm.get_position(ticker) is not None:
            continue
        try:
            pm.add_position(
                ticker=ticker,
                stock_name=coordinator_pos.stock_name,
                quantity=coordinator_pos.quantity,
                avg_price=coordinator_pos.avg_price,
                stop_loss=coordinator_pos.stop_loss,
                take_profit=coordinator_pos.take_profit,
            )
        except Exception as e:
            logger.warning(f"[Reconciler] PM backfill failed for {ticker}: {e}")


async def _detect_external_closes(coordinator, pm, holdings_by_ticker: dict, report: ReconcileReport) -> None:
    managed_tickers = {p.ticker for p in coordinator.state.positions}
    if pm is not None:
        try:
            managed_tickers |= {p.ticker for p in pm.get_all_positions()}
        except Exception as e:
            logger.warning(f"[Reconciler] PM get_all_positions failed: {e}")

    for ticker in managed_tickers:
        if ticker in holdings_by_ticker:
            continue

        tracking_sell = any(
            o.ticker == ticker
            and o.status == TrackedOrderStatus.TRACKING
            and o.side == "sell"
            for o in coordinator.fill_tracker.all_orders()
        )
        if tracking_sell:
            continue

        coordinator_pos = _find_position(coordinator.state.positions, ticker)
        stock_name = coordinator_pos.stock_name if coordinator_pos else None
        if coordinator_pos is not None:
            coordinator._remove_position(ticker)

        if pm is not None:
            pm_pos = pm.get_position(ticker)
            if pm_pos is not None:
                stock_name = stock_name or pm_pos.stock_name
                try:
                    pm.remove_position(ticker)
                except Exception as e:
                    logger.warning(f"[Reconciler] PM remove_position failed for {ticker}: {e}")

        report.externally_closed += 1
        await coordinator._on_alert(
            TradingAlert(
                id=str(uuid.uuid4())[:8],
                alert_type=AlertType.REBALANCE_SUGGESTED,
                ticker=ticker,
                title="외부 매도 감지",
                message=(
                    f"{stock_name or ticker} — 브로커 보유수량이 0이 되어 감시를 "
                    f"종료했습니다 (앱 외부에서 매도된 것으로 추정)"
                ),
                data={},
            )
        )


async def _fix_quantities(coordinator, pm, holdings_by_ticker: dict, report: ReconcileReport) -> None:
    for ticker, holding in holdings_by_ticker.items():
        broker_qty = holding.hldg_qty
        fixed = False

        coordinator_pos = _find_position(coordinator.state.positions, ticker)
        if coordinator_pos is not None and coordinator_pos.quantity != broker_qty:
            coordinator_pos.quantity = broker_qty
            coordinator_pos.last_updated = datetime.now()
            coordinator.risk_monitor.remove_position(ticker)
            coordinator.risk_monitor.add_position(coordinator_pos)
            coordinator._schedule_persist()
            fixed = True

        if pm is not None:
            pm_pos = pm.get_position(ticker)
            if pm_pos is not None and pm_pos.quantity != broker_qty:
                try:
                    pm.update_position(ticker=ticker, quantity=broker_qty)
                    fixed = True
                except Exception as e:
                    logger.warning(f"[Reconciler] PM quantity fix failed for {ticker}: {e}")

        if fixed:
            report.quantity_fixed += 1
            await coordinator._on_alert(
                TradingAlert(
                    id=str(uuid.uuid4())[:8],
                    alert_type=AlertType.REBALANCE_SUGGESTED,
                    ticker=ticker,
                    title="보유수량 보정",
                    message=(
                        f"{holding.stk_nm or ticker} 관리 수량을 브로커 보유수량"
                        f"({broker_qty}주)으로 보정했습니다"
                    ),
                    data={"broker_quantity": broker_qty},
                )
            )


async def reconcile(coordinator) -> ReconcileReport:
    """One reconcile pass against broker truth. Never raises — a broker query
    failure (or missing client) yields an all-zero report and leaves managed
    state untouched, same contract as `_poll_tracked_fills`."""
    report = ReconcileReport()

    if coordinator._kiwoom is None:
        return report

    try:
        balance = await coordinator._kiwoom.get_account_balance()
    except Exception as e:
        logger.error(f"[Reconciler] get_account_balance failed: {e}")
        return report

    holdings_by_ticker = {h.stk_cd: h for h in balance.holdings if h.hldg_qty > 0}
    pm = await _get_position_manager(coordinator)

    await _adopt_orphans(coordinator, pm, holdings_by_ticker, report)
    await _detect_external_closes(coordinator, pm, holdings_by_ticker, report)
    await _fix_quantities(coordinator, pm, holdings_by_ticker, report)

    return report
