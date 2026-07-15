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
    fee: int = 0,
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

    try:
        storage = await get_storage_service()
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
            "fee": fee,
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
