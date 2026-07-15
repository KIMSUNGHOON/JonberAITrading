"""
Trading API Routes

Provides endpoints for auto-trading system control and monitoring.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from services.trading import (
    TradingMode,
    TradingState,
    TradingAlert,
    RiskParameters,
    StopLossMode,
    # Strategy
    RiskTolerance,
    TradingStyle,
    StrategyPreset,
    TradingStrategy,
    EntryConditions,
    ExitConditions,
    PositionSizingRules,
    get_strategy_preset,
    get_all_presets,
)
from app.dependencies import get_trading_coordinator
from services.session_manager import (
    MarketType as SessionMarketType,
    SessionStatus,
    get_session_manager,
)
from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
# agent-chat PositionManager — 홀딩 스탑 병합용 보조 소스 (get_operations 참고).
# 지연 조회(트레이딩 코디네이터에 스탑이 없을 때만 호출)이며 실패해도 홀딩 섹션은
# 살아남는다(app/api/routes/agent_chat.py:753 GET /positions와 동일한 방어 패턴).
from services.agent_chat.coordinator import get_chat_coordinator
from services.trading.paper_performance import (
    compute_cumulative_return_pct,
    compute_daily_win_loss,
    daily_pnl_series,
)
# P2-4 Task P1: display-layer cost helper for the live holdings tile below
# (get_operations) — net-of-cost projection only, never fed back into the
# broker ledger (see services/trading/fill_costs.py docstring).
from services.trading.fill_costs import effective_pnl, effective_pnl_pct
from services.storage_service import get_storage_service
from services.trading.strategy_orchestrator import (
    ACTIVE_STRATEGY_REVISION_KEY,
    run_strategy_consensus,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trading", tags=["trading"])

KST = timezone(timedelta(hours=9))

# Paper-Proof C1 운용 개시 시점 기준 자산 (2026-07-13, roadmap 기록) — 사용자가
# --base/쿼리파라미터로 덮어쓰지 않으면 이 값을 분모로 누적 수익률을 계산한다.
DEFAULT_BASE_ASSET_KRW = 500_000_000


# -------------------------------------------
# Request/Response Models
# -------------------------------------------

class StartTradingRequest(BaseModel):
    """Request to start auto-trading"""
    risk_params: Optional[RiskParameters] = None


class TradingStatusResponse(BaseModel):
    """Trading system status"""
    mode: str
    is_active: bool
    started_at: Optional[str] = None
    daily_trades: int
    max_daily_trades: int
    pending_alerts_count: int


class PortfolioSummaryResponse(BaseModel):
    """Portfolio summary"""
    total_equity: float
    cash: float
    cash_ratio: float
    stock_value: float
    stock_ratio: float
    positions: List[dict]
    total_unrealized_pnl: float
    total_unrealized_pnl_pct: float
    daily_trades: int
    max_daily_trades: int


class AlertActionRequest(BaseModel):
    """Request to handle an alert action"""
    alert_id: str
    action: str
    data: Optional[dict] = None


class RiskParamsUpdateRequest(BaseModel):
    """Request to update risk parameters"""
    max_single_position_pct: Optional[float] = Field(None, ge=0.01, le=0.5)
    min_cash_ratio: Optional[float] = Field(None, ge=0.0, le=0.9)
    max_total_stock_pct: Optional[float] = Field(None, ge=0.1, le=1.0)
    sudden_move_threshold_pct: Optional[float] = Field(None, ge=1.0, le=30.0)
    max_daily_trades: Optional[int] = Field(None, ge=1, le=100)
    # R3 autonomy safety rails (enforced by services/autonomy/gate.py)
    max_daily_loss_pct: Optional[float] = Field(None, ge=0.1, le=20.0)
    max_open_positions: Optional[int] = Field(None, ge=1, le=50)
    max_trade_notional_krw: Optional[float] = Field(None, ge=10_000)
    stop_loss_mode: Optional[str] = None
    take_profit_mode: Optional[str] = None


# -------------------------------------------
# Trading Control Endpoints
# -------------------------------------------

@router.post("/start")
async def start_trading(
    request: Optional[StartTradingRequest] = None,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Start the auto-trading system.

    Initializes:
    - Account balance sync
    - Risk monitoring
    - Alert system
    """
    try:
        if request and request.risk_params:
            # In-place update — coordinator.risk_params는 PortfolioAgent/
            # RiskMonitor/TradingState와 참조 공유라 rebind하면 그들이 옛
            # 객체를 계속 봄 (pre-existing 잠복 버그 수정, Phase4).
            incoming = request.risk_params
            for field in type(incoming).model_fields:
                setattr(coordinator.risk_params, field, getattr(incoming, field))

        await coordinator.start()

        return {
            "status": "started",
            "mode": coordinator.state.mode.value,
            "message": "Auto-trading system started",
        }

    except Exception as e:
        logger.exception("[Trading API] Start failed")
        raise HTTPException(500, f"Failed to start trading: {e}")


@router.post("/stop")
async def stop_trading(
    coordinator=Depends(get_trading_coordinator),
):
    """Stop the auto-trading system."""
    try:
        await coordinator.stop()

        return {
            "status": "stopped",
            "mode": coordinator.state.mode.value,
            "message": "Auto-trading system stopped",
        }

    except Exception as e:
        logger.exception("[Trading API] Stop failed")
        raise HTTPException(500, f"Failed to stop trading: {e}")


@router.post("/pause")
async def pause_trading(
    reason: str = "Manual pause",
    coordinator=Depends(get_trading_coordinator),
):
    """Pause auto-trading (keeps monitoring)."""
    try:
        await coordinator.pause(reason)

        return {
            "status": "paused",
            "mode": coordinator.state.mode.value,
            "message": f"Trading paused: {reason}",
        }

    except Exception as e:
        logger.exception("[Trading API] Pause failed")
        raise HTTPException(500, f"Failed to pause trading: {e}")


@router.post("/resume")
async def resume_trading(
    coordinator=Depends(get_trading_coordinator),
):
    """Resume auto-trading after pause."""
    try:
        await coordinator.resume()

        return {
            "status": "resumed",
            "mode": coordinator.state.mode.value,
            "message": "Trading resumed",
        }

    except Exception as e:
        logger.exception("[Trading API] Resume failed")
        raise HTTPException(500, f"Failed to resume trading: {e}")


# -------------------------------------------
# Status Endpoints
# -------------------------------------------

