"""
Execution Node for Korean Stock Trading

Contains the execution node and conditional edge function.

Supported TradeAction types:
- BUY: 신규 매수 (미보유 시)
- SELL: 전량 매도 (보유 시)
- HOLD: 유지 (보유 시) - 거래 미실행
- ADD: 추가 매수 (보유 시) - 매수 주문 실행
- REDUCE: 부분 매도 (보유 시) - 매도 주문 실행
- WATCH: 관망 (미보유 + HOLD 시그널) - 거래 미실행
- AVOID: 매수 금지 (미보유 + SELL 시그널) - 거래 미실행
"""

from datetime import date
from typing import Literal, Optional

import structlog
from langchain_core.messages import AIMessage

from agents.graph.kr_stock_state import (
    KRStockAnalysisStage,
    KRStockPosition,
    TradeAction,
    add_kr_stock_reasoning_log,
)
from app.config import settings
from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
from services.execution import (
    KiwoomExecutionAdapter,
    ExecutionSide,
    ExecutionOrderType,
)
from services.trading.fill_confirm import confirm_kiwoom_fill

logger = structlog.get_logger()


def _normalize_action(action) -> TradeAction:
    """
    Normalize action to TradeAction enum.

    Args:
        action: Action as string or TradeAction enum

    Returns:
        TradeAction enum value
    """
    if isinstance(action, TradeAction):
        return action

    if isinstance(action, str):
        action_upper = action.upper()
        try:
            return TradeAction(action_upper)
        except ValueError:
            logger.warning("unknown_trade_action", action=action)
            return TradeAction.HOLD

    return TradeAction.HOLD


def _is_buy_action(action: TradeAction) -> bool:
    """Check if action is a buy-type action (BUY or ADD)."""
    return action in (TradeAction.BUY, TradeAction.ADD)


def _is_sell_action(action: TradeAction) -> bool:
    """Check if action is a sell-type action (SELL or REDUCE)."""
    return action in (TradeAction.SELL, TradeAction.REDUCE)


def _is_no_trade_action(action: TradeAction) -> bool:
    """Check if action requires no trade execution."""
    return action in (TradeAction.HOLD, TradeAction.WATCH, TradeAction.AVOID)


def _get_action_korean(action: TradeAction) -> str:
    """Get Korean description for action."""
    action_korean = {
        TradeAction.BUY: "신규 매수",
        TradeAction.SELL: "전량 매도",
        TradeAction.HOLD: "보유 유지",
        TradeAction.ADD: "추가 매수",
        TradeAction.REDUCE: "부분 매도",
        TradeAction.WATCH: "관망",
        TradeAction.AVOID: "매수 금지",
    }
    return action_korean.get(action, str(action))


def _calculate_position_quantity_change(
    action: TradeAction,
    order_quantity: int,
) -> int:
    """
    Calculate the quantity change for position tracking.

    Args:
        action: Trade action
        order_quantity: Number of shares in the order

    Returns:
        Position quantity change (positive for buy, negative for sell)
    """
    if _is_buy_action(action):
        return order_quantity
    elif _is_sell_action(action):
        return -order_quantity
    return 0


def _calculate_average_price(
    existing_price: int,
    existing_qty: int,
    new_price: int,
    new_qty: int,
) -> int:
    """
    Calculate average entry price after adding to position.

    Uses rounding to avoid floor division errors.

    Args:
        existing_price: Current average entry price
        existing_qty: Current position quantity
        new_price: New order price
        new_qty: New order quantity

    Returns:
        New average entry price (rounded)
    """
    total_qty = existing_qty + new_qty
    if total_qty <= 0:
        return new_price
    total_value = existing_price * existing_qty + new_price * new_qty
    return round(total_value / total_qty)


