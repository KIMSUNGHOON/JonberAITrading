"""
Trading API Routes

Provides endpoints for auto-trading system control and monitoring.
"""

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
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
    KIND_ANALYSIS,
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
    period_bounds,
    equity_return_for_period,
    realized_for_period,
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
# E3-4: EOD 리포트 API -- digest 재조립기 + LLM 내러티브(narrate_eod_digest는
# 이 모듈의 유일한 LLM 호출, 실패는 항상 None로 흡수됨 -- eod_digest.py 참고).
from services.trading.eod_digest import build_eod_digest, narrate_eod_digest
# FI-2: 발굴(discovery) 원장 조회 -- get_discovery_performance는 순수 집계
# (LLM/네트워크 없음), _top_strategy_tag는 eod_digest.py:66도 동일하게
# 모듈 경계를 넘어 재사용하는 기존 전례를 따른 것(밑줄 접두는 "패키지 내부
# 공용" 관례이지 진짜 private가 아님).
from services.discovery.ledger import get_discovery_performance, _top_strategy_tag
# 수동 발굴 트리거(POST /discovery/run) — 마감 엣지의 discovery 블록과 완전히
# 동일한 두 호출(_run_discovery_scan → run_discovery_pipeline)을 라이브
# coordinator/scanner 싱글턴에 대해 실행한다. get_settings로 DISCOVERY_ENABLED
# 킬스위치를, get_background_scanner로 코디네이터가 트리거하는 바로 그 스캐너
# 인스턴스를 재사용한다(coordinator.py:55-57과 동일 import 경로).
from app.config import get_settings
from services.background_scanner.scanner import get_background_scanner
from services.discovery.orchestrator import run_discovery_pipeline

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
    max_trade_notional_pct: Optional[float] = Field(None, ge=0.5, le=50.0)
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

    if request.max_trade_notional_pct is not None:
        params.max_trade_notional_pct = request.max_trade_notional_pct

    if request.stop_loss_mode is not None:
        params.stop_loss_mode = StopLossMode(request.stop_loss_mode)

    if request.take_profit_mode is not None:
        params.take_profit_mode = StopLossMode(request.take_profit_mode)

    try:
        # 재시작 안전(2026-07-29 리뷰): 이 프로세스에서 한 번도 start()를
        # 거치지 않은(_persistence_active=False) 코디네이터에 무조건
        # `_persist_state()`(전체 스냅샷)를 부르면, 메모리 상 빈
        # positions/trade_queue/watch_list가 블롭의 실제 데이터를 덮어써
        # 지워 버린다 — coordinator.py의 stop/pause/resume이 이미 봉합한
        # 것과 동일한 REGRESSION이 이 라우트에도 있었다. mode-only
        # persist가 일반화된 `_persist_fields()`로 risk_params 필드만
        # 부분 갱신한다. 키/직렬화 모양은 `_persist_state`와 반드시 같아야
        # 나중의 전체 persist와 어긋나지 않는다.
        if coordinator._persistence_active:
            await coordinator._persist_state()
        else:
            await coordinator._persist_fields(
                risk_params=coordinator.risk_params.model_dump()
            )
    except Exception:
        logger.warning("Failed to persist risk_params after update", exc_info=True)

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
# EOD Report (E3-4)
# -------------------------------------------

# eod_review.trade_date is the PK and storage.get_eod_reviews has no
# server-side date filter (mirrors eod_digest.py/eod_review.py's own
# scan-then-match idiom, see e.g. eod_digest.py's
# _DAILY_PERF_SNAPSHOT_SCAN_LIMIT) -- this bounds how many recent rows we
# scan in Python to find an exact trade_date match. ~2 years of trading
# days, comfortably more than any date a human would ever request here.
_EOD_REVIEW_SCAN_LIMIT = 500


async def _find_eod_review_row(storage: Any, trade_date: str) -> Optional[Dict[str, Any]]:
    rows = await storage.get_eod_reviews(limit=_EOD_REVIEW_SCAN_LIMIT)
    for row in rows:
        if row.get("trade_date") == trade_date:
            return row
    return None


def _parse_report_json(report_json: Optional[str]) -> Dict[str, Any]:
    try:
        return json.loads(report_json) if report_json else {}
    except (TypeError, ValueError):
        return {}


