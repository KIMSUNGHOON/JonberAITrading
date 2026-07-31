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
   tick rather than risk a false-positive close. Guard (review M2): if the
   broker reports ZERO holdings while ≥1 position is managed, the entire
   removal pass is skipped for the cycle (warning logged) — a malformed
   kt00004 payload parses to an empty list, and that must never mass-remove
   every local defense in one tick.

3. **Position fix** — broker quantity AND cost basis are truth (원가 단일화
   C1, 2026-07-31). For any ticker still present at the broker whose managed
   quantity or `avg_price` disagrees (independently — a position can have the
   right quantity and a drifted cost basis, or vice versa), the coordinator's
   `ManagedPosition.quantity`/`avg_price` are set directly (and the risk
   monitor re-registered so the watched size follows) and PM's fields are set
   via `update_position(quantity=..., avg_price=...)`, which assigns
   absolutely — the correct operation here regardless of how either side
   drifted (including the PM-absolute-vs-fill-tracker-incremental
   double-count race described above: whichever side over/under-counted
   converges to the broker value). Cost-basis drift under
   `COST_BASIS_TOLERANCE_PCT` (0.1%) is left alone — it's within the broker's
   `avg_buy_prc` `int` truncation, not a real mismatch. Stop-loss/take-profit
   are never touched by this pass.

