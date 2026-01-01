"""
Agent Group Chat API Routes

Endpoints for multi-agent discussion system.
Agents discuss, debate, and vote on trading opportunities.
"""

from typing import Optional, List
from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException, status, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from services.agent_chat import (
    get_chat_coordinator,
    ChatSession,
    AgentMessage,
    SessionStatus,
    DecisionAction,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/agent-chat", tags=["Agent Group Chat"])


# -------------------------------------------
# Request/Response Models
# -------------------------------------------


class StartDiscussionRequest(BaseModel):
    """Request to start a manual discussion."""
    ticker: str = Field(..., description="Stock ticker code")
    stock_name: str = Field(..., description="Stock name")


class StartDiscussionResponse(BaseModel):
    """Response after starting a discussion."""
    session_id: str
    ticker: str
    stock_name: str
    status: str
    started_at: str
    message: str


class SessionSummaryResponse(BaseModel):
    """Summary of a chat session."""
    id: str
    ticker: str
    stock_name: str
    status: str
    started_at: Optional[str]
    ended_at: Optional[str]
    total_messages: int
    total_rounds: int
    consensus_level: Optional[float]
    decision_action: Optional[str]
    decision_confidence: Optional[float]


class SessionDetailResponse(BaseModel):
    """Detailed session information."""
    id: str
    ticker: str
    stock_name: str
    status: str
    started_at: Optional[str]
    ended_at: Optional[str]
    rounds: List[dict]
    messages: List[dict]
    votes: List[dict]
    consensus_level: float
    decision: Optional[dict]


class ActiveDiscussionResponse(BaseModel):
    """Active discussion summary."""
    ticker: str
    stock_name: str
    session_id: str
    status: str
    started_at: Optional[str]


class CoordinatorStatusResponse(BaseModel):
    """Chat coordinator status."""
    is_running: bool
    active_discussions: int
    total_sessions: int
    check_interval_minutes: int
    max_concurrent_discussions: int


class StartCoordinatorRequest(BaseModel):
    """Request to start the coordinator."""
    check_interval_minutes: int = Field(default=5, ge=1, le=60)
    max_concurrent_discussions: int = Field(default=3, ge=1, le=10)


# -------------------------------------------
# Helper Functions
# -------------------------------------------


def _session_to_summary(session: ChatSession) -> dict:
    """Convert session to summary dict."""
    return {
        "id": session.id,
        "ticker": session.ticker,
        "stock_name": session.stock_name,
        "status": session.status.value,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "total_messages": len(session.all_messages),
        "total_rounds": len(session.rounds),
        "consensus_level": session.consensus_level,
        "decision_action": session.decision.action.value if session.decision else None,
        "decision_confidence": session.decision.confidence if session.decision else None,
    }


def _session_to_detail(session: ChatSession) -> dict:
    """Convert session to detailed dict."""
    return {
        "id": session.id,
        "ticker": session.ticker,
        "stock_name": session.stock_name,
        "status": session.status.value,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "rounds": [
            {
                "round_number": r.round_number,
                "round_type": r.round_type,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "message_count": len(r.messages),
            }
            for r in session.rounds
        ],
        "messages": [
            {
                "id": m.id,
                "timestamp": m.timestamp.isoformat(),
                "agent_type": m.agent_type.value,
                "agent_name": m.agent_name,
                "message_type": m.message_type.value,
                "content": m.content,
                "confidence": m.confidence,
                "data": m.data,
            }
            for m in session.all_messages
        ],
        "votes": [
            {
                "agent_type": v.agent_type.value,
                "vote": v.vote.value,
                "confidence": v.confidence,
                "weight": v.weight,
                "weighted_score": v.weighted_score,
                "reasoning": v.reasoning,
            }
            for v in session.votes
        ],
        "consensus_level": session.consensus_level,
        "decision": {
            "action": session.decision.action.value,
            "confidence": session.decision.confidence,
            "consensus_level": session.decision.consensus_level,
            "entry_price": session.decision.entry_price,
            "stop_loss": session.decision.stop_loss,
            "take_profit": session.decision.take_profit,
            "quantity": session.decision.quantity,
            "key_factors": session.decision.key_factors,
            "dissenting_opinions": session.decision.dissenting_opinions,
            "rationale": session.decision.rationale,
        } if session.decision else None,
    }


def _message_to_dict(message: AgentMessage) -> dict:
    """Convert message to dict for WebSocket."""
    return {
        "id": message.id,
        "timestamp": message.timestamp.isoformat(),
        "agent_type": message.agent_type.value,
        "agent_name": message.agent_name,
        "message_type": message.message_type.value,
        "content": message.content,
        "confidence": message.confidence,
        "data": message.data,
    }


# -------------------------------------------
# Coordinator Control Endpoints
# -------------------------------------------


@router.get("/status", response_model=CoordinatorStatusResponse)
async def get_coordinator_status():
    """
    Get chat coordinator status.

    Returns running state and statistics.
    """
    coordinator = await get_chat_coordinator()

    return CoordinatorStatusResponse(
        is_running=coordinator._running,
        active_discussions=len(coordinator._active_rooms),
        total_sessions=len(coordinator._session_history),
        check_interval_minutes=coordinator.check_interval,
        max_concurrent_discussions=coordinator.max_concurrent,
    )


@router.post("/start")
async def start_coordinator(request: Optional[StartCoordinatorRequest] = None):
    """
    Start the chat coordinator.

    Begins automatic watch list monitoring and discussion triggers.
    """
    try:
        coordinator = await get_chat_coordinator()

        if request:
            coordinator.check_interval = request.check_interval_minutes
            coordinator.max_concurrent = request.max_concurrent_discussions

        await coordinator.start()

        return {
            "status": "started",
            "message": "Agent chat coordinator started",
            "check_interval": coordinator.check_interval,
        }

    except Exception as e:
        logger.exception("Failed to start chat coordinator")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start coordinator: {str(e)}",
        )