@router.get("/status", response_model=TradingStatusResponse)
async def get_trading_status(
    coordinator=Depends(get_trading_coordinator),
):
    """Get current trading system status."""
    state = coordinator.state

    return TradingStatusResponse(
        mode=state.mode.value,
        is_active=coordinator.is_active,
        started_at=state.started_at.isoformat() if state.started_at else None,
        daily_trades=state.daily_trades_count,
        max_daily_trades=state.risk_params.max_daily_trades,
        pending_alerts_count=len(coordinator.get_pending_alerts()),
    )


@router.get("/portfolio", response_model=PortfolioSummaryResponse)
async def get_portfolio(
    coordinator=Depends(get_trading_coordinator),
):
    """Get portfolio summary."""
    summary = coordinator.get_portfolio_summary()
    return PortfolioSummaryResponse(**summary)


@router.get("/state")
async def get_full_state(
    coordinator=Depends(get_trading_coordinator),
):
    """Get complete trading state (for debugging)."""
    return coordinator.state.model_dump()


# -------------------------------------------
# Alert Endpoints
# -------------------------------------------

@router.get("/alerts")
async def get_alerts(
    coordinator=Depends(get_trading_coordinator),
):
    """Get all pending alerts."""
    alerts = coordinator.get_pending_alerts()
    return {
        "alerts": [a.model_dump() for a in alerts],
        "count": len(alerts),
    }