async def _latest_row_date(getter: Any, label: str) -> Optional[str]:
    """`getter(limit=1)`의 최신 행에서 trade_date(없으면 created_at 앞 10자)를
    뽑아낸다 — get_strategy_revisions/get_regime_snapshots 모두 이미
    created_at DESC 정렬이라 limit=1이면 충분(eod_digest.py의 "테이블 진짜
    최신" 관용구와 동일). 행이 없거나 읽기 자체가 실패하면 None(판단 불가로
    강등, never-raise)."""
    try:
        rows = await getter(limit=1)
    except Exception as e:  # noqa: BLE001 — 판단 불가로 강등
        logger.warning(f"[EODReportAPI] {label} staleness check failed: {e}")
        return None
    if not rows:
        return None

    row_date = rows[0].get("trade_date")
    if not row_date:
        created_at = rows[0].get("created_at")
        row_date = str(created_at)[:10] if created_at else None
    return row_date


async def _compute_staleness_note(storage: Any, requested_date: str) -> Optional[str]:
    """digest.strategy/regime은 둘 다 build_eod_digest 자체가 문서화하듯
    trade_date로 스코프되지 않은 '테이블 진짜 최신' 행이다(E3-1 설계) — 오늘이
    아닌 date로 POST /run을 돌리면 digest에 실린 strategy/regime 섹션이 요청
    date 이후에 결정된 리비전/스냅샷일 수 있다(E3-1 리뷰 Important #2, 그리고
    이 함수 자체의 리뷰픽스: 최초 구현이 strategy만 검사하고 regime을
    누락했었다 — 전략 합의는 정상적으로 돌았지만 레짐 파이프라인만 며칠
    정체된 시나리오에서 오판(None)했을 것).

    strategy_revisions와 regime_snapshot 각각의 최신 행 날짜를 독립적으로
    requested_date와 비교한다 — 한쪽만 stale이어도 다른 한쪽까지 stale로
    싸잡아 말하지 않도록, 노트 문자열은 stale한 쪽만 개별 언급한다. 둘 다
    정합(또는 판단 불가)이면 None."""
    strategy_date = await _latest_row_date(storage.get_strategy_revisions, "strategy_revisions")
    regime_date = await _latest_row_date(storage.get_regime_snapshots, "regime_snapshots")

    stale_parts = []
    if strategy_date and strategy_date != requested_date:
        stale_parts.append(f"strategy는 {strategy_date}")
    if regime_date and regime_date != requested_date:
        stale_parts.append(f"regime은 {regime_date}")

    if not stale_parts:
        return None

    return (
        f"digest의 {', '.join(stale_parts)} 기준 최신 리비전/스냅샷이며, "
        f"요청한 {requested_date}와 다를 수 있습니다."
    )


@router.get("/eod-report")
async def get_eod_report(date: Optional[str] = None):
    """E3-4: EOD 리포트 조회. date(YYYY-MM-DD) 생략 시 테이블 최신 행.
    report_json 전체(digest·narrative·staleness_note 포함, 저장 시점 값
    그대로)를 파싱해 trade_date·created_at와 함께 반환한다. 해당 날짜(또는
    빈 테이블)에 행이 없으면 404."""
    storage = await get_storage_service()

    if date:
        row = await _find_eod_review_row(storage, date)
    else:
        rows = await storage.get_eod_reviews(limit=1)
        row = rows[0] if rows else None

    if row is None:
        raise HTTPException(
            404,
            f"eod_review not found for date={date}" if date else "eod_review not found",
        )

    report = _parse_report_json(row.get("report_json"))
    report["trade_date"] = row.get("trade_date")
    report["created_at"] = row.get("created_at")
    return report


class EodReportRunRequest(BaseModel):
    date: Optional[str] = None  # 생략 시 오늘(KST)


