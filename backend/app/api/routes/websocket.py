"""
WebSocket Routes for Real-time Updates

Provides real-time streaming of:
- Reasoning logs
- Status updates
- Trade proposals
- Position updates
"""

import asyncio
from typing import Optional

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.routes.analysis import get_active_sessions
from app.api.routes.coin import get_coin_sessions

logger = structlog.get_logger()
router = APIRouter()


# -------------------------------------------
# Connection Manager
# -------------------------------------------


class ConnectionManager:
    """Manages WebSocket connections per session."""

    def __init__(self):
        self.active_connections: dict[str, set[WebSocket]] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        """Accept and register a WebSocket connection."""
        await websocket.accept()

        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()

        self.active_connections[session_id].add(websocket)

        logger.info(
            "websocket_connected",
            session_id=session_id,
            total_connections=len(self.active_connections[session_id]),
        )

    def disconnect(self, session_id: str, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if session_id in self.active_connections:
            self.active_connections[session_id].discard(websocket)

            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

        logger.info("websocket_disconnected", session_id=session_id)

    async def send_to_session(self, session_id: str, message: dict):
        """Send message to all connections for a session."""
        if session_id not in self.active_connections:
            return

        dead_connections = set()

        for connection in self.active_connections[session_id]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(
                    "websocket_send_failed",
                    session_id=session_id,
                    error=str(e),
                )
                dead_connections.add(connection)

        # Clean up dead connections
        for conn in dead_connections:
            self.active_connections[session_id].discard(conn)

    async def broadcast(self, message: dict):
        """Broadcast message to all connections."""
        for session_id in self.active_connections:
            await self.send_to_session(session_id, message)


# Global connection manager
manager = ConnectionManager()


# -------------------------------------------
# Safe Type Conversion Helpers
# -------------------------------------------


def safe_float(val, default=None):
    """Convert value to float safely, handling numpy types."""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def safe_int(val, default=0):
    """Convert value to int safely, handling numpy types."""
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


# -------------------------------------------
# WebSocket Endpoints
# -------------------------------------------


@router.websocket("/session/{session_id}")
async def websocket_session(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time session updates.

    Streams:
    - reasoning: New reasoning log entries
    - status: Status changes
    - proposal: Trade proposal when ready
    - position: Position updates
    - complete: Session completion

    Client can send:
    - "ping": Heartbeat (server responds with "pong")
    """
    await manager.connect(session_id, websocket)

    # Get both stock and coin sessions
    stock_sessions = get_active_sessions()
    coin_sessions = get_coin_sessions()

    # Track what we've sent to avoid duplicates
    last_log_index = 0
    last_status: Optional[str] = None
    last_stage: Optional[str] = None
    proposal_sent = False

    try:
        logger.debug(
            "websocket_loop_started",
            session_id=session_id,
        )

        while True:
            # Check both stock and coin sessions
            session = stock_sessions.get(session_id) or coin_sessions.get(session_id)

            if session:
                state = session["state"]
                current_status = session["status"]
                reasoning_log = state.get("reasoning_log", [])

                # Send new reasoning log entries
                if len(reasoning_log) > last_log_index:
                    new_entries = reasoning_log[last_log_index:]
                    for entry in new_entries:
                        await websocket.send_json({
                            "type": "reasoning",
                            "data": entry,
                        })
                    logger.debug(
                        "websocket_reasoning_sent",
                        session_id=session_id,
                        count=len(new_entries),
                    )
                    last_log_index = len(reasoning_log)

                # Extract stage value from enum or string
                stage = state.get("current_stage", "")
                if hasattr(stage, "value"):
                    stage = stage.value
                else:
                    stage = str(stage) if stage else ""

                # Send status updates when status OR stage changes
                if current_status != last_status or stage != last_stage:
                    await websocket.send_json({
                        "type": "status",
                        "data": {
                            "status": current_status,
                            "stage": stage,
                            "awaiting_approval": state.get("awaiting_approval", False),
                        },
                    })
                    logger.debug(
                        "websocket_status_sent",
                        session_id=session_id,
                        status=current_status,
                        stage=stage,
                    )
                    last_status = current_status
                    last_stage = stage

                # Send trade proposal when available (once)
                # proposal is now a dict after serialization fix
                if state.get("trade_proposal") and state.get("awaiting_approval") and not proposal_sent:
                    proposal = state["trade_proposal"]
                    action = proposal.get("action", "HOLD")
                    if hasattr(action, "value"):
                        action = action.value

                    # Support both stock (ticker) and coin (market) proposals
                    ticker_or_market = proposal.get("ticker") or proposal.get("market", "")

                    await websocket.send_json({
                        "type": "proposal",
                        "data": {
                            "id": str(proposal.get("id", "")),
                            "ticker": str(ticker_or_market),
                            "action": str(action),
                            "quantity": safe_int(proposal.get("quantity"), 0),
                            "entry_price": safe_float(proposal.get("entry_price")),
                            "stop_loss": safe_float(proposal.get("stop_loss")),
                            "take_profit": safe_float(proposal.get("take_profit")),
                            "risk_score": safe_float(proposal.get("risk_score"), 0.5),
                            "rationale": str(proposal.get("rationale", "") or "")[:500],
                        },
                    })
                    proposal_sent = True
                    logger.info(
                        "websocket_proposal_sent",
                        session_id=session_id,
                        ticker=ticker_or_market,
                        action=action,
                    )

                # Send position updates (position is now a dict after serialization)
                if state.get("active_position"):
                    position = state["active_position"]
                    # Calculate PnL since Position is now a dict
                    # Use safe conversion for numpy types
                    entry_price = safe_float(position.get("entry_price"), 0)
                    current_price = safe_float(position.get("current_price"), 0)
                    quantity = safe_int(position.get("quantity"), 0)
                    pnl = (current_price - entry_price) * quantity
                    pnl_percent = ((current_price / entry_price) - 1) * 100 if entry_price else 0

                    # Support both stock (ticker) and coin (market) positions
                    position_ticker = position.get("ticker") or position.get("market", "")

                    await websocket.send_json({
                        "type": "position",
                        "data": {
                            "ticker": str(position_ticker),
                            "quantity": quantity,
                            "entry_price": entry_price,
                            "current_price": current_price,
                            "pnl": round(float(pnl), 2),
                            "pnl_percent": round(float(pnl_percent), 2),
                        },
                    })

                # Check for completion
                if current_status in ("completed", "cancelled", "error"):
                    await websocket.send_json({
                        "type": "complete",
                        "data": {
                            "status": current_status,
                            "error": session.get("error"),
                        },
                    })
                    # Keep connection open for a bit, then close
                    await asyncio.sleep(2)
                    break

            # Handle incoming messages (ping/pong)
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=0.5,
                )
                if data == "ping":
                    await websocket.send_text("pong")
                elif data == "status":
                    # On-demand status request
                    if session:
                        await websocket.send_json({
                            "type": "status",
                            "data": {
                                "status": session["status"],
                                "stage": str(session["state"].get("current_stage", "")),
                                "awaiting_approval": session["state"].get("awaiting_approval", False),
                            },
                        })

            except asyncio.TimeoutError:
                pass

            # Polling interval
            await asyncio.sleep(0.3)

    except WebSocketDisconnect:
        logger.info("websocket_client_disconnected", session_id=session_id)
    except Exception as e:
        logger.error(
            "websocket_error",
            session_id=session_id,
            error=str(e),
        )
    finally:
        manager.disconnect(session_id, websocket)


@router.websocket("/broadcast")
async def websocket_broadcast(websocket: WebSocket):
    """
    WebSocket endpoint for system-wide broadcasts.

    Useful for monitoring all sessions.
    """
    await websocket.accept()

    try:
        while True:
            # Send heartbeat
            await websocket.send_json({
                "type": "heartbeat",
                "data": {"timestamp": asyncio.get_event_loop().time()},
            })

            # Handle incoming messages
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=5.0,
                )
                if data == "ping":
                    await websocket.send_text("pong")
                elif data == "sessions":
                    # Send current sessions summary (both stock and coin)
                    stock_sessions = get_active_sessions()
                    coin_sessions_dict = get_coin_sessions()

                    all_sessions = []
                    for sid, s in list(stock_sessions.items())[:5]:
                        all_sessions.append({
                            "id": sid,
                            "ticker": s["ticker"],
                            "status": s["status"],
                            "type": "stock",
                        })
                    for sid, s in list(coin_sessions_dict.items())[:5]:
                        all_sessions.append({
                            "id": sid,
                            "ticker": s.get("market", ""),
                            "status": s["status"],
                            "type": "coin",
                        })

                    await websocket.send_json({
                        "type": "sessions",
                        "data": {
                            "total": len(stock_sessions) + len(coin_sessions_dict),
                            "sessions": all_sessions[:10],
                        },
                    })

            except asyncio.TimeoutError:
                pass

    except WebSocketDisconnect:
        logger.info("broadcast_websocket_disconnected")
    except Exception as e:
        logger.error("broadcast_websocket_error", error=str(e))


# -------------------------------------------
# Helper for External Broadcasting
# -------------------------------------------


async def broadcast_to_session(session_id: str, message_type: str, data: dict):
    """
    Broadcast a message to all WebSocket clients for a session.

    Can be called from other parts of the application.

    Args:
        session_id: Target session
        message_type: Message type (reasoning, status, etc.)
        data: Message payload
    """
    await manager.send_to_session(session_id, {
        "type": message_type,
        "data": data,
    })
