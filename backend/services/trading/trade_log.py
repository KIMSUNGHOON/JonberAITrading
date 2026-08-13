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
            # 호출자가 fee를 직접 넘기면 그 값을 전체 비용으로 취급하고
            # tax는 별도 산정하지 않는다(0) — 이 분기는 현재 어떤 호출자도
            # fee를 넘기지 않아 도달하지 않는다.
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


def _compute_realized_costs(
    *,
    entry_price: float,
    exit_price: float,
    quantity: int,
    realized_amount: float,
    stk_cd: str,
) -> tuple[int, int, float, str]:
    """(fee, tax, net_amount, cost_source) — 왕복 거래비용을 gross에서 뺀다.

    fee = 매수 수수료 + 매도 수수료, tax = 매도 증권거래세.
    `compute_fill_cost`는 price/quantity가 0 이하이면 (0, 0)을 돌려주므로
    그때 net은 gross와 같아진다 — 의도된 동작이다(계좌 백필 집계처럼
    단가/수량이 없는 행에 가짜 비용을 만들어내지 않는다).

    never-raise: 호출자(`record_kr_realized_pnl_async`)의 계약은 "기록
    실패가 매도 경로를 절대 깨지 않는다"이고, 그 계약은 원장 행을 잃지
    않는 것까지 포함한다. `compute_fill_cost` 자체는 순수 함수지만
    `get_paper_fill_settings()`(pydantic BaseSettings 구성 — 환경변수가
    깨져 있으면 ValidationError)를 호출하므로, 여기서 터지면 비용만
    미상으로 두고(net=gross, cost_source='model_unavailable') 원장 기록은
    계속한다. 비용 산정 실패로 거래 기록 자체를 잃는 쪽이 더 나쁘다.
    """
    try:
        from services.trading.cost_model import compute_fill_cost

        entry_fee, _ = compute_fill_cost("buy", entry_price, quantity)
        exit_fee, exit_tax = compute_fill_cost("sell", exit_price, quantity)
    except Exception as e:
        logger.warning(
            "kr_realized_pnl_cost_model_failed", stk_cd=stk_cd, error=str(e)
        )
        return (0, 0, float(realized_amount), "model_unavailable")

    fee = entry_fee + exit_fee
    return (fee, exit_tax, float(realized_amount) - fee - exit_tax, "model")


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

    거래비용 (2026-08-08): 이 함수는 원장 기록과 결정 outcome 백필을 둘 다
    하는 유일한 초크포인트다. `realized_amount`는 (exit-entry)*qty 순수
    gross이고 여기에는 수수료도 증권거래세도 없었다 — 그 gross가 그대로
    `outcome_realized_pnl`로 백필돼 calibration의 정오답 채점 → 전략
    재가중으로 흘러가, 비용을 못 넘긴 거래가 "승리"로 학습됐다. 이제
    `compute_fill_cost` 모델로 왕복 비용을 빼 net을 함께 적고, **결정
    백필은 net으로** 한다. gross는 원장에 그대로 남는다(두 단위 병존).
    """
    from services.storage_service import get_storage_service

    try:
        # never-raise 계약 안쪽에서 산정한다 — `_compute_realized_costs`는
        # 자체 가드로 비용 실패 시 net=gross로 물러나지만, 그 가드가 못 잡는
        # 종류의 실패(예: 인자 자체가 산술 불가)까지 이 계약 밖으로 새어
        # 나가면 안 된다. 밖에 둘 이득이 없다.
        fee, tax, net_amount, cost_source = _compute_realized_costs(
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            realized_amount=realized_amount,
            stk_cd=stk_cd,
        )
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
            "fee": fee,
            "tax": tax,
            "net_amount": net_amount,
            "cost_source": cost_source,
        }
        await storage.save_kr_realized_pnl(record)
        if entry_decision_id:
            outcome_updated = await storage.update_decision_outcome(
                entry_decision_id, net_amount
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
                    net_amount=net_amount,
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