The balance is always fetched with `use_cache=False` (review M1): the
client's 30s TTL entry can predate a fill the tracker poll registered
seconds ago, and reconciling against that stale snapshot would remove the
just-registered position as an "external close".

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
    # 원가 단일화 C1(2026-07-31): 수량과 별개로 세는 이유는 07-31 실측에서
    # **수량은 맞고 원가만** 어긋난 종목이 둘이었기 때문이다.
    cost_basis_fixed: int = 0


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
            # stop_loss_mode mirrors the fill-poll path's register semantics
            # (coordinator risk params own the mode — review m1).
            await register_fill_as_position(
                coordinator,
                ticker=ticker,
                stock_name=holding.stk_nm,
                quantity=holding.hldg_qty,
                avg_price=float(holding.avg_buy_prc),
                stop_loss=stop_loss,
                take_profit=take_profit,
                source="reconciler",
                stop_loss_mode=coordinator.risk_params.stop_loss_mode,
                risk_score=risk_score,
            )
        else:
            # PM already tracks it (its own sync_from_account can populate a
            # ticker the coordinator never placed an order for) — see module
            # docstring for why register_fill_as_position is NOT used here.
            # stop_loss_mode/risk_score parity with the true-orphan branch
            # (review m1): a position adopted here must defend under the same
            # mode and carry its provenance risk.
            coordinator._add_position(
                ManagedPosition(
                    ticker=ticker,
                    stock_name=holding.stk_nm,
                    quantity=holding.hldg_qty,
                    avg_price=float(holding.avg_buy_prc),
                    current_price=float(holding.cur_prc),
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    stop_loss_mode=coordinator.risk_params.stop_loss_mode,
                    risk_score=risk_score,
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

    # Mass-removal guard (review M2): a SUCCESSFUL kt00004 response with an
    # EMPTY holdings list is not trustworthy enough to liquidate every local
    # position in one pass — the client manufactures [] from a malformed
    # payload (client.py stk_acnt_evlt_prst non-list → []). Skip only the
    # removal pass this cycle; adoption/quantity passes still ran/run. A
    # genuine account-wide close simply keeps being skipped until an operator
    # (or a non-empty snapshot) intervenes — fail-safe over fail-clean.
    if managed_tickers and not holdings_by_ticker:
        logger.warning(
            f"[Reconciler] Broker reported ZERO holdings while "
            f"{len(managed_tickers)} positions are managed — skipping the "
            f"external-close pass this cycle (possible malformed/empty payload)"
        )
        return

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


# 원가 편차 임계. 브로커 avg_buy_prc가 int라(kiwoom/models.py:202) 주당 최대
# 0.5원 절삭이 생기는데, 그것을 불일치로 오판하지 않기 위한 값이다.
COST_BASIS_TOLERANCE_PCT = 0.1


def _cost_basis_drift_pct(internal_avg: float, broker_avg: float) -> float:
    """내부 원가가 브로커 대비 몇 % 어긋났는지. 브로커가 0이면 0(판정 불가)."""
    if not broker_avg:
        return 0.0
    return abs(internal_avg - broker_avg) / broker_avg * 100.0


async def _fix_positions(coordinator, pm, holdings_by_ticker: dict, report: ReconcileReport) -> None:
    """브로커를 진실로 삼아 수량과 **원가**를 맞춘다.

    이름이 `_fix_quantities`였을 때는 수량만 고쳤고, 진입 조건도
    `quantity != broker_qty` 하나였다. 그런데 07-31 실측에서 089860·317400은
    수량이 맞는 상태에서 원가만 어긋나 있었다(-0.370%, +0.120%) — 그 조건으로는
    영원히 교정되지 않는다. 원가 비교를 독립 조건으로 둔다.

    손절·익절은 절대 재계산하지 않는다(원가 단일화 아크의 소급 원칙).
    """
    for ticker, holding in holdings_by_ticker.items():
        broker_qty = holding.hldg_qty
        broker_avg = float(getattr(holding, "avg_buy_prc", 0) or 0)
        qty_fixed = False
        cost_fixed = False

        coordinator_pos = _find_position(coordinator.state.positions, ticker)
        if coordinator_pos is not None:
            needs_qty = coordinator_pos.quantity != broker_qty
            needs_cost = bool(broker_avg) and _cost_basis_drift_pct(
                coordinator_pos.avg_price, broker_avg
            ) > COST_BASIS_TOLERANCE_PCT

            if needs_qty or needs_cost:
                if needs_qty:
                    coordinator_pos.quantity = broker_qty
                if needs_cost:
                    coordinator_pos.avg_price = broker_avg
                # Refresh current_price from the broker BEFORE re-registering
                # (review m2): RiskMonitor.add_position seeds last_price from
                # position.current_price, and a stale price there can trip the
                # sudden-move detector on the next real quote (PAUSED → all stop
                # checks skipped).
                coordinator_pos.current_price = float(holding.cur_prc)
                coordinator_pos.last_updated = datetime.now()
                coordinator.risk_monitor.remove_position(ticker)
                coordinator.risk_monitor.add_position(coordinator_pos)
                coordinator._schedule_persist()
                qty_fixed = qty_fixed or needs_qty
                cost_fixed = cost_fixed or needs_cost

        if pm is not None:
            pm_pos = pm.get_position(ticker)
            if pm_pos is not None:
                pm_needs_qty = pm_pos.quantity != broker_qty
                pm_needs_cost = bool(broker_avg) and _cost_basis_drift_pct(
                    pm_pos.avg_price, broker_avg
                ) > COST_BASIS_TOLERANCE_PCT
                if pm_needs_qty or pm_needs_cost:
                    try:
                        # stop_loss/take_profit은 넘기지 않는다 — update_position은
                        # None 인자를 무시(coalesce)하므로 기존 방어선이 보존된다.
                        pm.update_position(
                            ticker=ticker,
                            quantity=broker_qty if pm_needs_qty else None,
                            avg_price=broker_avg if pm_needs_cost else None,
                        )
                        qty_fixed = qty_fixed or pm_needs_qty
                        cost_fixed = cost_fixed or pm_needs_cost
                    except Exception as e:
                        logger.warning(f"[Reconciler] PM fix failed for {ticker}: {e}")

        if qty_fixed:
            report.quantity_fixed += 1
        if cost_fixed:
            report.cost_basis_fixed += 1

        if qty_fixed or cost_fixed:
            parts = []
            if qty_fixed:
                parts.append(f"보유수량({broker_qty}주)")
            if cost_fixed:
                parts.append(f"평균단가({broker_avg:,.0f}원)")
            await coordinator._on_alert(
                TradingAlert(
                    id=str(uuid.uuid4())[:8],
                    alert_type=AlertType.REBALANCE_SUGGESTED,
                    ticker=ticker,
                    title="포지션 보정",
                    message=(
                        f"{holding.stk_nm or ticker} 관리 정보를 브로커 "
                        f"{' / '.join(parts)}으로 보정했습니다"
                    ),
                    data={"broker_quantity": broker_qty, "broker_avg_price": broker_avg},
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
        # use_cache=False (review M1): the client's 30s TTL entry can predate
        # a fill the tracker poll registered seconds ago — reconciling against
        # that stale snapshot would remove the just-registered position as an
        # "external close" and re-adopt it next pass (oscillation). Same
        # reasoning as _poll_tracked_fills' ka10076 use_cache=False.
        balance = await coordinator._kiwoom.get_account_balance(use_cache=False)
    except Exception as e:
        logger.error(f"[Reconciler] get_account_balance failed: {e}")
        return report

    holdings_by_ticker = {h.stk_cd: h for h in balance.holdings if h.hldg_qty > 0}
    pm = await _get_position_manager(coordinator)

    await _adopt_orphans(coordinator, pm, holdings_by_ticker, report)
    await _detect_external_closes(coordinator, pm, holdings_by_ticker, report)
    await _fix_positions(coordinator, pm, holdings_by_ticker, report)

    return report