@router.post("/eod-report/run")
async def run_eod_report_now(
    request: EodReportRunRequest,
    coordinator=Depends(get_trading_coordinator),
):
    """E3-4: 수동 EOD 리포트 재생성 + 재통지 — 마감 엣지를 놓친 날(재시작/
    장애로 coordinator._check_queue_on_market_open의 EOD 체인이 못 돈 날)
    대비 수동 트리거. /strategy/consensus/run과 동일한 형태(요청 바디로
    date 지정, force성 재실행).

    digest를 build_eod_digest로 재조립하고(순수 집계, LLM 아님) narrate_
    eod_digest로 내러티브를 재생성한다(이 라우트가 거치는 유일한 LLM 호출 —
    실패/타임아웃은 narrate_eod_digest 자체가 절대 raise하지 않고 None을
    반환하므로 이 라우트도 항상 200을 반환한다). 기존 eod_review 행이 있으면
    그 report_json의 digest/narrative 키만 갱신하고 나머지 섹션(portfolio/
    per_stock/agents/regime — build_eod_review가 채우는 것들)은 보존한다;
    없으면 digest/narrative만으로 최소 report를 저장한다(INSERT OR REPLACE로
    trade_date PK 재사용, eod_review.py 관용구와 동일).

    저장 후 coordinator._notify_eod_summary(date)를 재호출해 Telegram/WS를
    재발송한다 — 그 함수 자신의 stale 가드(get_eod_reviews(limit=1)로 읽은
    최신 행의 trade_date가 요청 date와 다르면 스킵)가 date 정합을 보장하므로,
    과거 date를 재실행해도 더 최신 날짜의 요약이 잘못 재발송되는 일은 없다.
    응답의 `notified`는 그 호출의 반환값을 그대로 실어 보낸다(E3-4 리뷰픽스
    — _notify_eod_summary가 bool을 반환하도록 확장됨: 가드에 걸려 스킵되거나
    예외가 나면 False, 실제로 WS/Telegram 발송까지 도달하면 True — 기존
    마감 체인 호출부는 이 반환값을 그대로 무시하므로 그쪽은 무영향).

    staleness_note는 응답·저장 양쪽 모두 `digest.staleness_note` 한 자리에만
    싣는다(GET 응답과 노출 깊이 통일 — 이전 리뷰픽스 전에는 이 라우트가
    top-level에도 사이드카로 중복 노출했었다).
    """
    trade_date = request.date or datetime.now(KST).strftime("%Y-%m-%d")
    storage = await get_storage_service()

    digest = await build_eod_digest(coordinator=coordinator, storage=storage, trade_date=trade_date)
    digest["staleness_note"] = await _compute_staleness_note(storage, trade_date)
    narrative = await narrate_eod_digest(digest)

    existing_row = await _find_eod_review_row(storage, trade_date)
    report = _parse_report_json(existing_row.get("report_json")) if existing_row else {}
    report["trade_date"] = trade_date
    report["digest"] = digest
    report["narrative"] = narrative

    await storage.save_eod_review(
        {"trade_date": trade_date, "report_json": json.dumps(report)}
    )

    notified = await coordinator._notify_eod_summary(trade_date)

    return {
        "ok": True,
        "trade_date": trade_date,
        "digest": digest,
        "narrative": narrative,
        "notified": notified,
    }


# fire-and-forget 백그라운드 태스크 강참조 보관소 — asyncio는 태스크를 약참조로만
# 붙들어 create_task 반환값을 아무도 안 잡으면 스캔(수 시간) 도중 GC로 취소될 수
# 있다. 완료 시 스스로 비우는 집합에 담아 살아있게 한다(add_done_callback).
_discovery_run_tasks: set = set()


