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

    active_sessions = get_active_sessions()

    # Track what we've sent to avoid duplicates
    last_log_index = 0
    last_status: Optional[str] = None
    proposal_sent = False

    try:
        while True:
            session = active_sessions.get(session_id)

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
                    last_log_index = len(reasoning_log)

                # Send status updates
                if current_status != last_status:
                    await websocket.send_json({
                        "type": "status",
                        "data": {
                            "status": current_status,
                            "stage": str(state.get("current_stage", "")),
                            "awaiting_approval": state.get("awaiting_approval", False),
                        },
                    })
                    last_status = current_status

                # Send trade proposal when available (once)
                if state.get("trade_proposal") and state.get("awaiting_approval") and not proposal_sent:
                    proposal = state["trade_proposal"]
                    await websocket.send_json({
                        "type": "proposal",
                        "data": {
                            "id": proposal.id,
                            "ticker": proposal.ticker,
                            "action": proposal.action.value if hasattr(proposal.action, "value") else proposal.action,
                            "quantity": proposal.quantity,
                            "entry_price": proposal.entry_price,
                            "stop_loss": proposal.stop_loss,
                            "take_profit": proposal.take_profit,
                            "risk_score": proposal.risk_score,
                            "rationale": proposal.rationale[:500] if proposal.rationale else "",
                        },
                    })
                    proposal_sent = True

                # Send position updates
                if state.get("active_position"):
                    position = state["active_position"]
                    await websocket.send_json({
                        "type": "position",
                        "data": {
                            "ticker": position.ticker,
                            "quantity": position.quantity,
                            "entry_price": position.entry_price,
                            "current_price": position.current_price,
                            "pnl": position.pnl,
                            "pnl_percent": position.pnl_percent,
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
                    # Send current sessions summary
                    active_sessions = get_active_sessions()
                    await websocket.send_json({
                        "type": "sessions",
                        "data": {
                            "total": len(active_sessions),
                            "sessions": [
                                {
                                    "id": sid,
                                    "ticker": s["ticker"],
                                    "status": s["status"],
                                }
                                for sid, s in list(active_sessions.items())[:10]
                            ],
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
