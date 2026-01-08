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
from services.kiwoom import OrderType

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

    # Execute order via Kiwoom API (using shared singleton)
    try:
        client = await get_shared_kiwoom_client_async()

        # BUY or ADD → Execute buy order
        if _is_buy_action(action):
            order_response = await client.place_buy_order(
                stk_cd=stk_cd,
                qty=quantity,
                price=entry_price,
                order_type=OrderType.LIMIT,
            )

        # SELL or REDUCE → Execute sell order
        elif _is_sell_action(action):
            order_response = await client.place_sell_order(
                stk_cd=stk_cd,
                qty=quantity,
                price=entry_price,
                order_type=OrderType.LIMIT,
            )

        else:
            # Should not reach here due to no-trade check above
            reasoning = f"[실행] 알 수 없는 액션: {action.value}"
            return {
                "execution_status": "failed",
                "error": f"Unknown action: {action.value}",
                "current_stage": KRStockAnalysisStage.COMPLETE,
                "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
            }

        logger.info(
            "kr_stock_order_placed",
            stk_cd=stk_cd,
            action=action.value,
            order_no=order_response.ord_no,
            return_code=order_response.return_code,
        )

        # Calculate position quantity change
        existing_qty = existing_position.get("quantity", 0) if existing_position else 0
        quantity_change = _calculate_position_quantity_change(action, quantity)

        # Create/update position record based on action type
        if action == TradeAction.ADD:
            # ADD: Merge with existing position (existing_position is guaranteed non-None here)
            new_quantity = existing_qty + quantity
            avg_price = _calculate_average_price(
                existing_price=existing_position.get("entry_price", 0),
                existing_qty=existing_qty,
                new_price=entry_price,
                new_qty=quantity,
            )
            position = KRStockPosition(
                stk_cd=stk_cd,
                stk_nm=stk_nm,
                quantity=new_quantity,
                entry_price=avg_price,
                current_price=entry_price,
                stop_loss=proposal.get("stop_loss") or existing_position.get("stop_loss"),
                take_profit=proposal.get("take_profit") or existing_position.get("take_profit"),
            )
        elif action == TradeAction.REDUCE and existing_position:
            # Reduce existing position
            new_quantity = max(0, existing_qty - quantity)
            position = KRStockPosition(
                stk_cd=stk_cd,
                stk_nm=stk_nm,
                quantity=new_quantity,
                entry_price=existing_position.get("entry_price", entry_price),
                current_price=entry_price,
                stop_loss=existing_position.get("stop_loss") if new_quantity > 0 else None,
                take_profit=existing_position.get("take_profit") if new_quantity > 0 else None,
            )
        else:
            # BUY (new position) or SELL (position closed)
            position = KRStockPosition(
                stk_cd=stk_cd,
                stk_nm=stk_nm,
                quantity=quantity_change,
                entry_price=entry_price,
                current_price=entry_price,
                stop_loss=proposal.get("stop_loss"),
                take_profit=proposal.get("take_profit"),
            )

        # Build reasoning message with action-specific details
        if action == TradeAction.ADD:
            reasoning = (
                f"[실행] ({mode_str}) {action_korean} 접수: {stk_nm} +{quantity}주 @ {entry_price:,}원, "
                f"기존 {existing_qty}주 → 총 {position.quantity}주, 주문번호: {order_response.ord_no}"
            )
        elif action == TradeAction.REDUCE:
            reasoning = (
                f"[실행] ({mode_str}) {action_korean} 접수: {stk_nm} -{quantity}주 @ {entry_price:,}원, "
                f"기존 {existing_qty}주 → 잔여 {position.quantity}주, 주문번호: {order_response.ord_no}"
            )
        else:
            reasoning = (
                f"[실행] ({mode_str}) {action_korean} 접수: {stk_nm} {quantity}주 @ {entry_price:,}원, "
                f"주문번호: {order_response.ord_no}"
            )

        return {
            "execution_status": "completed",
            "active_position": position.model_dump(),
            "order_response": {
                "ord_no": order_response.ord_no,
                "return_code": order_response.return_code,
                "return_msg": order_response.return_msg,
            },
            "current_stage": KRStockAnalysisStage.COMPLETE,
            "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
            "messages": [AIMessage(content=reasoning)],
        }

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