@router.post("/discovery/run")
async def run_discovery_now(coordinator=Depends(get_trading_coordinator)):
    """수동 발굴(discovery) 파이프라인 트리거 — 마감 엣지(coordinator._check_
    queue_on_market_open의 open→closed 엣지, 장 마감 시 1회)를 재시작/장애로
    놓쳤거나, 개장 전에 미리 후보를 준비하고 싶을 때 쓰는 수동 트리거.
    /eod-report/run·/strategy/consensus/run과 동일한 "놓친 엣지 복구" 관용구.

    마감 엣지 블록의 discovery 두 스텝을 그대로 떼어내 실행한다
    (coordinator.py:2918-2947과 동일):
      1) coordinator._run_discovery_scan() — 전 종목 discovery 스캔 트리거 +
         완료까지 폴링(notify_progress=False, 스캐너 busy면 skip, SC-2 동적
         타임아웃). scan_ok(bool) 반환.
      2) run_discovery_pipeline(...) — backfill→rank→LLM검토→promote→원장.
         승격은 Depends로 주입된 **라이브 coordinator 싱글턴**의 워치리스트에
         반영되므로 다음 개장 시 target_entry_price ±3% 근접분이 fire된다.
         (별도 프로세스 스크립트로는 이 라이브 워치리스트에 닿을 수 없어 무의미
         — 반드시 이 in-process 경로여야 한다.)

    스캔은 전 종목(수천)·수십 분~수 시간이 걸리므로 이 라우트는 작업을
    asyncio.create_task로 백그라운드에 던지고 즉시 반환한다(POST /scanner/start
    와 동일한 fire-and-forget). 진행은 GET /scanner/progress, 결과는 GET
    /trading/discovery/candidates·GET /trading/watch-list로 관찰한다.

    trade_date는 요청 시점의 서버 로컬 날짜(datetime.now(), naive)로 한 번만
    계산해 백그라운드 태스크에 넘긴다 — 마감 체인(coordinator.py:2943)과 동일한
    계산이며, 스캔 세션의 started_at 날짜와 일치해야 하는 불변식이다
    (ranker._load_discovery_session이 date(started_at)=trade_date로 매칭 —
    KST-aware를 쓰면 자정 근처 UTC 오프셋에서 어긋나 조용히 0건이 될 수 있어
    naive 로컬을 그대로 쓴다). 스캔은 늘 오늘 새로 돌므로 날짜 override는 두지
    않는다(과거 날짜=세션 불일치로 조용히 0건이 되는 footgun 차단).

    DISCOVERY_ENABLED가 off면 enabled=False로, 트레이딩 미기동(coordinator
    start() 전)이면 started=False로 스캔조차 시작하지 않고 즉시 거부한다
    (아래 가드 주석 참고).
    """
    if not get_settings().DISCOVERY_ENABLED:
        return {
            "ok": False,
            "enabled": False,
            "started": False,
            "message": "DISCOVERY_ENABLED is off — 발굴 트리거 거부",
        }

    # Important(리뷰 봉합): coordinator가 아직 start()되지 않았으면
    # add_to_watch_list의 _schedule_persist가 no-op이라 승격이 워치리스트에
    # 영속되지 않는다. 이후 /trading/start의 _restore_state가 스테일 blob으로
    # 워치리스트를 덮어써 방금 승격한 후보가 조용히 증발한다(원장/FE는 승격됐다고
    # 표시하는 위험한 불일치). 기동 전이면 수 시간짜리 스캔조차 시작하지 않고 거부.
    if not getattr(coordinator, "_persistence_active", False):
        return {
            "ok": False,
            "enabled": True,
            "started": False,
            "message": "트레이딩 미기동 — 먼저 POST /trading/start 후 다시 호출(승격 영속 보장)",
        }

    trade_date = datetime.now().strftime("%Y-%m-%d")

    async def _run_discovery_job():
        # 두 호출 모두 내부적으로 never-raise이지만, 마감 체인의 방어 심화
        # (coordinator.py:2920/2938 try/except)를 동일하게 한 번 더 감싼다.
        try:
            scan_ok = await coordinator._run_discovery_scan()
            # TOCTOU 방어(리뷰 Minor): 스캔이 수 시간이라 그 사이 /trading/stop이
            # _persistence_active를 다시 False로 되돌릴 수 있다. 그 상태에서 승격하면
            # add_to_watch_list가 영속되지 않고 다음 /trading/start의 _restore_state가
            # 덮어써 승격이 조용히 증발한다(요청 시점 가드로는 못 막는 잔여 창).
            # 승격 직전 재확인해 미기동이면 파이프라인을 건너뛴다.
            if not getattr(coordinator, "_persistence_active", False):
                logger.warning(
                    "[Discovery] manual run aborted before pipeline — trading "
                    "stopped mid-scan (_persistence_active False); skipping promotion "
                    "to avoid unpersisted-then-clobbered watch entries. trade_date=%s",
                    trade_date,
                )
                return
            summary = await run_discovery_pipeline(
                coordinator=coordinator,
                storage=await get_storage_service(),
                scanner=await get_background_scanner(),
                trade_date=trade_date,
                scan_ok=scan_ok,
            )
            logger.info(
                "[Discovery] manual run finished trade_date=%s scan_ok=%s summary=%s",
                trade_date,
                scan_ok,
                summary,
            )
        except Exception as e:
            logger.warning(
                "[Discovery] manual run failed trade_date=%s: %s", trade_date, e
            )

    task = asyncio.create_task(_run_discovery_job())
    _discovery_run_tasks.add(task)
    task.add_done_callback(_discovery_run_tasks.discard)

    return {
        "ok": True,
        "enabled": True,
        "started": True,
        "trade_date": trade_date,
        "message": (
            "발굴 스캔 시작 — GET /scanner/progress 로 진행 확인, "
            "GET /trading/discovery/candidates·/watch-list 로 결과 확인"
        ),
    }