@router.post("/stop")
async def stop_coordinator():
    """
    Stop the chat coordinator.

    Stops automatic monitoring and cancels active discussions.
    """
    try:
        coordinator = await get_chat_coordinator()
        await coordinator.stop()

        return {
            "status": "stopped",
            "message": "Agent chat coordinator stopped",
        }

    except Exception as e:
        logger.exception("Failed to stop chat coordinator")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop coordinator: {str(e)}",
        )


# -------------------------------------------
# Manual Discussion Endpoints
# -------------------------------------------


@router.post("/discuss", response_model=StartDiscussionResponse)
async def start_discussion(request: StartDiscussionRequest):
    """
    Start a manual discussion for a stock.

    Triggers agents to analyze and discuss the stock immediately.
    The discussion runs synchronously and returns the completed session.
    """
    try:
        coordinator = await get_chat_coordinator()

        logger.info(
            "manual_discussion_requested",
            ticker=request.ticker,
            stock_name=request.stock_name,
        )

        session = await coordinator.start_manual_discussion(
            ticker=request.ticker,
            stock_name=request.stock_name,
        )

        return StartDiscussionResponse(
            session_id=session.id,
            ticker=session.ticker,
            stock_name=session.stock_name,
            status=session.status.value,
            started_at=session.started_at.isoformat() if session.started_at else "",
            message=f"Discussion completed for {request.stock_name}",
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("Failed to start manual discussion")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start discussion: {str(e)}",
        )


@router.get("/active")
async def get_active_discussions():
    """
    Get list of currently active discussions.

    Returns discussions that are in progress.
    """
    coordinator = await get_chat_coordinator()
    active = coordinator.get_active_discussions()

    return {
        "discussions": active,
        "count": len(active),
    }


# -------------------------------------------
# Session History Endpoints
# -------------------------------------------


@router.get("/sessions")
async def get_sessions(
    limit: int = 20,
    ticker: Optional[str] = None,
):
    """
    Get session history.

    Args:
        limit: Maximum number of sessions to return
        ticker: Filter by ticker (optional)

    Returns:
        List of session summaries
    """
    coordinator = await get_chat_coordinator()
    sessions = coordinator.get_session_history(limit=limit, ticker=ticker)

    return {
        "sessions": [_session_to_summary(s) for s in sessions],
        "count": len(sessions),
    }


@router.get("/sessions/{session_id}")
async def get_session_detail(session_id: str):
    """
    Get detailed information about a specific session.

    Includes all messages, votes, and decision details.
    """
    coordinator = await get_chat_coordinator()
    session = coordinator.get_session_by_id(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )

    return _session_to_detail(session)


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """
    Get all messages from a specific session.

    Returns messages in chronological order.
    """
    coordinator = await get_chat_coordinator()
    session = coordinator.get_session_by_id(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )

    return {
        "messages": [_message_to_dict(m) for m in session.all_messages],
        "count": len(session.all_messages),
    }


