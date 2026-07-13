"""register_fill_as_position — 양쪽 감시 엔진 공용 등록 헬퍼.

체결된 포지션을 두 개의 독립된 감시 엔진에 동시에 등록한다:

1. ExecutionCoordinator (`coordinator._add_position`) — 기존 포지션과 평균
   합산, RiskMonitor 등록, persist 스케줄까지 내장. 이 헬퍼의 계약상 반드시
   성공해야 하는 1차 등록.
2. agent-chat PositionManager (`get_chat_coordinator().position_manager`) —
   그룹 챗 감시가 같은 포지션을 보게 하는 best-effort 미러링. 코디네이터가
   아직 기동 전이면(`position_manager is None`) 스킵하고 로그만 남기며,
   그 외 예외도 전부 삼켜 1차 등록을 되돌리거나 예외를 전파하지 않는다.

Task 4(fill tracker)·5(graph node)·6(reconciler)가 이 헬퍼를 통해 체결을
양쪽에 반영한다.
"""
from typing import Optional

import structlog

from services.trading.models import ManagedPosition

logger = structlog.get_logger()


async def register_fill_as_position(
    coordinator,  # ExecutionCoordinator
    *,
    ticker: str,
    stock_name: str,
    quantity: int,
    avg_price: float,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    session_id: Optional[str] = None,
    source: str = "fill_tracker",
    stop_loss_mode=None,  # Optional[StopLossMode]
    risk_score: Optional[int] = None,
) -> None:
    """Register a filled position into both monitoring engines.

    `quantity` is the INCREMENTAL fill delta (FillDelta.new_fill_qty), not an
    absolute holding. Coordinator._add_position averages/sums incrementally by
    itself; PositionManager.update_position assigns absolutely, so the
    existing-ticker branch sums existing.quantity + delta before passing it.

    `stop_loss_mode`/`risk_score` are optional so the fill-tracker poll path
    registers with the SAME semantics as the placement-fill path (which sets
    both on the position); when omitted, the ManagedPosition model defaults
    apply — existing consumers are unaffected (F3 review LOW-a).

    Coordinator registration happens first and unconditionally. PositionManager
    mirroring is best-effort: any failure (including PM not running) is caught
    and logged, never raised, since the coordinator registration already
    completed.
    """
    optional_fields = {}
    if stop_loss_mode is not None:
        optional_fields["stop_loss_mode"] = stop_loss_mode
    if risk_score is not None:
        optional_fields["risk_score"] = risk_score

    coordinator._add_position(
        ManagedPosition(
            ticker=ticker,
            stock_name=stock_name,
            quantity=quantity,
            avg_price=avg_price,
            # coordinator.py:589-599 관례: 등록 시점 현재가=체결가. 누락 시
            # Pydantic 기본값 0 → unrealized_pnl_pct 상시 -100%,
            # portfolio_agent 노출 계산이 0으로 잡힌다(이후 아무도
            # _state.positions[].current_price를 갱신하지 않음).
            current_price=avg_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            analysis_session_id=session_id,
            **optional_fields,
        )
    )

    try:
        # 지연 import: agent_chat 패키지는 트레이딩 코디네이터와 독립적으로
        # 기동/미기동될 수 있고, 순환 import를 피하기 위해 호출 시점에 로드한다.
        from services.agent_chat.coordinator import get_chat_coordinator

        chat_coordinator = await get_chat_coordinator()
        position_manager = chat_coordinator.position_manager
        if position_manager is None:
            logger.info(
                "register_fill_as_position_pm_not_running",
                ticker=ticker,
                source=source,
            )
            return

        existing = position_manager.get_position(ticker)
        if existing is None:
            position_manager.add_position(
                ticker=ticker,
                stock_name=stock_name,
                quantity=quantity,
                avg_price=avg_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
        else:
            # coalesce: PM에 이미 사용자가 설정한 스탑(non-None)이 있으면
            # 신규 체결값으로 덮어쓰지 않는다. update_position 자체도 None
            # 인자는 무시(coalesce)하므로, 기존값이 None일 때만 넘긴다.
            # quantity는 증분 델타 → update_position은 절대값 할당이므로
            # 기존 보유량에 합산해 넘긴다(2-트랜치 20+28=48; 델타를 그대로
            # 넘기면 PM만 28로 과소보고).
            position_manager.update_position(
                ticker=ticker,
                quantity=existing.quantity + quantity,
                stop_loss=stop_loss if existing.stop_loss is None else None,
                take_profit=take_profit if existing.take_profit is None else None,
            )
    except Exception as e:
        logger.warning(
            "register_fill_as_position_pm_failed",
            ticker=ticker,
            source=source,
            error=str(e),
        )