# -------------------------------------------
# FI-2: Discovery Ledger Query Endpoints
#
# storage.get_discovery_candidates (services/storage_service.py:2650) has no
# `promoted` filter and no `offset` param -- adding either would touch a
# storage-layer signature several other callers depend on (eod_digest.py,
# services/discovery/ledger.py). Per the FI-2 brief this stays minimally
# invasive: both filters are applied here, in the route, after a single
# storage query. `promoted` filtering happens on an over-fetched batch
# (see _DISCOVERY_CANDIDATES_OVERFETCH_CAP below) since we can't know in
# advance how many of the newest-N rows match the filter; `offset` is a
# plain list slice. For this single-user paper-trading app's data volume
# this is correct in practice, with a documented edge: a `promoted` filter
# combined with more than _DISCOVERY_CANDIDATES_OVERFETCH_CAP total rows
# for the requested trade_date could under-return older matches -- FI-4's
# ledger page is expected to scope by trade_date, keeping per-day volume
# far under the cap.
# -------------------------------------------

_DISCOVERY_CANDIDATES_OVERFETCH_CAP = 5000


class DiscoveryCandidateResponse(BaseModel):
    id: Optional[str] = None
    trade_date: Optional[str] = None
    ticker: Optional[str] = None
    name: Optional[str] = None
    composite_score: Optional[float] = None
    top_strategy_tag: Optional[str] = Field(
        None, description="strategy_scores_json에서 계산한 최고 기여 전략 태그"
    )
    regime_label: Optional[str] = None
    rank: Optional[int] = None
    promoted: bool = False
    skip_reason: Optional[str] = None
    close_price: Optional[float] = None
    fwd_1d: Optional[float] = None
    fwd_5d: Optional[float] = None
    fwd_20d: Optional[float] = None


class DiscoveryCandidatesResponse(BaseModel):
    candidates: List[DiscoveryCandidateResponse] = Field(default_factory=list)
    count: int = Field(0, description="이 페이지에 실제로 담긴 후보 수 (전체 매치 수 아님)")


def _to_discovery_candidate_response(row: Dict[str, Any]) -> DiscoveryCandidateResponse:
    return DiscoveryCandidateResponse(
        id=row.get("id"),
        trade_date=row.get("trade_date"),
        ticker=row.get("ticker"),
        name=row.get("name"),
        composite_score=row.get("composite_score"),
        top_strategy_tag=_top_strategy_tag(row.get("strategy_scores_json")),
        regime_label=row.get("regime_label"),
        rank=row.get("rank"),
        promoted=bool(row.get("promoted")),
        skip_reason=row.get("skip_reason"),
        close_price=row.get("close_price"),
        fwd_1d=row.get("fwd_1d"),
        fwd_5d=row.get("fwd_5d"),
        fwd_20d=row.get("fwd_20d"),
    )


