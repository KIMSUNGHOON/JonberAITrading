"""
Trading API Routes

Provides endpoints for auto-trading system control and monitoring.
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.services.trading import (
    TradingMode,
    TradingState,
    TradingAlert,
    RiskParameters,
    StopLossMode,
    AllocationPlan,
)
from backend.app.dependencies import get_trading_coordinator

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