@router.get("/sessions/{session_id}/decision")
async def get_session_decision(session_id: str):
    """
    Get the final decision from a session.

    Returns decision details including rationale and key factors.
    """
    coordinator = await get_chat_coordinator()
    session = coordinator.get_session_by_id(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )

    if not session.decision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session has no decision yet",
        )

    decision = session.decision
    return {
        "session_id": session_id,
        "ticker": session.ticker,
        "stock_name": session.stock_name,
        "action": decision.action.value,
        "confidence": decision.confidence,
        "consensus_level": decision.consensus_level,
        "entry_price": decision.entry_price,
        "stop_loss": decision.stop_loss,
        "take_profit": decision.take_profit,
        "quantity": decision.quantity,
        "key_factors": decision.key_factors,
        "dissenting_opinions": decision.dissenting_opinions,
        "rationale": decision.rationale,
    }


# -------------------------------------------
# WebSocket for Real-time Updates
# -------------------------------------------


class ConnectionManager:
    """Manages WebSocket connections for chat updates."""

    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """Connect a client to a session's updates."""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str):
        """Disconnect a client from session updates."""
        if session_id in self.active_connections:
            if websocket in self.active_connections[session_id]:
                self.active_connections[session_id].remove(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

    async def send_message(self, session_id: str, message: dict):
        """Send a message to all clients watching a session."""
        if session_id in self.active_connections:
            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

    async def broadcast_status(self, session_id: str, status: str, session: dict):
        """Broadcast status change to all clients."""
        await self.send_message(session_id, {
            "type": "status_change",
            "session_id": session_id,
            "status": status,
            "session": session,
        })


manager = ConnectionManager()


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time session updates.

    Connect to receive:
    - New messages as they're generated
    - Status changes (analyzing, discussing, voting, decided)
    - Final decision announcement
    """
    await manager.connect(websocket, session_id)

    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()

            # Handle ping/pong
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)


# -------------------------------------------
# Utility Endpoints
# -------------------------------------------


@router.get("/agents")
async def get_agent_info():
    """
    Get information about available discussion agents.

    Returns agent types and their roles.
    """
    from services.agent_chat import AgentType

    agents = [
        {
            "type": AgentType.TECHNICAL.value,
            "name": "기술적 분석가",
            "description": "차트 패턴, 기술적 지표 분석",
            "weight": 0.25,
        },
        {
            "type": AgentType.FUNDAMENTAL.value,
            "name": "펀더멘털 분석가",
            "description": "재무제표, 밸류에이션 분석",
            "weight": 0.25,
        },
        {
            "type": AgentType.SENTIMENT.value,
            "name": "시장 심리 분석가",
            "description": "뉴스, 시장 심리 분석",
            "weight": 0.20,
        },
        {
            "type": AgentType.RISK.value,
            "name": "리스크 관리자",
            "description": "리스크 평가, 포지션 사이징",
            "weight": 0.30,
        },
        {
            "type": AgentType.MODERATOR.value,
            "name": "토론 진행자",
            "description": "토론 진행, 최종 결정",
            "weight": 0.0,
        },
    ]

    return {
        "agents": agents,
        "total_weight": 1.0,
        "consensus_threshold": 0.75,
    }


@router.get("/decision-actions")
async def get_decision_actions():
    """
    Get available decision action types.

    Returns possible actions that can result from a discussion.
    """
    actions = [
        {
            "action": DecisionAction.BUY.value,
            "description": "신규 매수",
            "emoji": "🟢",
        },
        {
            "action": DecisionAction.SELL.value,
            "description": "전량 매도",
            "emoji": "🔴",
        },
        {
            "action": DecisionAction.HOLD.value,
            "description": "보유 유지",
            "emoji": "⏸️",
        },
        {
            "action": DecisionAction.ADD.value,
            "description": "추가 매수",
            "emoji": "🟢➕",
        },
        {
            "action": DecisionAction.REDUCE.value,
            "description": "일부 매도",
            "emoji": "🔴➖",
        },
        {
            "action": DecisionAction.WATCH.value,
            "description": "모니터링",
            "emoji": "👁",
        },
        {
            "action": DecisionAction.NO_ACTION.value,
            "description": "행동 없음",
            "emoji": "⏹️",
        },
    ]

    return {"actions": actions}


# -------------------------------------------
# Position Management Endpoints
# -------------------------------------------


class AddPositionRequest(BaseModel):
    """Request to add a position to monitor."""
    ticker: str = Field(..., description="Stock ticker code")
    stock_name: str = Field(..., description="Stock name")
    quantity: int = Field(..., ge=1, description="Position quantity")
    avg_price: float = Field(..., gt=0, description="Average entry price")
    current_price: Optional[float] = Field(None, gt=0, description="Current price")
    stop_loss: Optional[float] = Field(None, description="Stop-loss price")
    take_profit: Optional[float] = Field(None, description="Take-profit price")
    trailing_stop_pct: Optional[float] = Field(None, ge=0, le=50, description="Trailing stop percentage")


class UpdatePositionRequest(BaseModel):
    """Request to update a monitored position."""
    quantity: Optional[int] = Field(None, ge=0, description="New quantity")
    stop_loss: Optional[float] = Field(None, description="New stop-loss price")
    take_profit: Optional[float] = Field(None, description="New take-profit price")
    trailing_stop_pct: Optional[float] = Field(None, ge=0, le=50, description="New trailing stop percentage")


class PositionManagerConfigRequest(BaseModel):
    """Request to update position manager configuration."""
    check_interval_seconds: Optional[int] = Field(None, ge=10, le=300)
    stop_loss_warning_pct: Optional[float] = Field(None, ge=0.5, le=10)
    take_profit_warning_pct: Optional[float] = Field(None, ge=0.5, le=10)
    significant_gain_pct: Optional[float] = Field(None, ge=5, le=50)
    significant_loss_pct: Optional[float] = Field(None, ge=1, le=20)
    auto_execute_stop_loss: Optional[bool] = None
    auto_execute_take_profit: Optional[bool] = None
    auto_update_trailing: Optional[bool] = None


@router.get("/positions")
async def get_monitored_positions():
    """
    Get all monitored positions.

    Returns positions being tracked by the position manager.
    """
    coordinator = await get_chat_coordinator()

    if not coordinator.position_manager:
        return {
            "positions": [],
            "count": 0,
            "is_running": False,
        }

    pm = coordinator.position_manager
    positions = pm.get_all_positions()

    return {
        "positions": [
            {
                "ticker": p.ticker,
                "stock_name": p.stock_name,
                "quantity": p.quantity,
                "avg_price": p.avg_price,
                "current_price": p.current_price,
                "unrealized_pnl": p.unrealized_pnl,
                "unrealized_pnl_pct": p.unrealized_pnl_pct,
                "position_value": p.position_value,
                "stop_loss": p.stop_loss,
                "take_profit": p.take_profit,
                "trailing_stop_pct": p.trailing_stop_pct,
                "trailing_stop_price": p.trailing_stop_price,
                "highest_price": p.highest_price,
                "holding_days": p.holding_days,
                "discussion_count": p.discussion_count,
                "last_discussion": p.last_discussion.isoformat() if p.last_discussion else None,
            }
            for p in positions
        ],
        "count": len(positions),
        "is_running": pm._running,
    }


@router.get("/positions/summary")
async def get_position_summary():
    """
    Get position manager summary.

    Returns overall statistics and status.
    """
    coordinator = await get_chat_coordinator()

    if not coordinator.position_manager:
        return {
            "is_running": False,
            "position_count": 0,
            "total_value": 0,
            "total_unrealized_pnl": 0,
            "total_unrealized_pnl_pct": 0,
            "event_count": 0,
            "positions": [],
        }

    return coordinator.position_manager.get_summary()


@router.get("/positions/events")
async def get_position_events(
    ticker: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
):
    """
    Get position events.

    Returns events triggered by position monitoring.
    """
    coordinator = await get_chat_coordinator()

    if not coordinator.position_manager:
        return {
            "events": [],
            "count": 0,
        }

    from services.agent_chat import PositionEventType

    event_type_enum = None
    if event_type:
        try:
            event_type_enum = PositionEventType(event_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid event type: {event_type}",
            )

    events = coordinator.position_manager.get_events(
        ticker=ticker,
        event_type=event_type_enum,
        limit=limit,
    )

    return {
        "events": [
            {
                "id": e.id,
                "ticker": e.ticker,
                "event_type": e.event_type.value,
                "timestamp": e.timestamp.isoformat(),
                "current_price": e.current_price,
                "trigger_value": e.trigger_value,
                "message": e.message,
                "requires_discussion": e.requires_discussion,
                "auto_execute": e.auto_execute,
                "data": e.data,
            }
            for e in events
        ],
        "count": len(events),
    }


@router.get("/positions/event-types")
async def get_position_event_types():
    """Get available position event types."""
    from services.agent_chat import PositionEventType

    return {
        "event_types": [
            {
                "type": PositionEventType.STOP_LOSS_NEAR.value,
                "description": "손절가 근접",
                "emoji": "⚠️",
            },
            {
                "type": PositionEventType.STOP_LOSS_HIT.value,
                "description": "손절가 도달",
                "emoji": "🔴",
            },
            {
                "type": PositionEventType.TAKE_PROFIT_NEAR.value,
                "description": "익절가 근접",
                "emoji": "🎯",
            },
            {
                "type": PositionEventType.TAKE_PROFIT_HIT.value,
                "description": "익절가 도달",
                "emoji": "🟢",
            },
            {
                "type": PositionEventType.SIGNIFICANT_GAIN.value,
                "description": "상당한 수익",
                "emoji": "📈",
            },
            {
                "type": PositionEventType.SIGNIFICANT_LOSS.value,
                "description": "상당한 손실",
                "emoji": "📉",
            },
            {
                "type": PositionEventType.TRAILING_STOP_UPDATE.value,
                "description": "트레일링 스탑 갱신",
                "emoji": "📊",
            },
            {
                "type": PositionEventType.HOLDING_PERIOD_LONG.value,
                "description": "장기 보유",
                "emoji": "📅",
            },
            {
                "type": PositionEventType.VOLATILITY_SPIKE.value,
                "description": "변동성 급증",
                "emoji": "⚡",
            },
        ]
    }


@router.get("/positions/{ticker}")
async def get_position(ticker: str):
    """Get a specific monitored position."""
    coordinator = await get_chat_coordinator()

    if not coordinator.position_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Position manager not running",
        )

    position = coordinator.position_manager.get_position(ticker)

    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Position '{ticker}' not found",
        )

    return {
        "ticker": position.ticker,
        "stock_name": position.stock_name,
        "quantity": position.quantity,
        "avg_price": position.avg_price,
        "current_price": position.current_price,
        "unrealized_pnl": position.unrealized_pnl,
        "unrealized_pnl_pct": position.unrealized_pnl_pct,
        "position_value": position.position_value,
        "stop_loss": position.stop_loss,
        "take_profit": position.take_profit,
        "trailing_stop_pct": position.trailing_stop_pct,
        "trailing_stop_price": position.trailing_stop_price,
        "highest_price": position.highest_price,
        "lowest_price": position.lowest_price,
        "entry_time": position.entry_time.isoformat(),
        "holding_days": position.holding_days,
        "discussion_count": position.discussion_count,
        "last_discussion": position.last_discussion.isoformat() if position.last_discussion else None,
        "events_triggered": position.events_triggered,
    }


@router.post("/positions")
async def add_position(request: AddPositionRequest):
    """
    Add a position to monitor.

    Starts tracking the position for stop-loss, take-profit, and other events.
    """
    coordinator = await get_chat_coordinator()

    if not coordinator.position_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Position manager not running. Start the coordinator first.",
        )

    try:
        position = coordinator.position_manager.add_position(
            ticker=request.ticker,
            stock_name=request.stock_name,
            quantity=request.quantity,
            avg_price=request.avg_price,
            current_price=request.current_price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            trailing_stop_pct=request.trailing_stop_pct,
        )

        return {
            "status": "added",
            "ticker": position.ticker,
            "message": f"Position {request.stock_name} added to monitoring",
        }

    except Exception as e:
        logger.exception("Failed to add position")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add position: {str(e)}",
        )


@router.put("/positions/{ticker}")
async def update_position(ticker: str, request: UpdatePositionRequest):
    """Update a monitored position's parameters."""
    coordinator = await get_chat_coordinator()

    if not coordinator.position_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Position manager not running",
        )

    position = coordinator.position_manager.update_position(
        ticker=ticker,
        quantity=request.quantity,
        stop_loss=request.stop_loss,
        take_profit=request.take_profit,
        trailing_stop_pct=request.trailing_stop_pct,
    )

    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Position '{ticker}' not found",
        )

    return {
        "status": "updated",
        "ticker": ticker,
        "stop_loss": position.stop_loss,
        "take_profit": position.take_profit,
        "trailing_stop_pct": position.trailing_stop_pct,
    }


@router.delete("/positions/{ticker}")
async def remove_position(ticker: str):
    """Remove a position from monitoring."""
    coordinator = await get_chat_coordinator()

    if not coordinator.position_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Position manager not running",
        )

    success = coordinator.position_manager.remove_position(ticker)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Position '{ticker}' not found",
        )

    return {
        "status": "removed",
        "ticker": ticker,
    }


@router.post("/positions/sync")
async def sync_positions():
    """
    Sync positions from account holdings.

    Updates monitored positions to match current account holdings.
    """
    coordinator = await get_chat_coordinator()

    if not coordinator.position_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Position manager not running. Start the coordinator first.",
        )

    try:
        await coordinator.position_manager.sync_from_account()

        positions = coordinator.position_manager.get_all_positions()

        return {
            "status": "synced",
            "position_count": len(positions),
            "tickers": [p.ticker for p in positions],
        }

    except Exception as e:
        logger.exception("Failed to sync positions")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync positions: {str(e)}",
        )