@router.get("/discovery/candidates", response_model=DiscoveryCandidatesResponse)
async def get_discovery_candidates_route(
    trade_date: Optional[str] = None,
    promoted: Optional[bool] = None,
    limit: int = 200,
    offset: int = 0,
):
    """FI-2: discovery_candidates 원장 조회 (발굴 스캔이 남긴 후보 + 승격
    여부 + 사후 채워지는 fwd_1d/5d/20d).

    trade_date로 특정일로 좁힐 수 있고, promoted로 승격/스킵만 골라볼 수
    있다(둘 다 optional -- 생략하면 전체 최신순). limit/offset은 이 라우트
    레벨에서 적용된다(위 섹션 docstring 참고). 후보가 하나도 없어도(빈
    테이블이거나 필터에 아무것도 안 걸려도) 200 + 빈 리스트를 반환한다 --
    404가 아니다(원장 조회는 "아직 없음"이 정상 상태).
    """
    storage = await get_storage_service()

    fetch_limit = (
        _DISCOVERY_CANDIDATES_OVERFETCH_CAP if promoted is not None else (offset + limit)
    )
    rows = await storage.get_discovery_candidates(trade_date=trade_date, limit=fetch_limit)

    if promoted is not None:
        rows = [r for r in rows if bool(r.get("promoted")) == promoted]

    page = rows[offset : offset + limit]
    candidates = [_to_discovery_candidate_response(r) for r in page]
    return DiscoveryCandidatesResponse(candidates=candidates, count=len(candidates))


class DiscoveryPerformanceBucket(BaseModel):
    candidates: int = 0
    promoted: int = 0
    avg_fwd_1d: Optional[float] = None
    avg_fwd_5d: Optional[float] = None
    hit_rate_5d: Optional[float] = None


class DiscoveryPerformanceResponse(BaseModel):
    days: int
    by_strategy_tag: Dict[str, DiscoveryPerformanceBucket] = Field(default_factory=dict)


@router.get("/discovery/performance", response_model=DiscoveryPerformanceResponse)
async def get_discovery_performance_route(days: int = 14):
    """FI-2: 발굴 전략태그별 성과 요약 (services/discovery/ledger.py::
    get_discovery_performance 그대로 위임 -- 순수 집계, 빈 원장/윈도우 밖은
    빈 dict, 절대 raise 하지 않음). 전략별 후보 수·승격 수·평균 fwd_1d/5d·
    hit_rate_5d."""
    storage = await get_storage_service()
    summary = await get_discovery_performance(storage, days=days)
    return DiscoveryPerformanceResponse(days=days, by_strategy_tag=summary)


class UsSignalComponent(BaseModel):
    ticker: str
    weight: float
    change_pct: Optional[float] = None


class UsSignalCurationItem(BaseModel):
    ticker: str
    name: str
    signal_type: Optional[str] = None


class UsSignalResponse(BaseModel):
    enabled: bool
    as_of: Optional[str] = None
    signal_pct: Optional[float] = None
    signal: Optional[float] = None
    components: List[UsSignalComponent] = Field(default_factory=list)
    computed_at: Optional[str] = None
    curation: List[UsSignalCurationItem] = Field(default_factory=list)
    sub_signals: Optional[dict] = None


@router.get("/discovery/us-signal", response_model=UsSignalResponse)
async def get_us_signal_route():
    """현재 US AI 크로스마켓 신호 + 적용 큐레이션(읽기전용). off/stale이면 신호필드 null·큐레이션은 항상."""
    from app.config import get_settings
    from services.trading.us_market_data import get_cached_us_ai_signal, US_AI_TICKERS
    from services.discovery.ai_valuechain import AI_VALUECHAIN_TICKERS

    enabled = bool(get_settings().US_SIGNAL_ENABLED)
    cached = await get_cached_us_ai_signal()  # off/stale/실패 → None (never-raise)
    comps_pct = (cached or {}).get("components") or {}
    components = [
        UsSignalComponent(ticker=t, weight=w, change_pct=comps_pct.get(t))
        for t, w in US_AI_TICKERS.items()
    ]
    curation = [
        UsSignalCurationItem(ticker=t, name=v["name"], signal_type=v.get("signal_type"))
        for t, v in AI_VALUECHAIN_TICKERS.items()
    ]
    return UsSignalResponse(
        enabled=enabled,
        as_of=(cached or {}).get("as_of"),
        signal_pct=(cached or {}).get("signal_pct"),
        signal=(cached or {}).get("signal"),
        components=components,
        computed_at=(cached or {}).get("computed_at"),
        curation=curation,
        sub_signals=(cached or {}).get("sub_signals"),
    )


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
    # while its state["awaiting_approval"] was already cleared -- surface that
    # mismatch so the board can't offer a doomed approve/reject on an
    # unapprovable session.
    #
    # P3-3 (session-SSOT) audit: originally written (ed56505) when the sm's
    # AnalysisSession.state was a separate copy of a legacy in-memory dict
    # that could silently fail to mirror a cancel -- that legacy dict is gone
    # (P3-1), so cross-store divergence can no longer happen. The guard still
    # earns its keep: approval.py's _submit_decision_locked splits one
    # decision into two independent write-through SessionManager calls with
    # the full graph resume running between them -- an early
    # commit_session_state(...) (~L335) that lands state["awaiting_approval"]
    # =False as part of decision_updates, and a later, separate
    # commit_session_status(...) that lands the terminal/rearm status
    # (~L564 for approved/modified/cancelled; ~L508 for reject's rearm back
    # to AWAITING_APPROVAL). approval.py's own comment at ~L558-562 spells
    # out the resulting risk: if that later status commit fails, the sm row
    # is left showing a stale AWAITING_APPROVAL status for a session whose
    # state has already moved on -- exactly status==AWAITING_APPROVAL +
    # state["awaiting_approval"]==False. This split-commit failure mode is
    # exercised by
    # tests/test_api/test_awaiting_writethrough.py::test_approval_rejected_rearm_failed_commit_never_schedules
    # (commit_session_state succeeds, commit_session_status fails). Same
    # store, not cross-store -- but a single source (status alone) would
    # still miss it. Keep computing this from state.
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
        # P4-1: kind='analysis' only -- a discussion (or other non-analysis
        # producer) session sharing the SM store must never surface as a
        # ghost "analyzing"/"awaiting" card on the operations board.
        sessions = await sm.get_all_sessions(market_type=mt, kind=KIND_ANALYSIS)
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


