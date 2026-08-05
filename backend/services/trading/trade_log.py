"""record_trade_fill — persists confirmed KR stock trade fills for /trades.

P1-1 (2026-07-14): the 거래내역 tab was a permanent empty shell — the storage
methods it called did not exist (masked by `except AttributeError: []` in the
route) and nothing anywhere recorded a fill. This module is the single
recording helper called from every fill choke point:

- `services.trading.coordinator.ExecutionCoordinator._execute_order` (BUY
  placement fills)
- `services.trading.coordinator.ExecutionCoordinator._poll_tracked_fills`
  (F3 post-fill discovery via ka10076)
- `services.trading.coordinator.ExecutionCoordinator._apply_sell_fill`
  (SELL fills, all 4 call sites)
- `agents.graph.kr_stock_nodes.execution.kr_stock_execution_node`
  (graph-path fills)

Recording a trade must never break the trading/execution flow, so this
module offers two layers:

- `record_trade_fill_async`: the awaitable core. Never raises — a storage
  failure is logged and swallowed.
- `record_trade_fill`: fire-and-forget wrapper — schedules the core as a
  background asyncio task so a slow/failing write can't block order
  execution. A module-level strong-reference set keeps the task alive until
  it completes (an unreferenced `asyncio.create_task` result can otherwise be
  garbage-collected mid-flight).
"""

import asyncio
import uuid
from datetime import datetime
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

# Strong references to in-flight fire-and-forget tasks. asyncio does not keep
# a task alive on its own once the caller drops the handle returned by
# create_task — without this set, a trade-fill write can be silently
# cancelled by the garbage collector before it reaches storage.
_pending_tasks: set[asyncio.Task] = set()


async def record_trade_fill_async(
    *,
    stk_cd: str,
    side: str,
    order_type: str,
    price: float,
    quantity: int,
    executed_quantity: int,
    status: str,
    stk_nm: Optional[str] = None,
    session_id: Optional[str] = None,
    fee: Optional[int] = None,
    total_krw: Optional[float] = None,
    order_id: Optional[str] = None,
    trade_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    strategy_id: Optional[str] = None,
    entry_or_exit: Optional[str] = None,
) -> None:
    """Persist one confirmed KR stock trade fill. Awaitable core — never
    raises; storage failures are logged only so a recording failure can
    never break the caller's trading flow."""
    from services.storage_service import get_storage_service
    from services.trading.cost_model import compute_fill_cost

    try:
        storage = await get_storage_service()

        # 비용 산정 — 호출자가 명시적으로 넘기지 않으면 모델로 산정한다.
        # 세 호출자(ledger_reconcile / kr_stock_nodes.execution / coordinator)가
        # 각자 넘기게 하면 하나만 빠뜨려도 원장이 다시 섞인다. 단일 지점에서
        # 산정해 미래 호출자도 빠뜨릴 수 없게 한다.
        if fee is None:
            commission, tax = compute_fill_cost(side, price, executed_quantity)
            cost_source = "model"
        else:
            commission, tax = int(fee), 0
            cost_source = "broker"

        record: dict[str, Any] = {
            "id": trade_id or str(uuid.uuid4()),
            "session_id": session_id,
            "stk_cd": stk_cd,
            "stk_nm": stk_nm,
            "side": side,
            "order_type": order_type,
            "price": round(price),
            "quantity": quantity,
            "executed_quantity": executed_quantity,
            "fee": commission,
            "tax": tax,
            "cost_source": cost_source,
            "total_krw": (
                round(total_krw)
                if total_krw is not None
                else round(price * executed_quantity)
            ),
            "status": status,
            "order_id": order_id,
            "created_at": datetime.now(),
            "decision_id": decision_id,
            "strategy_id": strategy_id,
            "entry_or_exit": entry_or_exit,
        }
        await storage.add_kr_stock_trade(record)
    except Exception as e:
        logger.warning(
            "trade_fill_record_failed", stk_cd=stk_cd, side=side, error=str(e)
        )


def record_trade_fill(**kwargs) -> None:
    """Fire-and-forget: schedule `record_trade_fill_async` without blocking
    the caller. Safe to call from any (a)synchronous fill choke point that
    already has a running event loop — a storage failure is logged inside
    the core and never propagates here, and the absence of a running loop
    (e.g. a bare unit-test call) degrades to a logged no-op rather than an
    exception."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "trade_fill_record_no_event_loop",
            stk_cd=kwargs.get("stk_cd"),
            side=kwargs.get("side"),
        )
        return

    task = loop.create_task(record_trade_fill_async(**kwargs))
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


async def wait_for_pending_trade_fill_writes() -> None:
    """Test helper: await every in-flight fire-and-forget trade-fill write
    scheduled via `record_trade_fill`, so tests can assert on storage state
    deterministically instead of racing the event loop."""
    tasks = list(_pending_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def record_kr_realized_pnl_async(
    *,
    stk_cd: str,
    entry_price: float,
    exit_price: float,
    quantity: int,
    realized_amount: float,
    entry_decision_id: Optional[str] = None,
    exit_decision_id: Optional[str] = None,
    entry_at: Optional[datetime] = None,
    exit_at: Optional[datetime] = None,
    holding_period_seconds: Optional[int] = None,
) -> None:
    """Persist one matched KR entry/exit realized-P&L record, then backfill
    the originating decision's outcome. Awaitable core — never raises;
    storage failures are logged only so a recording failure can never break
    the caller's sell path (mirrors record_trade_fill_async's contract).

    (Phase1 Task 4/C3a: the single write path `coordinator._apply_sell_fill`
    funnels through, called via the fire-and-forget `record_kr_realized_pnl`
    below since `_apply_sell_fill` is sync and cannot await this directly.)
    """
    from services.storage_service import get_storage_service

    try:
        storage = await get_storage_service()
        record: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "stk_cd": stk_cd,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "realized_amount": realized_amount,
            "entry_decision_id": entry_decision_id,
            "exit_decision_id": exit_decision_id,
            "entry_at": entry_at,
            "exit_at": exit_at,
            "holding_period_seconds": holding_period_seconds,
        }
        await storage.save_kr_realized_pnl(record)
        if entry_decision_id:
            outcome_updated = await storage.update_decision_outcome(
                entry_decision_id, realized_amount
            )
            if not outcome_updated:
                # L4: update_decision_outcome already logged the storage-side
                # reason (decision_outcome_update_missed) -- this warning is
                # the CALL-SITE observation that a specific realized-P&L
                # write's outcome backfill never landed, so the gap shows up
                # right next to the trade that caused it (previously this
                # branch discarded the bool return entirely and stayed
                # silent).
                logger.warning(
                    "kr_realized_pnl_decision_outcome_backfill_missed",
                    entry_decision_id=entry_decision_id,
                    realized_amount=realized_amount,
                )
    except Exception as e:
        logger.warning(
            "kr_realized_pnl_record_failed", stk_cd=stk_cd, error=str(e)
        )


def record_kr_realized_pnl(**kwargs) -> None:
    """Fire-and-forget: schedule `record_kr_realized_pnl_async` without
    blocking the caller. Identical contract to `record_trade_fill` — safe to
    call from any (a)synchronous fill choke point that already has a running
    event loop; the absence of a running loop (e.g. a bare unit-test call)
    degrades to a logged no-op rather than an exception."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "kr_realized_pnl_record_no_event_loop",
            stk_cd=kwargs.get("stk_cd"),
        )
        return

    task = loop.create_task(record_kr_realized_pnl_async(**kwargs))
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