async def kr_stock_execution_node(state: dict) -> dict:
    """
    Execute the approved Korean stock trade via Kiwoom API.

    Supports all TradeAction types:
    - BUY/ADD: Execute buy order
    - SELL/REDUCE: Execute sell order
    - HOLD/WATCH/AVOID: No trade execution, mark as completed

    Supports two trading modes based on KIWOOM_IS_MOCK:
    - mock: Uses mock trading API (simulated)
    - live: Uses live trading API (real money)
    """
    proposal = state.get("trade_proposal", {})
    approval_status = state.get("approval_status")
    existing_position = state.get("existing_position")

    if approval_status != "approved" or not proposal:
        reasoning = f"[실행] 거래 미승인 (상태: {approval_status}). 실행 건너뜀."
        return {
            "execution_status": "cancelled",
            "current_stage": KRStockAnalysisStage.COMPLETE,
            "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        }

    stk_cd = proposal.get("stk_cd", "")
    stk_nm = proposal.get("stk_nm", stk_cd)
    raw_action = proposal.get("action", "HOLD")
    entry_price = proposal.get("entry_price", 0)
    quantity = proposal.get("quantity", 0)

    # Normalize action to TradeAction enum
    action = _normalize_action(raw_action)
    action_korean = _get_action_korean(action)

    is_mock = getattr(settings, "KIWOOM_IS_MOCK", True)
    mode_str = "모의투자" if is_mock else "실거래"

    logger.info(
        "kr_stock_trade_execution_start",
        stk_cd=stk_cd,
        action=action.value,
        action_korean=action_korean,
        trading_mode=mode_str,
    )

    # Handle no-trade actions (HOLD, WATCH, AVOID)
    if _is_no_trade_action(action):
        reasoning = f"[실행] {action_korean} 결정 - {stk_nm} 거래 미실행"
        return {
            "execution_status": "completed",
            "current_stage": KRStockAnalysisStage.COMPLETE,
            "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
            "messages": [AIMessage(content=reasoning)],
        }

    # Validate input parameters
    if quantity <= 0:
        reasoning = f"[실행] 잘못된 수량: {quantity}"
        return {
            "execution_status": "failed",
            "error": f"Invalid quantity: {quantity}",
            "current_stage": KRStockAnalysisStage.COMPLETE,
            "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        }

    if entry_price <= 0:
        reasoning = f"[실행] 잘못된 가격: {entry_price}"
        return {
            "execution_status": "failed",
            "error": f"Invalid entry_price: {entry_price}",
            "current_stage": KRStockAnalysisStage.COMPLETE,
            "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        }

    # Validate ADD/REDUCE requires existing position
    if action in (TradeAction.ADD, TradeAction.REDUCE) and not existing_position:
        reasoning = f"[실행] {action_korean} 실패 - 기존 포지션 없음"
        logger.warning(
            "action_requires_existing_position",
            stk_cd=stk_cd,
            action=action.value,
        )
        return {
            "execution_status": "failed",
            "error": f"{action.value} requires existing position",
            "current_stage": KRStockAnalysisStage.COMPLETE,
            "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        }

    # Execute via the broker-agnostic execution path. KiwoomExecutionAdapter wraps
    # the shared client (mock/live gated inside it by KIWOOM_IS_MOCK).
    try:
        client = await get_shared_kiwoom_client_async()
        adapter = KiwoomExecutionAdapter(client)

        if _is_buy_action(action):
            exec_side = ExecutionSide.BUY
        elif _is_sell_action(action):
            exec_side = ExecutionSide.SELL
        else:
            # Should not reach here due to no-trade check above
            reasoning = f"[실행] 알 수 없는 액션: {action.value}"
            return {
                "execution_status": "failed",
                "error": f"Unknown action: {action.value}",
                "current_stage": KRStockAnalysisStage.COMPLETE,
                "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
            }

        result = await adapter.place(
            ticker=stk_cd,
            side=exec_side,
            qty=quantity,
            price=entry_price,
            order_type=ExecutionOrderType.LIMIT,
        )
        order_response = result.raw  # native OrderResponse — ord_no/return_code used below

        # A broker REJECTION is not an exception — KiwoomExecutionAdapter.place
        # returns success=False (return_code != 0, ord_no likely empty) WITHOUT
        # raising. Branch on it BEFORE fill confirmation: a rejected order has
        # no fill to confirm and must never register a phantom TrackedOrder
        # (an "" ord_no would be polled against real ka10076 every tick and
        # expire at market close as '미체결 만료' for an order the broker
        # refused). Same failure vocabulary as the node's other failure paths.
        if not result.success:
            error_msg = order_response.return_msg or "Order rejected by broker"
            logger.error(
                "kr_stock_order_rejected",
                stk_cd=stk_cd,
                action=action.value,
                return_code=order_response.return_code,
                error=error_msg,
            )
            reasoning = f"[실행] {action_korean} 주문 거부: {error_msg}"
            return {
                "execution_status": "failed",
                "error": error_msg,
                "order_response": {
                    "ord_no": order_response.ord_no,
                    "return_code": order_response.return_code,
                    "return_msg": order_response.return_msg,
                },
                "current_stage": KRStockAnalysisStage.COMPLETE,
                "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
                "messages": [AIMessage(content=reasoning)],
            }

        logger.info(
            "kr_stock_order_placed",
            stk_cd=stk_cd,
            action=action.value,
            order_no=order_response.ord_no,
            return_code=order_response.return_code,
        )

        # An accepted order is NOT a filled order — confirm the ACTUAL fill via
        # ka10076 (체결내역) instead of assuming full fill at the limit price.
        # A limit order may fill partially or not at all; reporting an assumed
        # full fill fabricated ghost positions for shares the broker never
        # actually filled (F3 audit; mirrors OrderAgent._confirm_kiwoom_fill).
        # A query failure inside confirm_kiwoom_fill is reported as 0 fill,
        # never as an assumed full fill.
        filled_qty, avg_fill_price = await confirm_kiwoom_fill(
            client,
            ticker=stk_cd,
            order_no=order_response.ord_no,
            requested_qty=quantity,
            fallback_price=entry_price,
        )
        remaining_qty = max(0, quantity - filled_qty)

        logger.info(
            "kr_stock_fill_confirmed",
            stk_cd=stk_cd,
            action=action.value,
            order_no=order_response.ord_no,
            requested_qty=quantity,
            filled_qty=filled_qty,
            remaining_qty=remaining_qty,
        )

        # Calculate position quantity change — driven by the CONFIRMED fill,
        # never the requested quantity. A 0 fill produces no position at all
        # (position stays None → omitted from the returned state so any
        # existing position is left untouched rather than clobbered).
        existing_qty = existing_position.get("quantity", 0) if existing_position else 0
        avg_fill_price_int = round(avg_fill_price)

        position: Optional[KRStockPosition] = None
        if filled_qty > 0:
            # Create/update position record based on action type
            if action == TradeAction.ADD:
                # ADD: Merge with existing position (existing_position is guaranteed non-None here)
                new_quantity = existing_qty + filled_qty
                avg_price = _calculate_average_price(
                    existing_price=existing_position.get("entry_price", 0),
                    existing_qty=existing_qty,
                    new_price=avg_fill_price,
                    new_qty=filled_qty,
                )
                position = KRStockPosition(
                    stk_cd=stk_cd,
                    stk_nm=stk_nm,
                    quantity=new_quantity,
                    entry_price=avg_price,
                    current_price=avg_fill_price_int,
                    stop_loss=proposal.get("stop_loss") or existing_position.get("stop_loss"),
                    take_profit=proposal.get("take_profit") or existing_position.get("take_profit"),
                )
            elif action == TradeAction.REDUCE and existing_position:
                # Reduce existing position by the CONFIRMED sold quantity
                new_quantity = max(0, existing_qty - filled_qty)
                position = KRStockPosition(
                    stk_cd=stk_cd,
                    stk_nm=stk_nm,
                    quantity=new_quantity,
                    entry_price=existing_position.get("entry_price", avg_fill_price_int),
                    current_price=avg_fill_price_int,
                    stop_loss=existing_position.get("stop_loss") if new_quantity > 0 else None,
                    take_profit=existing_position.get("take_profit") if new_quantity > 0 else None,
                )
            else:
                # BUY (new position) or SELL (position reduced/closed) — the
                # CONFIRMED fill, not the requested quantity, drives the delta.
                quantity_change = _calculate_position_quantity_change(action, filled_qty)
                position = KRStockPosition(
                    stk_cd=stk_cd,
                    stk_nm=stk_nm,
                    quantity=quantity_change,
                    entry_price=avg_fill_price_int,
                    current_price=avg_fill_price_int,
                    stop_loss=proposal.get("stop_loss"),
                    take_profit=proposal.get("take_profit"),
                )

            # P1-1: record the confirmed fill for /trades — regardless of
            # action type (BUY/ADD/SELL/REDUCE), matching the coordinator's
            # own choke points. Lazy-imported (mirrors this file's existing
            # convention for coordinator side effects below) so tests can
            # patch it at its origin module. Best-effort: a recording
            # failure must never fail the graph run.
            try:
                from services.trading.trade_log import record_trade_fill

                record_trade_fill(
                    stk_cd=stk_cd,
                    stk_nm=stk_nm,
                    side="buy" if _is_buy_action(action) else "sell",
                    order_type="limit",
                    price=avg_fill_price,
                    quantity=quantity,
                    executed_quantity=filled_qty,
                    status="completed" if filled_qty >= quantity else "partial",
                    order_id=order_response.ord_no,
                    session_id=state.get("session_id"),
                )
            except Exception as trade_log_err:
                logger.warning(
                    "kr_stock_trade_log_failed",
                    stk_cd=stk_cd,
                    action=action.value,
                    error=str(trade_log_err),
                )

        # Mirror the confirmed fill into the trading coordinator's own
        # monitoring (RiskMonitor / agent-chat PositionManager) and, for any
        # still-unfilled remainder of a BUY-side order, register it with the
        # coordinator's fill tracker so the scheduler's ka10076 poll can pick
        # up the post-fill later — otherwise a partial/zero fill at placement
        # time would go unwatched by every defense engine once this node
        # returns. SELL/REDUCE unfilled remainders are explicitly out of
        # scope here (mirrors coordinator.py's own R5-P4 scope boundary).
        #
        # Best-effort: a coordinator failure must never crash the graph run,
        # so this entire block is exception-boxed and the execution_status
        # computed below is unaffected by it.
        if _is_buy_action(action):
            try:
                from app.dependencies import get_trading_coordinator
                from services.trading.pending_order_tracker import TrackedOrder
                from services.trading.position_registration import (
                    register_fill_as_position,
                )

                coordinator = await get_trading_coordinator()

                # Proposal risk_score is float 0-1 (KRStockTradeProposal);
                # the coordinator layer (TrackedOrder / ManagedPosition) uses
                # int 1-10 — convert with the file's existing convention
                # (decision_nodes.py:330, int(proposal.risk_score * 10)).
                proposal_risk = proposal.get("risk_score")
                risk_score_int = (
                    int(float(proposal_risk) * 10) if proposal_risk is not None else None
                )

                if filled_qty > 0:
                    await register_fill_as_position(
                        coordinator,
                        ticker=stk_cd,
                        stock_name=stk_nm,
                        quantity=filled_qty,
                        avg_price=avg_fill_price,
                        stop_loss=proposal.get("stop_loss"),
                        take_profit=proposal.get("take_profit"),
                        session_id=state.get("session_id"),
                        source="kr_graph_execution",
                        # Parity with the poll path (coordinator.py:1560-1561):
                        # stop_loss_mode from risk params, risk from the proposal.
                        stop_loss_mode=coordinator.risk_params.stop_loss_mode,
                        risk_score=risk_score_int,
                    )

                if remaining_qty > 0:
                    coordinator.fill_tracker.register(
                        TrackedOrder(
                            ord_no=order_response.ord_no,
                            ticker=stk_cd,
                            stock_name=stk_nm,
                            side="buy",
                            total_quantity=quantity,
                            filled_quantity=filled_qty,
                            filled_amount=filled_qty * avg_fill_price,
                            limit_price=entry_price,
                            stop_loss=proposal.get("stop_loss"),
                            take_profit=proposal.get("take_profit"),
                            source_session_id=state.get("session_id"),
                            risk_score=risk_score_int,
                            trade_date=date.today().strftime("%Y%m%d"),
                        )
                    )
                    # A memory-only TrackedOrder dies with the process — the
                    # exact incident class this arc closes. Schedule the
                    # coordinator's blob persistence (R5-P1 mechanism) so the
                    # tracked remainder survives a restart.
                    coordinator._schedule_persist()
            except Exception as coord_err:
                logger.warning(
                    "kr_stock_fill_registration_failed",
                    stk_cd=stk_cd,
                    action=action.value,
                    error=str(coord_err),
                )

        execution_status = "completed" if filled_qty > 0 else "placed_pending_fill"

        # Build reasoning message with action-specific details
        if action == TradeAction.ADD:
            reported_total = position.quantity if position else existing_qty
            reasoning = (
                f"[실행] ({mode_str}) {action_korean} 접수: {stk_nm} +{filled_qty}/{quantity}주(체결/요청) "
                f"@ {avg_fill_price_int:,}원, 기존 {existing_qty}주 → 총 {reported_total}주, "
                f"주문번호: {order_response.ord_no}"
            )
        elif action == TradeAction.REDUCE:
            reported_remaining = position.quantity if position else existing_qty
            reasoning = (
                f"[실행] ({mode_str}) {action_korean} 접수: {stk_nm} -{filled_qty}/{quantity}주(체결/요청) "
                f"@ {avg_fill_price_int:,}원, 기존 {existing_qty}주 → 잔여 {reported_remaining}주, "
                f"주문번호: {order_response.ord_no}"
            )
        elif filled_qty <= 0:
            reasoning = (
                f"[실행] ({mode_str}) {action_korean} 접수: {stk_nm} {quantity}주 @ {entry_price:,}원, "
                f"체결 미확인 — 체결 추적 중 (주문번호: {order_response.ord_no})"
            )
        else:
            reasoning = (
                f"[실행] ({mode_str}) {action_korean} 접수: {stk_nm} {filled_qty}/{quantity}주(체결/요청) "
                f"@ {avg_fill_price_int:,}원, 주문번호: {order_response.ord_no}"
            )

        response_update = {
            "execution_status": execution_status,
            "order_response": {
                "ord_no": order_response.ord_no,
                "return_code": order_response.return_code,
                "return_msg": order_response.return_msg,
            },
            "current_stage": KRStockAnalysisStage.COMPLETE,
            "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
            "messages": [AIMessage(content=reasoning)],
        }
        if position is not None:
            response_update["active_position"] = position.model_dump()
        return response_update

    except Exception as e:
        error_msg = str(e)
        logger.error(
            "kr_stock_order_failed",
            stk_cd=stk_cd,
            action=action.value,
            error=error_msg,
        )

        reasoning = f"[실행] {action_korean} 주문 실패: {error_msg}"

        return {
            "execution_status": "failed",
            "error": error_msg,
            "current_stage": KRStockAnalysisStage.COMPLETE,
            "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
            "messages": [AIMessage(content=reasoning)],
        }


def should_continue_kr_stock_execution(state: dict) -> Literal["execute", "re_analyze", "end"]:
    """Conditional edge: Check if trade was approved, rejected, or cancelled."""
    approval_status = state.get("approval_status")

    if approval_status == "approved":
        return "execute"
    elif approval_status == "rejected":
        return "re_analyze"
    else:
        return "end"