# ─── 기간 손익 요약 (NAV 손익 표시) ───
#
# `realized`(브로커 ka10074)와 `equity_return`(로컬 daily_perf_snapshot)은
# 서로 다른 소스라 독립적으로 강등된다. 미실현손익은 여기 없다 — PositionsPanel이
# 이미 폴링 중인 /operations 데이터에서 프론트가 합산한다(브로커 중복 호출 회피).


def _pnl_summary_today() -> date:
    """오늘(KST). 테스트가 시간을 고정할 수 있도록 분리해 둔다."""
    return datetime.now(KST).date()


class PnlSummaryEquityReturn(BaseModel):
    pct: float = Field(..., description="기간 수익률 %")
    basis: str = Field(
        ..., description='분모 출처: "prior_close"(기간 시작 직전 종가) 또는 "base_asset"(기준자산)'
    )
    trade_date: str = Field(
        ...,
        description=(
            "이 수익률의 분자(end_equity)를 만든 스냅샷의 거래일(YYYY-MM-DD). "
            "장중에는 오늘자 스냅샷이 아직 없어 직전 영업일 종가 기준이므로 "
            "화면에 함께 표시해 프론트가 신선도를 알 수 있게 한다."
        ),
    )


class PnlSummaryResponse(BaseModel):
    realized: Optional[Dict[str, int]] = Field(
        None, description="버킷별 실현손익 (day/week/month/total), 이미 세후"
    )
    equity_return: Optional[Dict[str, PnlSummaryEquityReturn]] = Field(
        None, description="버킷별 평가금 기준 수익률"
    )
    as_of: str = Field(..., description="기준일 YYYY-MM-DD (KST)")
    errors: Dict[str, str] = {}