@router.post("/alerts/action")
async def handle_alert_action(
    request: AlertActionRequest,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Handle user action on an alert.

    Actions depend on alert type:
    - SUDDEN_MOVE: RESUME, CLOSE_POSITION, ADJUST_STOP_LOSS
    - STOP_LOSS_TRIGGERED: EXECUTE_STOP_LOSS, ADJUST_STOP_LOSS, HOLD
    - TAKE_PROFIT_TRIGGERED: EXECUTE_TAKE_PROFIT, ADJUST_TARGET, HOLD
    """
    try:
        await coordinator.handle_alert_action(
            alert_id=request.alert_id,
            action=request.action,
            data=request.data,
        )

        return {
            "status": "success",
            "message": f"Action '{request.action}' applied",
        }

    except Exception as e:
        logger.exception("[Trading API] Alert action failed")
        raise HTTPException(500, f"Failed to handle action: {e}")


# -------------------------------------------
# Risk Parameters Endpoints
# -------------------------------------------

@router.get("/risk-params")
async def get_risk_params(
    coordinator=Depends(get_trading_coordinator),
):
    """Get current risk parameters."""
    return coordinator.risk_params.model_dump()


@router.put("/risk-params")
async def update_risk_params(
    request: RiskParamsUpdateRequest,
    coordinator=Depends(get_trading_coordinator),
):
    """Update risk parameters."""
    params = coordinator.risk_params

    if request.max_single_position_pct is not None:
        params.max_single_position_pct = request.max_single_position_pct

    if request.min_cash_ratio is not None:
        params.min_cash_ratio = request.min_cash_ratio

    if request.max_total_stock_pct is not None:
        params.max_total_stock_pct = request.max_total_stock_pct

    if request.sudden_move_threshold_pct is not None:
        params.sudden_move_threshold_pct = request.sudden_move_threshold_pct

    if request.max_daily_trades is not None:
        params.max_daily_trades = request.max_daily_trades

    if request.max_daily_loss_pct is not None:
        params.max_daily_loss_pct = request.max_daily_loss_pct

    if request.max_open_positions is not None:
        params.max_open_positions = request.max_open_positions

    if request.max_trade_notional_krw is not None:
        params.max_trade_notional_krw = request.max_trade_notional_krw

    if request.stop_loss_mode is not None:
        params.stop_loss_mode = StopLossMode(request.stop_loss_mode)

    if request.take_profit_mode is not None:
        params.take_profit_mode = StopLossMode(request.take_profit_mode)

    return {
        "status": "updated",
        "risk_params": params.model_dump(),
    }


# -------------------------------------------
# Position Endpoints
# -------------------------------------------

@router.get("/positions")
async def get_positions(
    coordinator=Depends(get_trading_coordinator),
):
    """Get all managed positions."""
    positions = coordinator.state.positions
    return {
        "positions": [p.model_dump() for p in positions],
        "count": len(positions),
    }


@router.delete("/positions/{ticker}")
async def close_position(
    ticker: str,
    coordinator=Depends(get_trading_coordinator),
):
    """Close a specific position."""
    try:
        await coordinator._close_position(ticker)

        return {
            "status": "closed",
            "ticker": ticker,
            "message": f"Position {ticker} closed",
        }

    except Exception as e:
        logger.exception(f"[Trading API] Close position failed: {ticker}")
        raise HTTPException(500, f"Failed to close position: {e}")


@router.put("/positions/{ticker}/stop-loss")
async def update_position_stop_loss(
    ticker: str,
    stop_loss: float,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Update stop-loss for a position.

    T7 review C1 fix: this used to unconditionally return
    {"status": "updated"} even when `ticker` was not tracked by
    RiskMonitor — which is ALWAYS true for coin positions (they live in a
    separate storage-backed table, `coin_positions`, and never enter
    RiskMonitor's `_watching`). Now: try RiskMonitor first (the autonomy
    surface); if that's a no-op, fall back to persisting directly into the
    coin position store — the actual source `PositionsPanel` reads for
    coin rows — so the edit takes real effect; if NEITHER surface knows
    this ticker, raise an honest 404 instead of a fake success.
    """
    if coordinator.risk_monitor.update_stop_loss(ticker, stop_loss):
        return {"status": "updated", "ticker": ticker, "stop_loss": stop_loss, "source": "risk_monitor"}

    from services.storage_service import get_storage_service

    storage = await get_storage_service()
    market = ticker.upper()
    if await storage.get_coin_position(market) and await storage.update_coin_position(
        market, {"stop_loss": stop_loss}
    ):
        return {"status": "updated", "ticker": market, "stop_loss": stop_loss, "source": "coin_position_store"}

    raise HTTPException(
        status_code=404,
        detail=f"활성 리스크 관리 대상이 아니며 저장된 포지션도 없습니다: {ticker}",
    )


@router.put("/positions/{ticker}/take-profit")
async def update_position_take_profit(
    ticker: str,
    take_profit: float,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Update take-profit for a position.

    See `update_position_stop_loss` — same honesty fix (T7 review C1).
    """
    if coordinator.risk_monitor.update_take_profit(ticker, take_profit):
        return {"status": "updated", "ticker": ticker, "take_profit": take_profit, "source": "risk_monitor"}

    from services.storage_service import get_storage_service

    storage = await get_storage_service()
    market = ticker.upper()
    if await storage.get_coin_position(market) and await storage.update_coin_position(
        market, {"take_profit": take_profit}
    ):
        return {"status": "updated", "ticker": market, "take_profit": take_profit, "source": "coin_position_store"}

    raise HTTPException(
        status_code=404,
        detail=f"활성 리스크 관리 대상이 아니며 저장된 포지션도 없습니다: {ticker}",
    )


# -------------------------------------------
# Activity Log Endpoints
# -------------------------------------------

@router.get("/activity")
async def get_activity_log(
    limit: int = 50,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Get recent activity log entries.

    Shows agent decisions, orders, and system events.
    """
    activities = coordinator.get_activity_log(limit)
    return {
        "activities": [a.model_dump() for a in activities],
        "count": len(activities),
    }


# -------------------------------------------
# Market Hours Endpoints
# -------------------------------------------

class MarketStatusResponse(BaseModel):
    """Market status response for frontend"""
    market: str
    name: str
    is_open: bool
    message: str
    current_time: str
    next_open: Optional[str] = None
    next_close: Optional[str] = None
    countdown_seconds: int = 0  # Seconds until next_open or next_close


def _calculate_countdown(target_time, current_time) -> int:
    """Calculate seconds until target time."""
    if target_time is None:
        return 0
    delta = target_time - current_time
    return max(0, int(delta.total_seconds()))


@router.get("/market-status")
async def get_market_status(market: str = "krx"):
    """
    Get current market status with countdown.

    This endpoint is optimized for frontend use with countdown_seconds.

    Args:
        market: Market type (krx, crypto). Default: krx

    Returns:
        Market status with countdown in seconds.
    """
    from services.trading import get_market_hours_service, MarketType

    market_hours = get_market_hours_service()

    try:
        market_type = MarketType(market.lower())
    except ValueError:
        market_type = MarketType.KRX

    session = market_hours.get_market_session(market_type)

    # Calculate countdown
    if session.is_open:
        countdown = _calculate_countdown(session.next_close, session.current_time)
    else:
        countdown = _calculate_countdown(session.next_open, session.current_time)

    return MarketStatusResponse(
        market=market_type.value.upper(),
        name="Korea Exchange" if market_type == MarketType.KRX else "Cryptocurrency",
        is_open=session.is_open,
        message=session.message,
        current_time=session.current_time.isoformat(),
        next_open=session.next_open.isoformat() if session.next_open else None,
        next_close=session.next_close.isoformat() if session.next_close else None,
        countdown_seconds=countdown,
    )


@router.get("/market-hours")
async def get_market_hours():
    """
    Get current market session status.

    Returns trading hours information for supported markets.
    """
    from services.trading import get_market_hours_service, MarketType

    market_hours = get_market_hours_service()

    krx_session = market_hours.get_market_session(MarketType.KRX)
    crypto_session = market_hours.get_market_session(MarketType.CRYPTO)

    return {
        "krx": {
            "market": "KRX",
            "name": "Korea Exchange",
            "is_open": krx_session.is_open,
            "message": krx_session.message,
            "current_time": krx_session.current_time.isoformat(),
            "next_open": krx_session.next_open.isoformat() if krx_session.next_open else None,
            "next_close": krx_session.next_close.isoformat() if krx_session.next_close else None,
            "countdown_seconds": _calculate_countdown(
                krx_session.next_close if krx_session.is_open else krx_session.next_open,
                krx_session.current_time
            ),
        },
        "crypto": {
            "market": "CRYPTO",
            "name": "Cryptocurrency",
            "is_open": crypto_session.is_open,
            "message": crypto_session.message,
            "current_time": crypto_session.current_time.isoformat(),
        },
    }


# -------------------------------------------
# Strategy Endpoints
# -------------------------------------------

class StrategyCreateRequest(BaseModel):
    """Request to create a custom strategy"""
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="")
    preset: Optional[str] = Field(default=None)  # Base preset to copy from
    risk_tolerance: str = Field(default="moderate")
    trading_style: str = Field(default="position")
    system_prompt: str = Field(default="")
    entry_conditions: Optional[dict] = None
    exit_conditions: Optional[dict] = None
    position_sizing: Optional[dict] = None
    custom_instructions: str = Field(default="")


class StrategyUpdateRequest(BaseModel):
    """Request to update a strategy"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    risk_tolerance: Optional[str] = None
    trading_style: Optional[str] = None
    system_prompt: Optional[str] = None
    entry_conditions: Optional[dict] = None
    exit_conditions: Optional[dict] = None
    position_sizing: Optional[dict] = None
    custom_instructions: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/strategies/presets")
async def get_strategy_presets():
    """
    Get all available strategy presets.

    Returns pre-defined trading strategies with their configurations.
    """
    return {
        "presets": get_all_presets(),
        "risk_tolerances": [r.value for r in RiskTolerance],
        "trading_styles": [s.value for s in TradingStyle],
    }


@router.get("/strategies/presets/{preset_name}")
async def get_preset_details(preset_name: str):
    """
    Get detailed configuration of a specific preset.
    """
    try:
        preset_enum = StrategyPreset(preset_name)
        strategy = get_strategy_preset(preset_enum)
        return strategy.model_dump()
    except ValueError:
        raise HTTPException(404, f"Preset '{preset_name}' not found")


async def _persist_manual_strategy(strategy) -> bool:
    """POST/PUT /strategy의 인메모리 적용을 revision 원장에 미러(source=
    'manual') + 활성 포인터 이동. 실패는 정직 강등(False) — 인메모리 적용
    자체(현행 동작)는 유지된다."""
    from uuid import uuid4

    try:
        storage = await get_storage_service()
        revision_id = str(uuid4())
        parent_id = await storage.get_app_setting(ACTIVE_STRATEGY_REVISION_KEY)
        strategy.id = revision_id
        saved = await storage.save_strategy_revision({
            "id": revision_id,
            "trade_date": datetime.now().strftime("%Y-%m-%d"),
            "source": "manual",
            "stance": None,
            "consensus_level": None,
            "changed": 1,
            "strategy_json": strategy.model_dump_json(),
            "parent_revision_id": parent_id or None,
            "rationale": "manual set via /trading/strategy",
            "votes_json": None,
            "regime_snapshot_id": None,
        })
        if saved:
            await storage.set_app_setting(ACTIVE_STRATEGY_REVISION_KEY, revision_id)
        return saved
    except Exception as e:
        logger.warning(f"manual strategy persist failed: {e}")
        return False


@router.get("/strategy")
async def get_current_strategy(
    coordinator=Depends(get_trading_coordinator),
):
    """
    Get the currently active trading strategy.
    """
    strategy = coordinator.get_strategy()
    if strategy:
        return strategy.model_dump()
    return {"strategy": None, "message": "No strategy configured"}


@router.post("/strategy")
async def set_strategy(
    request: StrategyCreateRequest,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Create and set a new trading strategy.

    You can start from a preset or create a completely custom strategy.
    """
    try:
        # If a preset is specified, start from it
        if request.preset:
            try:
                preset_enum = StrategyPreset(request.preset)
                base_strategy = get_strategy_preset(preset_enum)
                # Copy preset values as base
                strategy_data = base_strategy.model_dump()
            except ValueError:
                raise HTTPException(400, f"Invalid preset: {request.preset}")
        else:
            strategy_data = {}

        # Override with request data
        strategy_data["name"] = request.name
        strategy_data["description"] = request.description
        strategy_data["preset"] = StrategyPreset.CUSTOM  # Always mark as custom once edited

        # Handle risk tolerance
        if request.risk_tolerance:
            try:
                strategy_data["risk_tolerance"] = RiskTolerance(request.risk_tolerance)
            except ValueError:
                raise HTTPException(400, f"Invalid risk_tolerance: {request.risk_tolerance}")

        # Handle trading style
        if request.trading_style:
            try:
                strategy_data["trading_style"] = TradingStyle(request.trading_style)
            except ValueError:
                raise HTTPException(400, f"Invalid trading_style: {request.trading_style}")

        # Handle system prompt
        if request.system_prompt:
            strategy_data["system_prompt"] = request.system_prompt

        # Handle conditions
        if request.entry_conditions:
            strategy_data["entry_conditions"] = EntryConditions(**request.entry_conditions)

        if request.exit_conditions:
            strategy_data["exit_conditions"] = ExitConditions(**request.exit_conditions)

        if request.position_sizing:
            strategy_data["position_sizing"] = PositionSizingRules(**request.position_sizing)

        if request.custom_instructions:
            strategy_data["custom_instructions"] = request.custom_instructions

        # Create strategy
        strategy = TradingStrategy(**strategy_data)

        # Set in coordinator
        coordinator.set_strategy(strategy)

        logger.info(f"[Strategy API] Set strategy: {strategy.name}")

        persisted = await _persist_manual_strategy(strategy)

        return {
            "status": "created",
            "strategy": strategy.model_dump(),
            "persisted": persisted,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Strategy API] Failed to create strategy")
        raise HTTPException(500, f"Failed to create strategy: {e}")


@router.put("/strategy")
async def update_strategy(
    request: StrategyUpdateRequest,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Update the current trading strategy.
    """
    try:
        current = coordinator.get_strategy()
        if not current:
            raise HTTPException(404, "No strategy to update")

        # Get current strategy data
        strategy_data = current.model_dump()

        # Update fields
        if request.name is not None:
            strategy_data["name"] = request.name

        if request.description is not None:
            strategy_data["description"] = request.description

        if request.risk_tolerance is not None:
            try:
                strategy_data["risk_tolerance"] = RiskTolerance(request.risk_tolerance)
            except ValueError:
                raise HTTPException(400, f"Invalid risk_tolerance: {request.risk_tolerance}")

        if request.trading_style is not None:
            try:
                strategy_data["trading_style"] = TradingStyle(request.trading_style)
            except ValueError:
                raise HTTPException(400, f"Invalid trading_style: {request.trading_style}")

        if request.system_prompt is not None:
            strategy_data["system_prompt"] = request.system_prompt

        if request.entry_conditions is not None:
            strategy_data["entry_conditions"] = EntryConditions(**request.entry_conditions)

        if request.exit_conditions is not None:
            strategy_data["exit_conditions"] = ExitConditions(**request.exit_conditions)

        if request.position_sizing is not None:
            strategy_data["position_sizing"] = PositionSizingRules(**request.position_sizing)

        if request.custom_instructions is not None:
            strategy_data["custom_instructions"] = request.custom_instructions

        if request.is_active is not None:
            strategy_data["is_active"] = request.is_active

        # Mark as custom since it's been edited
        strategy_data["preset"] = StrategyPreset.CUSTOM

        # Update timestamp
        from datetime import datetime
        strategy_data["updated_at"] = datetime.now()

        # Create updated strategy
        strategy = TradingStrategy(**strategy_data)

        # Set in coordinator
        coordinator.set_strategy(strategy)

        logger.info(f"[Strategy API] Updated strategy: {strategy.name}")

        persisted = await _persist_manual_strategy(strategy)

        return {
            "status": "updated",
            "strategy": strategy.model_dump(),
            "persisted": persisted,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Strategy API] Failed to update strategy")
        raise HTTPException(500, f"Failed to update strategy: {e}")


@router.delete("/strategy")
async def clear_strategy(
    coordinator=Depends(get_trading_coordinator),
):
    """
    Clear the current trading strategy.
    """
    coordinator.set_strategy(None)
    logger.info("[Strategy API] Strategy cleared")

    try:
        storage = await get_storage_service()
        await storage.set_app_setting(ACTIVE_STRATEGY_REVISION_KEY, "")
    except Exception as e:
        logger.warning(f"strategy pointer clear failed: {e}")

    return {
        "status": "cleared",
        "message": "Trading strategy has been cleared",
    }


@router.post("/strategy/apply-preset/{preset_name}")
async def apply_preset(
    preset_name: str,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Apply a preset strategy directly.
    """
    try:
        preset_enum = StrategyPreset(preset_name)
        # deep copy REQUIRED before persistence: get_strategy_preset returns
        # the shared module-level STRATEGY_PRESETS instance for non-CUSTOM
        # presets, and _persist_manual_strategy mutates strategy.id — without
        # the copy that would corrupt the global preset object.
        strategy = get_strategy_preset(preset_enum).model_copy(deep=True)

        coordinator.set_strategy(strategy)

        logger.info(f"[Strategy API] Applied preset: {preset_name}")

        persisted = await _persist_manual_strategy(strategy)

        return {
            "status": "applied",
            "preset": preset_name,
            "strategy": strategy.model_dump(),
            "persisted": persisted,
        }

    except ValueError:
        raise HTTPException(404, f"Preset '{preset_name}' not found")


@router.get("/strategy/revisions")
async def get_strategy_revisions(limit: int = 30):
    """Phase3: 전략 버전 이력 (최신순). strategy_json/votes_json은 파싱해
    내보낸다(FE 편의)."""
    storage = await get_storage_service()
    rows = await storage.get_strategy_revisions(limit=limit)
    active_id = await storage.get_app_setting(ACTIVE_STRATEGY_REVISION_KEY)
    revisions = []
    for row in rows:
        item = dict(row)
        for key in ("strategy_json", "votes_json"):
            try:
                item[key] = json.loads(item[key]) if item.get(key) else None
            except (TypeError, ValueError):
                pass  # 손상 blob은 원문 그대로 정직 노출
        item["is_active"] = row["id"] == active_id
        revisions.append(item)
    return {"revisions": revisions, "active_revision_id": active_id or None}


class ConsensusRunRequest(BaseModel):
    trade_date: Optional[str] = None  # 생략 시 오늘


@router.post("/strategy/consensus/run")
async def run_consensus_now(
    request: ConsensusRunRequest,
    coordinator=Depends(get_trading_coordinator),
):
    """Phase3: 수동 전략 합의 실행 (배포 검증·백필용). ENABLED 게이트를
    우회(force)하지만 never-raise 계약은 동일 — 실패도 200 + ok=False."""
    trade_date = request.trade_date or datetime.now().strftime("%Y-%m-%d")
    storage = await get_storage_service()
    return await run_strategy_consensus(coordinator, storage, trade_date, force=True)


# -------------------------------------------
# Trade Queue Endpoints
# -------------------------------------------

class AddToQueueRequest(BaseModel):
    """Request to add a trade directly to queue"""
    ticker: str
    stock_name: Optional[str] = None
    action: str  # "BUY" or "SELL"
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_score: int = Field(default=5, ge=1, le=10)
    session_id: Optional[str] = None
    reason: str = "Manual queue addition"


@router.post("/queue/add")
async def add_to_trade_queue(
    request: AddToQueueRequest,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Add a trade directly to the queue.

    This bypasses the approval flow and adds the trade directly.
    Useful for adding trades from completed analyses.
    """
    try:
        import uuid

        # Generate session ID if not provided
        session_id = request.session_id or str(uuid.uuid4())

        # Add to queue
        queued_trade = coordinator.add_to_queue(
            session_id=session_id,
            ticker=request.ticker,
            stock_name=request.stock_name,
            action=request.action,
            entry_price=request.entry_price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            risk_score=request.risk_score,
            reason=request.reason,
        )

        logger.info(f"[Trading API] Added to queue: {request.ticker} - {request.action}")

        return {
            "status": "queued",
            "queue_id": queued_trade.id,
            "ticker": request.ticker,
            "action": request.action,
            "message": f"Trade queued: {request.action} {request.stock_name or request.ticker}",
        }

    except Exception as e:
        logger.exception("[Trading API] Failed to add to queue")
        raise HTTPException(500, f"Failed to add to queue: {e}")


@router.get("/queue")
async def get_trade_queue(
    include_all: bool = False,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Get trades in queue.

    Args:
        include_all: If True, returns all trades including FAILED/COMPLETED/CANCELLED.
                    If False (default), returns only PENDING and PROCESSING trades.
    """
    queue = coordinator.get_trade_queue(include_all=include_all)
    return {
        "queue": [t.model_dump() for t in queue],
        "count": len(queue),
    }


@router.delete("/queue/{queue_id}")
async def cancel_queued_trade(
    queue_id: str,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Cancel a queued trade.
    """
    success = coordinator.cancel_queued_trade(queue_id)
    if not success:
        raise HTTPException(404, f"Queued trade '{queue_id}' not found or already processed")

    return {
        "status": "cancelled",
        "queue_id": queue_id,
    }


@router.delete("/queue/{queue_id}/dismiss")
async def dismiss_trade(
    queue_id: str,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Dismiss a completed/failed/cancelled trade from the queue.

    This removes the trade from the queue entirely.
    Only works for trades that are not PENDING or PROCESSING.
    """
    success = coordinator.dismiss_trade(queue_id)
    if not success:
        raise HTTPException(
            400,
            f"Cannot dismiss trade '{queue_id}': not found or still active"
        )

    return {
        "status": "dismissed",
        "queue_id": queue_id,
    }


@router.post("/queue/process")
async def process_trade_queue(
    coordinator=Depends(get_trading_coordinator),
):
    """
    Manually process the trade queue.

    Normally this happens automatically when market opens.
    """
    await coordinator.process_trade_queue()

    return {
        "status": "processed",
        "message": "Trade queue processing completed",
    }


# -------------------------------------------
# Watch List Endpoints
# -------------------------------------------

class AddToWatchListRequest(BaseModel):
    """Request to add a stock to watch list"""
    ticker: str
    stock_name: Optional[str] = None
    signal: str = "hold"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    current_price: float
    target_entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    analysis_summary: str = ""
    key_factors: Optional[List[str]] = None
    risk_score: int = Field(default=5, ge=1, le=10)
    session_id: Optional[str] = None


class ConvertWatchToQueueRequest(BaseModel):
    """Request to convert watch list item to trade queue"""
    watch_id: str
    action: str = "BUY"
    reason: str = "User converted from watch list"


@router.get("/watch-list")
async def get_watch_list(
    coordinator=Depends(get_trading_coordinator),
):
    """
    Get all stocks in watch list.

    Returns stocks that have WATCH recommendation for monitoring.
    """
    watch_list = coordinator.get_watch_list()
    return {
        "watch_list": [w.model_dump() for w in watch_list],
        "count": len(watch_list),
    }


@router.post("/watch-list/add")
async def add_to_watch_list(
    request: AddToWatchListRequest,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Add a stock to the watch list.

    Use this to track stocks that are not yet ready for immediate buying
    but should be monitored for potential entry.
    """
    try:
        import uuid

        # Generate session ID if not provided
        session_id = request.session_id or str(uuid.uuid4())

        # Add to watch list
        watched = coordinator.add_to_watch_list(
            session_id=session_id,
            ticker=request.ticker,
            stock_name=request.stock_name,
            signal=request.signal,
            confidence=request.confidence,
            current_price=request.current_price,
            target_entry_price=request.target_entry_price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            analysis_summary=request.analysis_summary,
            key_factors=request.key_factors,
            risk_score=request.risk_score,
        )

        logger.info(f"[Trading API] Added to watch list: {request.ticker}")

        return {
            "status": "added",
            "watch_id": watched.id,
            "ticker": request.ticker,
            "message": f"Added to watch list: {request.stock_name or request.ticker}",
        }

    except Exception as e:
        logger.exception("[Trading API] Failed to add to watch list")
        raise HTTPException(500, f"Failed to add to watch list: {e}")


@router.delete("/watch-list/{watch_id}")
async def remove_from_watch_list(
    watch_id: str,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Remove a stock from the watch list.
    """
    success = coordinator.remove_from_watch_list(watch_id)
    if not success:
        raise HTTPException(404, f"Watch list item '{watch_id}' not found or already removed")

    return {
        "status": "removed",
        "watch_id": watch_id,
    }


@router.post("/watch-list/convert")
async def convert_watch_to_queue(
    request: ConvertWatchToQueueRequest,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Convert a watched stock to the trade queue.

    Use this when you decide to buy a stock that was on the watch list.
    """
    try:
        queued = coordinator.convert_watch_to_queue(
            watch_id=request.watch_id,
            action=request.action,
            reason=request.reason,
        )

        if not queued:
            raise HTTPException(404, f"Watch list item '{request.watch_id}' not found or already converted")

        logger.info(f"[Trading API] Converted watch to queue: {request.watch_id} -> {queued.id}")

        return {
            "status": "converted",
            "watch_id": request.watch_id,
            "queue_id": queued.id,
            "ticker": queued.ticker,
            "action": request.action,
            "message": f"Converted to trade queue: {queued.stock_name or queued.ticker}",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Trading API] Failed to convert watch to queue")
        raise HTTPException(500, f"Failed to convert: {e}")


@router.get("/watch-list/{ticker}")
async def get_watched_stock(
    ticker: str,
    coordinator=Depends(get_trading_coordinator),
):
    """
    Get watch list item by ticker.
    """
    watched = coordinator.get_watched_stock(ticker)
    if not watched:
        raise HTTPException(404, f"Stock '{ticker}' not found in watch list")

    return watched.model_dump()


# -------------------------------------------
# Agent Status Endpoints
# -------------------------------------------

@router.get("/agents")
async def get_agent_states(
    coordinator=Depends(get_trading_coordinator),
):
    """
    Get status of all trading agents.

    Returns current task and status for each agent:
    - Portfolio Agent: Position sizing and allocation
    - Order Agent: Order execution
    - Risk Monitor: Stop-loss/take-profit monitoring
    """
    return {
        "agents": coordinator.get_agent_states(),
    }


# ─── Operations pipeline aggregate (spec 2026-07-13-operations-pipeline-board) ───

class OperationsAnalyzing(BaseModel):
    session_id: str
    ticker: str
    name: Optional[str] = None
    status: str
    current_stage: Optional[str] = None
    started_at: Optional[str] = None


class OperationsAwaiting(BaseModel):
    session_id: str
    ticker: str
    name: Optional[str] = None
    proposal: Optional[Dict[str, Any]] = None  # session.state["trade_proposal"] 원본
    auto_approve_at: Optional[str] = None
    # Zombie-resurrection guard: a sm row can be stuck at status=AWAITING_APPROVAL
    # while its state["awaiting_approval"] was already cleared (e.g. a cancel whose
    # sm mirror failed) — surface that mismatch so the board can't offer a doomed
    # approve/reject on an unapprovable session.
    actionable: bool = True


class OperationsOpenOrder(BaseModel):
    order_id: str
    stk_cd: str
    stk_nm: Optional[str] = None
    side: str  # "buy" | "sell"
    price: Optional[int] = None
    quantity: int
    remaining_quantity: int
    executed_quantity: int = 0
    created_at: Optional[str] = None


class OperationsPendingBuy(BaseModel):
    queue: Optional[List[Dict[str, Any]]] = None
    open_orders: Optional[List[OperationsOpenOrder]] = None


class OperationsHolding(BaseModel):
    ticker: str
    name: Optional[str] = None
    quantity: int
    avg_price: float
    current_price: float
    pnl: float
    pnl_pct: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class OperationsFill(BaseModel):
    ticker: str
    name: Optional[str] = None
    side: str  # "buy" | "sell"
    quantity: int
    price: int
    time: str  # HHMMSS


# Fields the FE consumer actually reads (OperationsPanel.tsx +
# kiwoomSessionHandlers.ts rehydrateKiwoomSessions) — everything else,
# notably `analyses` (the full per-agent LLM output array) and any other
# internal KRStockTradeProposal bookkeeping, is dropped so a 5s poll doesn't
# re-serialize the whole analysis payload.
_PROPOSAL_SLIM_KEYS = (
    "id", "stk_cd", "stk_nm", "action", "quantity",
    "entry_price", "stop_loss", "take_profit",
    "risk_score", "position_size_pct",
    "rationale", "bull_case", "bear_case", "created_at",
)


def _slim_proposal(proposal: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Strip a raw `trade_proposal` state dict down to the FE-facing fields."""
    if proposal is None:
        return None
    return {k: proposal[k] for k in _PROPOSAL_SLIM_KEYS if k in proposal}


class OperationsResponse(BaseModel):
    analyzing: Optional[List[OperationsAnalyzing]] = None
    awaiting: Optional[List[OperationsAwaiting]] = None
    watching: Optional[List[Dict[str, Any]]] = None
    pending_buy: OperationsPendingBuy
    holding: Optional[List[OperationsHolding]] = None
    today_fills: Optional[List[OperationsFill]] = None
    errors: Dict[str, str] = {}


@router.get("/operations", response_model=OperationsResponse)
async def get_operations(
    market: str = "kiwoom",
    coordinator=Depends(get_trading_coordinator),
):
    """운용 파이프라인 스냅샷 — 섹션별 독립 수집, 실패는 null+errors(위장 금지)."""
    errors: Dict[str, str] = {}
    res: Dict[str, Any] = {
        "analyzing": None, "awaiting": None, "watching": None,
        "pending_buy": OperationsPendingBuy(), "holding": None,
        "today_fills": None, "errors": errors,
    }

    # 1) 세션 (분석중 / 승인대기) — SQLite 영속이라 재시작도 견딤
    try:
        sm = await get_session_manager()
        mt = SessionMarketType.COIN if market == "coin" else SessionMarketType.KIWOOM
        sessions = await sm.get_all_sessions(market_type=mt)
        analyzing, awaiting = [], []
        for s in sessions.values():
            if s.status == SessionStatus.RUNNING:
                analyzing.append(OperationsAnalyzing(
                    session_id=s.session_id, ticker=s.ticker,
                    name=s.display_name, status=s.status.value,
                    current_stage=s.state.get("current_stage"),
                    started_at=s.created_at.isoformat() if s.created_at else None,
                ))
            elif s.status == SessionStatus.AWAITING_APPROVAL:
                awaiting.append(OperationsAwaiting(
                    session_id=s.session_id, ticker=s.ticker,
                    name=s.display_name,
                    proposal=_slim_proposal(s.state.get("trade_proposal")),
                    auto_approve_at=s.state.get("auto_approve_at"),
                    actionable=bool(s.state.get("awaiting_approval")),
                ))
        res["analyzing"], res["awaiting"] = analyzing, awaiting
    except Exception as e:  # noqa: BLE001 — 섹션 독립 강등
        errors["sessions"] = str(e)

    if market != "kiwoom":
        # 코인: 큐/감시/브로커 섹션은 비해당(null, errors 없음)
        return OperationsResponse(**res)

    # 2) 감시 / 큐 (코디네이터 인메모리 — 실패 가능성 낮음, 그래도 독립)
    try:
        res["watching"] = [w.model_dump() for w in coordinator.get_watch_list()]
    except Exception as e:  # noqa: BLE001
        errors["watching"] = str(e)
    queue_items: Optional[List[Dict[str, Any]]] = None
    try:
        queue_items = [t.model_dump() for t in coordinator.get_trade_queue()]
    except Exception as e:  # noqa: BLE001
        errors["queue"] = str(e)

    # 3) 브로커 3종 — 각각 독립 수집
    open_orders: Optional[List[OperationsOpenOrder]] = None
    try:
        client = await get_shared_kiwoom_client_async()
    except Exception as e:  # noqa: BLE001
        client = None
        for k in ("open_orders", "holding", "today_fills"):
            errors[k] = str(e)

    if client is not None:
        try:
            raw = await client.get_pending_orders()
            open_orders = [
                OperationsOpenOrder(
                    order_id=o.ord_no, stk_cd=o.stk_cd, stk_nm=o.stk_nm,
                    # 소비자 계약(services/kiwoom/models.py, client._normalize_buy_sell):
                    # buy_sell_tp "1"=매수, "2"=매도. PendingOrder에는 trde_tp 필드가
                    # 없다 — buy_sell_tp가 유일한 매매구분 소스(orders.py:156 동일 관례).
                    side="buy" if o.buy_sell_tp in ("1", "01", "매수") else "sell",
                    price=o.ord_uv, quantity=o.ord_qty,
                    remaining_quantity=o.rmn_qty, executed_quantity=o.ccld_qty,
                    created_at=o.ord_tm,
                )
                for o in raw
            ]
        except Exception as e:  # noqa: BLE001
            errors["open_orders"] = str(e)

        try:
            balance = await client.get_account_balance()
            stops = {p.ticker: p for p in coordinator.state.positions}

            # 스탑 소스 2순위: agent-chat PositionManager (services/agent_chat/
            # position_manager.py). 필드별 coalescing — 트레이딩 코디네이터
            # ManagedPosition의 stop_loss/take_profit 각각이 None이 아니면 그 값이
            # 우선(1순위)이고, None인 필드만 PositionManager에서 보충한다(포지션
            # 존재 자체가 스탑을 가리지 않도록; 예: 코디네이터 포지션에
            # stop_loss=None인데 agent-chat 스탑이 걸려 있는 경우). 양 필드가 모두
            # 코디네이터에서 채워지면 PM은 조회하지 않는다(지연). 조회 자체가
            # 실패하거나 코디네이터/포지션매니저가 미기동이어도 홀딩 섹션은 그대로
            # 살아남는다 (agent_chat.py:753 GET /positions와 동일한 방어:
            # get_chat_coordinator → position_manager None 체크).
            chat_pm_box: Dict[str, Any] = {}

            async def _chat_pm():
                if "pm" not in chat_pm_box:
                    try:
                        chat_coordinator = await get_chat_coordinator()
                        chat_pm_box["pm"] = chat_coordinator.position_manager
                    except Exception:  # noqa: BLE001 — enrichment only, never fail holding
                        chat_pm_box["pm"] = None
                return chat_pm_box["pm"]

            async def _stops_for(ticker: str):
                managed = stops.get(ticker)
                stop_loss = getattr(managed, "stop_loss", None)
                take_profit = getattr(managed, "take_profit", None)
                if stop_loss is not None and take_profit is not None:
                    return stop_loss, take_profit
                pm = await _chat_pm()
                pos = pm.get_position(ticker) if pm is not None else None
                if pos is not None:
                    if stop_loss is None:
                        stop_loss = pos.stop_loss
                    if take_profit is None:
                        take_profit = pos.take_profit
                return stop_loss, take_profit

            # balance.holdings = services.kiwoom.models.Holding (kt00004) —
            # 실제 필드는 hldg_qty/avg_buy_prc/cur_prc/evlu_pfls_amt/evlu_pfls_rt
            # (quantity/avg_buy_price 등은 API 스키마 KRStockHolding의 이름;
            # kr_stocks/orders.py:68-73의 매핑과 동일 소스·동일 변환).
            #
            # P2-4 Task P1: pnl/pnl_pct here are DISPLAY values only — this
            # is the live real-time position tile's actual data source (see
            # frontend/src/components/terminal/panels/PositionsPanel.tsx
            # header note: KR rows read `getOperations('kiwoom')`, not
            # kr_stocks/positions.py). The broker's raw evlu_pfls_amt/
            # evlu_pfls_rt (price-diff only) never account for the
            # round-trip cost of actually exiting, so they're run through
            # `effective_pnl`/`effective_pnl_pct` (services/trading/
            # fill_costs.py) net of KR commission (both legs) + sell tax.
            # This does NOT touch the broker ledger itself (kt00004
            # current_asset / ka10074 realized P&L stay untouched, and so
            # does ManagedPosition.unrealized_pnl) — it only changes what
            # gets displayed here.
            holdings_out = []
            for h in balance.holdings:
                stop_loss, take_profit = await _stops_for(h.stk_cd)
                avg_price = float(h.avg_buy_prc)
                current_price = float(h.cur_prc)
                quantity = float(h.hldg_qty)
                holdings_out.append(OperationsHolding(
                    ticker=h.stk_cd, name=h.stk_nm, quantity=h.hldg_qty,
                    avg_price=avg_price,
                    current_price=current_price,
                    pnl=effective_pnl(avg_price, current_price, quantity, "BUY"),
                    pnl_pct=effective_pnl_pct(avg_price, current_price, quantity, "BUY"),
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                ))
            res["holding"] = holdings_out
        except Exception as e:  # noqa: BLE001
            errors["holding"] = str(e)

        try:
            fills = await client.get_filled_orders()
            res["today_fills"] = [
                OperationsFill(
                    ticker=f.stk_cd, name=f.stk_nm,
                    # buy_sell_tp "1"=매수(buy) — see note above.
                    side="buy" if f.buy_sell_tp == "1" else "sell",
                    quantity=f.ccld_qty, price=f.ccld_uv, time=f.ccld_tm,
                )
                for f in fills
            ]
        except Exception as e:  # noqa: BLE001
            errors["today_fills"] = str(e)

    res["pending_buy"] = OperationsPendingBuy(queue=queue_items, open_orders=open_orders)
    return OperationsResponse(**res)


# ─── Performance visualization (TUX4 — "수익률 담보" 딜리버러블) ───
#
# services/trading/paper_performance.py의 순수 집계 함수를 브로커 호출 결과에
# 적용한다. 실현손익(ka10074) 섹션과 자산(kt00004) 섹션은 서로 다른 API
# 호출이라 독립적으로 실패할 수 있다 — 하나가 죽어도 다른 하나는 정상 반환
# (/operations와 동일한 섹션별 정직 강등: null + errors, 0/가짜 값 위장 금지).


class PerformanceDailyPoint(BaseModel):
    dt: str = Field(..., description="일자 (YYYYMMDD)")
    pnl: int = Field(..., description="당일 매도손익 (부호 보존)")
    cumulative_pnl: int = Field(..., description="기간 내 누적 손익 (부호 보존)")


class PerformancePnlSummary(BaseModel):
    strt_dt: str
    end_dt: str
    realized_pnl_total: int
    commission: int
    tax: int
    net_pnl: int
    trade_days: int
    win_days: int
    loss_days: int
    flat_days: int
    win_rate_pct: Optional[float] = Field(
        None, description="일 단위 승률 % = 승/(승+패); 승부 없으면 None"
    )
    daily: List[PerformanceDailyPoint] = Field(default_factory=list)


class PerformanceAssetSummary(BaseModel):
    current_asset: int = Field(..., description="현재 계좌 평가액 (주식+예수금)")
    base_asset: Optional[int] = Field(None, description="누적 수익률 분모 (기준 자산)")
    cumulative_return_pct: Optional[float] = Field(
        None, description="누적 수익률 % (기준 자산 대비); 기준 없으면 None"
    )


class PerformanceResponse(BaseModel):
    pnl: Optional[PerformancePnlSummary] = None
    asset: Optional[PerformanceAssetSummary] = None
    errors: Dict[str, str] = {}


@router.get("/performance", response_model=PerformanceResponse)
async def get_performance(
    base: Optional[int] = DEFAULT_BASE_ASSET_KRW,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """모의투자 성과 스냅샷 — 실현손익·승률·일별 시리즈 + 누적 수익률.

    `pnl`(ka10074 기간 실현손익)과 `asset`(kt00004 현재 평가액) 섹션은
    독립적으로 조회·강등된다: 하나가 실패해도 다른 하나는 정상 값을 반환하고
    실패한 섹션만 null + errors 사유가 채워진다 (위장 금지).

    Args:
        base: 누적 수익률 분모 (기본: Paper-Proof C1 운용 개시 기준 자산).
              0 이하 또는 미지정이면 cumulative_return_pct는 None.
        start/end: 조회 기간 YYYYMMDD (기본: 최근 30일).
    """
    errors: Dict[str, str] = {}
    end_dt = end or datetime.now(KST).strftime("%Y%m%d")
    strt_dt = start or (datetime.now(KST) - timedelta(days=30)).strftime("%Y%m%d")

    try:
        client = await get_shared_kiwoom_client_async()
    except Exception as e:  # noqa: BLE001 — 클라이언트 자체를 못 얻으면 양쪽 다 실패
        client = None
        errors["pnl"] = str(e)
        errors["asset"] = str(e)

    pnl_summary: Optional[PerformancePnlSummary] = None
    if client is not None:
        try:
            pnl = await client.get_realized_pnl(strt_dt=strt_dt, end_dt=end_dt)
            win_days, loss_days, flat_days, win_rate_pct = compute_daily_win_loss(pnl.daily)
            pnl_summary = PerformancePnlSummary(
                strt_dt=pnl.strt_dt,
                end_dt=pnl.end_dt,
                realized_pnl_total=pnl.realized_pnl,
                commission=pnl.commission,
                tax=pnl.tax,
                # P2-4 P3b (2026-07-14, follow-up to P3/2b5c897): ka10074
                # rlzt_pl은 이미 수수료·세금이 차감된 NET 값이다 — 공식
                # Kiwoom REST API 문서(Kiwoom-REST-API/kiwoom_docs/계좌.md
                # ka10073 예제, 216-272행)의 실제 응답으로 검산됨:
                #   gross = (cntr_pric-buy_uv)*cntr_qty = 60597.04
                #   gross - (trde_cmsn+trde_tax) = 60597.04-784 = 59813.04
                #   == tdy_sel_pl (정확히 일치)
                # 즉 commission/tax는 참고용 비용 내역일 뿐, realized_pnl에서
                # 다시 빼면 이중차감(과소평가)이 된다. `pnl.realized_pnl -
                # pnl.commission - pnl.tax`로 되돌리지 말 것 — see
                # services/trading/paper_performance.py::build_performance_report
                # (P3, 2b5c897) and test_paper_performance.py::TestNetGrossSemantics.
                net_pnl=pnl.realized_pnl,
                trade_days=len(pnl.daily),
                win_days=win_days,
                loss_days=loss_days,
                flat_days=flat_days,
                win_rate_pct=win_rate_pct,
                daily=[PerformanceDailyPoint(**p) for p in daily_pnl_series(pnl.daily)],
            )
        except Exception as e:  # noqa: BLE001 — 섹션 독립 강등
            errors["pnl"] = str(e)

    asset_summary: Optional[PerformanceAssetSummary] = None
    if client is not None:
        try:
            balance = await client.get_account_balance()
            current_asset = balance.total_value
            asset_summary = PerformanceAssetSummary(
                current_asset=current_asset,
                base_asset=base,
                cumulative_return_pct=compute_cumulative_return_pct(current_asset, base),
            )
        except Exception as e:  # noqa: BLE001 — 섹션 독립 강등
            errors["asset"] = str(e)

    return PerformanceResponse(pnl=pnl_summary, asset=asset_summary, errors=errors)
