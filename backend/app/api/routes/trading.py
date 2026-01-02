"""
Trading API Routes

Provides endpoints for auto-trading system control and monitoring.
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from services.trading import (
    TradingMode,
    TradingState,
    TradingAlert,
    RiskParameters,
    StopLossMode,
    AllocationPlan,
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trading", tags=["trading"])


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
            coordinator.risk_params = request.risk_params

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
    """Update stop-loss for a position."""
    coordinator.risk_monitor.update_stop_loss(ticker, stop_loss)

    return {
        "status": "updated",
        "ticker": ticker,
        "stop_loss": stop_loss,
    }


@router.put("/positions/{ticker}/take-profit")
async def update_position_take_profit(
    ticker: str,
    take_profit: float,
    coordinator=Depends(get_trading_coordinator),
):
    """Update take-profit for a position."""
    coordinator.risk_monitor.update_take_profit(ticker, take_profit)

    return {
        "status": "updated",
        "ticker": ticker,
        "take_profit": take_profit,
    }


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

        return {
            "status": "created",
            "strategy": strategy.model_dump(),
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

        return {
            "status": "updated",
            "strategy": strategy.model_dump(),
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
        strategy = get_strategy_preset(preset_enum)

        coordinator.set_strategy(strategy)

        logger.info(f"[Strategy API] Applied preset: {preset_name}")

        return {
            "status": "applied",
            "preset": preset_name,
            "strategy": strategy.model_dump(),
        }

    except ValueError:
        raise HTTPException(404, f"Preset '{preset_name}' not found")


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
    - Strategy Engine: Strategy evaluation
    """
    return {
        "agents": coordinator.get_agent_states(),
    }