@router.get("/pnl-summary", response_model=PnlSummaryResponse)
async def get_pnl_summary(base: Optional[int] = DEFAULT_BASE_ASSET_KRW):
    """일/주/월/누적 실현손익과 평가금 기준 수익률.

    버킷 경계는 캘린더 기준이다 — 주는 이번 주 월요일부터, 월은 이번 달 1일부터.
    평가금 수익률의 분모는 기간 시작 **직전** 종가이고, 그런 행이 없으면
    `base`(기준자산)로 물러서며 `basis`가 어느 쪽이었는지 드러낸다.

    브로커는 **한 번만** 호출한다 — 버킷마다 부르면 Kiwoom 레이트리밋(초당 약
    1.4요청)에 걸린다. 그래서 스냅샷을 먼저 읽어 누적 버킷의 시작을 정한 뒤
    가장 넓은 창으로 1회 조회하고 그 일별 시리즈를 버킷별로 합산한다.
    """
    errors: Dict[str, str] = {}
    today = _pnl_summary_today()

    snapshots: list = []
    try:
        storage = await get_storage_service()
        snapshots = await storage.get_daily_perf_snapshots(limit=400)
    except Exception as e:  # noqa: BLE001 — 섹션 독립 강등
        errors["equity_return"] = str(e)

    # get_daily_perf_snapshots는 최신순이라 가장 이른 일자는 마지막 행이다.
    # trade_date가 YYYYMMDD 8자리로 정규화되는 값이 아니면(예: 손상된 행이
    # ISO datetime 문자열을 담고 있는 경우) data_start로 채택하지 않는다 —
    # equity_return_for_period가 스냅샷 행을 거를 때 쓰는 것과 같은 가드.
    # 이 가드 없이 문자열을 그대로 넘기면 이후 문자열 비교(`dt < start` 등)가
    # 의미 없는 값과 뒤섞여 total 버킷의 basis/수익률이 조용히 틀어진다.
    data_start: Optional[str] = None
    if snapshots:
        raw = snapshots[-1].get("trade_date")
        if isinstance(raw, str):
            candidate = raw.replace("-", "")
            if len(candidate) == 8 and candidate.isdigit():
                data_start = candidate

    bounds = period_bounds(today, data_start)

    equity_return: Optional[Dict[str, PnlSummaryEquityReturn]] = None
    if "equity_return" not in errors:
        computed = {}
        for bucket, (start, end) in bounds.items():
            point = equity_return_for_period(snapshots, start, end, base)
            if point is not None:
                computed[bucket] = PnlSummaryEquityReturn(**point)
        if computed:
            equity_return = computed
        elif snapshots:
            # 스냅샷은 있지만 어느 버킷도 계산 가능한 구간을 못 찾은
            # 경우 — 드물지만 "행이 없다"와는 다른 사실이므로 구분해 보고한다.
            errors["equity_return"] = "평가금 스냅샷은 있으나 계산 가능한 구간 없음"
        else:
            # storage.get_daily_perf_snapshots는 내부에서 예외를 모두
            # 삼키고 빈 리스트를 반환한다(storage_service.py) — 그래서
            # "아직 기록된 행이 없음"과 "조회 자체가 실패함"을 여기서
            # 구분할 수 없다. 확인하지 않은 원인을 단정하지 않는다.
            errors["equity_return"] = (
                "평가금 스냅샷 없음 (또는 조회 실패 — 원인 구분 불가)"
            )

    realized: Optional[Dict[str, int]] = None
    try:
        client = await get_shared_kiwoom_client_async()
        window_start = min(start for start, _ in bounds.values())
        pnl = await client.get_realized_pnl(
            strt_dt=window_start, end_dt=today.strftime("%Y%m%d")
        )
        points = daily_pnl_series(pnl.daily)
        realized = {
            bucket: realized_for_period(points, start, end)
            for bucket, (start, end) in bounds.items()
        }
        if data_start is None:
            # data_start(가장 이른 평가금 스냅샷)를 모르면 bounds()의
            # `total`은 이번 달 1일로 물러선 값이다 — "누적"이라는 라벨과
            # 달리 실제로는 월간과 같은 창일 수 있다는 사실을 표시해 둔다.
            errors["realized_total_scope"] = (
                "데이터 시작일 불명 — 누적이 이번 달로 제한됨"
            )
    except Exception as e:  # noqa: BLE001 — 섹션 독립 강등
        errors["realized"] = str(e)

    # as_of는 가능하면 "실제로 반영된 데이터가 어느 날짜 것인지"를 보여준다
    # — 장중에는 평가금 수익률이 전부 직전 종가 기준이므로, 오늘 날짜
    # (datetime.now 기반)를 그대로 as_of로 쓰면 마치 오늘자 데이터처럼
    # 보인다. 평가금 버킷이 하나라도 살아 있으면 그중 가장 최신
    # trade_date를 as_of로 쓰고, 없으면(평가금 섹션 자체가 죽었을 때)
    # 오늘 날짜로 물러선다.
    as_of = (
        max(v.trade_date for v in equity_return.values())
        if equity_return
        else today.strftime("%Y-%m-%d")
    )

    return PnlSummaryResponse(
        realized=realized,
        equity_return=equity_return,
        as_of=as_of,
        errors=errors,
    )
