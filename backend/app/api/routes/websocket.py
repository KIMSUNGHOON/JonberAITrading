"""
WebSocket Routes for Real-time Updates

Provides real-time streaming of:
- Reasoning logs
- Status updates
- Trade proposals
- Position updates
- Real-time market data (ticker, trade)
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional, Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.routes.analysis import get_active_sessions
from app.api.routes.coin import get_coin_sessions
from app.api.routes.kr_stocks import get_kr_stock_sessions

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
# Analysis Results Extraction Helpers
# -------------------------------------------


def _extract_analysis_results(state: dict) -> dict | None:
    """
    Extract detailed analysis results from session state.

    Returns structured analysis results matching DetailedAnalysisResults frontend type.
    Handles both KR Stock (KRStockAnalysisResult) and other analysis formats.
    """
    results = {}

    # Technical Analysis
    tech = state.get("technical_analysis")
    if tech:
        # KR Stock stores indicators in 'signals' dict
        tech_signals = tech.get("signals", {})

        results["technical"] = {
            "summary": tech.get("reasoning", "") or tech.get("summary", ""),  # Use full reasoning, fallback to summary
            "recommendation": _normalize_action(tech.get("signal", "HOLD")),
            "confidence": safe_float(tech.get("confidence", 0.5)) * 100,  # Convert to 0-100
            "indicators": {
                "rsi": safe_float(tech_signals.get("rsi") or tech.get("rsi")),
                "macd": _extract_macd_from_signals(tech_signals) or _extract_macd(tech),
                "sma50": safe_float(tech_signals.get("sma_20") or tech.get("sma_50")),
                "sma200": safe_float(tech_signals.get("sma_60") or tech.get("sma_200")),
                "bollingerBands": _extract_bollinger_from_signals(tech_signals) or _extract_bollinger(tech),
                "stochastic_k": safe_float(tech_signals.get("stochastic_k")),
                "atr": safe_float(tech_signals.get("atr")),
                "volume_ratio": safe_float(tech_signals.get("volume_ratio")),
            },
            "signals": tech.get("key_factors", [])[:5],
            "trend": tech_signals.get("trend", "neutral"),
            "cross": tech_signals.get("cross"),
        }

    # Fundamental Analysis
    fund = state.get("fundamental_analysis")
    if fund:
        # KR Stock stores metrics in 'signals' dict
        fund_signals = fund.get("signals", {})

        results["fundamental"] = {
            "summary": fund.get("reasoning", "") or fund.get("summary", ""),  # Use full reasoning, fallback to summary
            "recommendation": _normalize_action(fund.get("signal", "HOLD")),
            "confidence": safe_float(fund.get("confidence", 0.5)) * 100,
            "metrics": {
                "per": safe_float(fund_signals.get("per") or fund.get("per")),
                "pbr": safe_float(fund_signals.get("pbr") or fund.get("pbr")),
                "roe": safe_float(fund_signals.get("roe") or fund.get("roe")),
                "eps": safe_float(fund_signals.get("eps") or fund.get("eps")),
                "debtRatio": safe_float(fund.get("debt_ratio")),
                "revenueGrowth": safe_float(fund.get("revenue_growth")),
                "operatingMargin": safe_float(fund.get("operating_margin")),
            },
            "highlights": fund.get("key_factors", [])[:5],
            "financialHealth": _get_financial_health(fund_signals),
        }

    # Sentiment Analysis
    sent = state.get("sentiment_analysis")
    if sent:
        # KR Stock stores sentiment data in 'signals' dict
        sent_signals = sent.get("signals", {})

        results["sentiment"] = {
            "summary": sent.get("reasoning", "") or sent.get("summary", ""),  # Use full reasoning, fallback to summary
            "recommendation": _normalize_action(sent.get("signal", "HOLD")),
            "confidence": safe_float(sent.get("confidence", 0.5)) * 100,
            "sentiment": _normalize_sentiment(sent_signals.get("news_sentiment") or sent.get("sentiment", "neutral")),
            "sentimentScore": safe_float(sent.get("sentiment_score", 0)),
            "newsCount": safe_int(sent.get("news_count", 0)),
            "recentNews": sent.get("recent_news", [])[:5],
            "socialMentions": safe_int(sent.get("social_mentions")),
            "analystRatings": sent.get("analyst_ratings"),
        }

    # Risk Assessment
    risk = state.get("risk_assessment")
    if risk:
        # KR Stock stores risk data in 'signals' dict
        risk_signals = risk.get("signals", {})
        risk_score = safe_float(risk_signals.get("risk_score", risk.get("risk_score", 0.5)))

        results["risk"] = {
            "summary": risk.get("reasoning", "") or risk.get("summary", ""),  # Use full reasoning, fallback to summary
            "riskLevel": _get_risk_level(risk_score),
            "confidence": safe_float(risk.get("confidence", 0.5)) * 100,
            "riskScore": risk_score * 100,  # Convert to 0-100
            "factors": _format_risk_factors(risk.get("key_factors", [])),
            "volatility": None,  # Not available in KR Stock analysis
            "suggestedStopLoss": safe_float(risk_signals.get("suggested_stop_loss") or risk.get("stop_loss")),
            "suggestedTakeProfit": safe_float(risk_signals.get("suggested_take_profit") or risk.get("take_profit")),
            "maxPositionSize": safe_float(risk_signals.get("max_position_pct")),
        }

    return results if results else None


def _get_financial_health(fund_signals: dict) -> str:
    """Determine financial health based on fundamental metrics."""
    per = safe_float(fund_signals.get("per"))
    pbr = safe_float(fund_signals.get("pbr"))

    # Simple heuristic based on valuation metrics
    if per is None and pbr is None:
        return "unknown"

    score = 0
    if per is not None:
        if 5 < per < 15:
            score += 1
        elif per > 30 or per < 0:
            score -= 1
    if pbr is not None:
        if 0.5 < pbr < 2:
            score += 1
        elif pbr > 5 or pbr < 0:
            score -= 1

    if score >= 1:
        return "strong"
    elif score <= -1:
        return "weak"
    return "moderate"


def _normalize_sentiment(sentiment: str | None) -> str:
    """Normalize sentiment to positive/neutral/negative."""
    if sentiment is None:
        return "neutral"
    s = str(sentiment).lower()
    if s in ("positive", "bullish", "긍정"):
        return "positive"
    if s in ("negative", "bearish", "부정"):
        return "negative"
    return "neutral"


def _format_risk_factors(factors: list) -> list[dict]:
    """Convert simple string factors to structured format."""
    result = []
    for i, factor in enumerate(factors[:5]):
        if isinstance(factor, dict):
            result.append(factor)
        else:
            # Convert string to structured format
            factor_str = str(factor)
            impact = "neutral"
            if any(kw in factor_str.lower() for kw in ["위험", "risk", "하락", "부정"]):
                impact = "negative"
            elif any(kw in factor_str.lower() for kw in ["기회", "opportunity", "상승", "긍정"]):
                impact = "positive"

            result.append({
                "name": f"Factor {i+1}",
                "impact": impact,
                "weight": 0.5,
                "description": factor_str,
            })
    return result


def _get_risk_level(risk_score: float | None) -> str:
    """Convert risk score to risk level string."""
    if risk_score is None:
        return "medium"
    score = safe_float(risk_score, 0.5)
    if score < 0.3:
        return "low"
    if score > 0.7:
        return "high"
    return "medium"


def _extract_macd_from_signals(signals: dict) -> dict | None:
    """Extract MACD data from KR Stock signals dict."""
    histogram = signals.get("macd_histogram")
    if histogram is None:
        return None
    return {
        "value": None,  # KR Stock doesn't store MACD line separately
        "signal": None,
        "histogram": safe_float(histogram),
    }


def _extract_bollinger_from_signals(signals: dict) -> dict | None:
    """Extract Bollinger Bands from KR Stock signals dict."""
    upper = signals.get("bollinger_upper")
    lower = signals.get("bollinger_lower")
    if upper is None and lower is None:
        return None
    return {
        "upper": safe_float(upper),
        "middle": None,
        "lower": safe_float(lower),
    }


def _normalize_action(signal: Any) -> str:
    """Normalize signal/action to BUY/SELL/HOLD."""
    if signal is None:
        return "HOLD"
    signal_str = str(signal).upper()
    if signal_str in ("BUY", "STRONG_BUY", "BULLISH"):
        return "BUY"
    if signal_str in ("SELL", "STRONG_SELL", "BEARISH"):
        return "SELL"
    return "HOLD"


def _extract_macd(tech: dict) -> dict | None:
    """Extract MACD data from technical analysis."""
    if not tech.get("macd"):
        return None
    macd = tech["macd"]
    if isinstance(macd, dict):
        return {
            "value": safe_float(macd.get("value", macd.get("macd"))),
            "signal": safe_float(macd.get("signal")),
            "histogram": safe_float(macd.get("histogram")),
        }
    return None


def _extract_bollinger(tech: dict) -> dict | None:
    """Extract Bollinger Bands data from technical analysis."""
    if not tech.get("bollinger_bands") and not tech.get("bb_upper"):
        return None
    bb = tech.get("bollinger_bands", {})
    if isinstance(bb, dict):
        return {
            "upper": safe_float(bb.get("upper", tech.get("bb_upper"))),
            "middle": safe_float(bb.get("middle", tech.get("bb_middle"))),
            "lower": safe_float(bb.get("lower", tech.get("bb_lower"))),
        }
    return {
        "upper": safe_float(tech.get("bb_upper")),
        "middle": safe_float(tech.get("bb_middle")),
        "lower": safe_float(tech.get("bb_lower")),
    }


def _serialize_proposal(proposal: dict, full: bool = False) -> dict:
    """
    Serialize trade proposal for WebSocket transmission.

    Args:
        proposal: Trade proposal dict
        full: If True, include full content without truncation (for complete messages).
              If False, truncate for smaller notification messages.
    """
    action = proposal.get("action", "HOLD")
    if hasattr(action, "value"):
        action = action.value

    rationale = str(proposal.get("rationale", "") or "")
    bull_case = str(proposal.get("bull_case", "") or "")
    bear_case = str(proposal.get("bear_case", "") or "")

    # Apply truncation only for notification messages (not full/complete messages)
    if not full:
        rationale = rationale[:2000]  # Increased from 1000
        bull_case = bull_case[:1000]   # Increased from 500
        bear_case = bear_case[:1000]   # Increased from 500

    # Get ticker/symbol with fallbacks for different market types
    ticker = proposal.get("ticker") or proposal.get("market") or proposal.get("stk_cd", "")

    # Get display name (stock name or korean name) for UI display
    display_name = proposal.get("stk_nm") or proposal.get("korean_name") or ""

    return {
        "id": str(proposal.get("id", "")),
        "ticker": ticker,
        "display_name": display_name,  # Add display name for proper UI rendering
        "action": str(action),
        "quantity": safe_int(proposal.get("quantity"), 0),
        "entry_price": safe_float(proposal.get("entry_price")),
        "stop_loss": safe_float(proposal.get("stop_loss")),
        "take_profit": safe_float(proposal.get("take_profit")),
        "risk_score": safe_float(proposal.get("risk_score"), 0.5),
        "rationale": rationale,
        "bull_case": bull_case,
        "bear_case": bear_case,
    }


def _create_reasoning_summary(reasoning_log: list) -> str:
    """Create a summary from reasoning log entries."""
    if not reasoning_log:
        return ""

    # Filter for synthesis/final entries or take last few entries
    summary_entries = []
    for entry in reversed(reasoning_log):
        entry_str = str(entry)
        # Prioritize synthesis and final decision entries
        if any(kw in entry_str.lower() for kw in ["synthesis", "결론", "종합", "final", "decision", "결정"]):
            summary_entries.insert(0, entry_str)
            if len(summary_entries) >= 3:
                break

    # If no synthesis entries found, take last 3 entries
    if not summary_entries:
        summary_entries = [str(e) for e in reasoning_log[-3:]]

    return "\n".join(summary_entries)[:5000]  # Increased from 2000


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
            # Check all session types: US stocks, coins, and Korean stocks (Kiwoom)
            stock_sessions = get_active_sessions()
            coin_sessions = get_coin_sessions()
            kr_stock_sessions = get_kr_stock_sessions()

            session = (
                stock_sessions.get(session_id) or
                coin_sessions.get(session_id) or
                kr_stock_sessions.get(session_id)
            )

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
                            "session_id": session_id,
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
                        "session_id": session_id,
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

                    # Support stock (ticker), coin (market), and Korean stock (stk_cd) proposals
                    ticker_or_market = proposal.get("ticker") or proposal.get("market") or proposal.get("stk_cd", "")
                    display_name = proposal.get("stk_nm") or proposal.get("korean_name") or ""

                    await websocket.send_json({
                        "type": "proposal",
                        "data": {
                            "session_id": session_id,
                            "id": str(proposal.get("id", "")),
                            "ticker": str(ticker_or_market),
                            "display_name": display_name,  # Include display name
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
                        "session_id": session_id,
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
                    # Build complete message with detailed analysis results
                    complete_data = {
                        "status": current_status,
                        "error": session.get("error"),
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }

                    # Include analysis results if completed successfully
                    if current_status == "completed":
                        # INFO level logging for troubleshooting (visible in console)
                        tech_data = state.get("technical_analysis")
                        fund_data = state.get("fundamental_analysis")
                        sent_data = state.get("sentiment_analysis")
                        risk_data = state.get("risk_assessment")

                        logger.info(
                            "websocket_complete_state_check",
                            session_id=session_id,
                            state_keys=list(state.keys()) if state else [],
                            has_technical=tech_data is not None,
                            has_fundamental=fund_data is not None,
                            has_sentiment=sent_data is not None,
                            has_risk=risk_data is not None,
                            tech_type=type(tech_data).__name__ if tech_data else None,
                        )

                        # Extract analysis results from state
                        analysis_results = _extract_analysis_results(state)
                        logger.info(
                            "websocket_analysis_results_extracted",
                            session_id=session_id,
                            has_results=analysis_results is not None,
                            result_keys=list(analysis_results.keys()) if analysis_results else [],
                        )
                        if analysis_results:
                            complete_data["analysis_results"] = analysis_results
                        else:
                            # Log warning if no analysis results were extracted
                            logger.warning(
                                "websocket_no_analysis_results",
                                session_id=session_id,
                                state_keys=list(state.keys()) if state else [],
                            )

                        # Include trade proposal
                        proposal = state.get("trade_proposal")
                        if proposal:
                            complete_data["trade_proposal"] = _serialize_proposal(proposal, full=True)

                        # Include reasoning summary (last few entries)
                        reasoning_log = state.get("reasoning_log", [])
                        if reasoning_log:
                            # Create a summary from the last synthesis/final entries
                            complete_data["reasoning_summary"] = _create_reasoning_summary(reasoning_log)

                    await websocket.send_json({
                        "type": "complete",
                        "session_id": session_id,
                        "data": complete_data,
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
                            "session_id": session_id,
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
                    # Send current sessions summary (stock, coin, and kr_stock)
                    stock_sessions = get_active_sessions()
                    coin_sessions_dict = get_coin_sessions()
                    kr_stock_sessions_dict = get_kr_stock_sessions()

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
                    for sid, s in list(kr_stock_sessions_dict.items())[:5]:
                        all_sessions.append({
                            "id": sid,
                            "ticker": s.get("stk_cd", ""),
                            "status": s["status"],
                            "type": "kiwoom",
                        })

                    await websocket.send_json({
                        "type": "sessions",
                        "data": {
                            "total": len(stock_sessions) + len(coin_sessions_dict) + len(kr_stock_sessions_dict),
                            "sessions": all_sessions[:15],
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


# -------------------------------------------
# Real-time Market Data WebSocket
# -------------------------------------------


@router.websocket("/ticker")
async def websocket_ticker(websocket: WebSocket):
    """
    WebSocket endpoint for real-time ticker data.

    Streams real-time price updates from Upbit via WebSocket.
    Much more efficient than polling the REST API.

    Client can send:
    - {"action": "subscribe", "markets": ["KRW-BTC", "KRW-ETH"]}
    - {"action": "unsubscribe", "markets": ["KRW-BTC"]}
    - "ping": Heartbeat (server responds with "pong")

    Server sends:
    - {"type": "ticker", "market": "KRW-BTC", "trade_price": 12345, ...}
    - {"type": "subscribed", "markets": ["KRW-BTC", "KRW-ETH"]}
    - {"type": "error", "message": "..."}
    """
    from services.realtime_service import get_realtime_service

    await websocket.accept()
    logger.info("ticker_websocket_connected")

    # Get realtime service
    try:
        service = await get_realtime_service()
    except Exception as e:
        logger.error("realtime_service_unavailable", error=str(e))
        await websocket.send_json({
            "type": "error",
            "message": "Realtime service unavailable",
        })
        await websocket.close()
        return

    # Track subscribed markets for cleanup
    subscribed_markets: set[str] = set()

    # Callback to send ticker data to this client
    async def send_ticker(data: dict):
        try:
            await websocket.send_json(data)
        except Exception:
            pass  # Will be handled in disconnect

    # Sync wrapper for async callback
    def ticker_callback(data: dict):
        try:
            asyncio.create_task(send_ticker(data))
        except RuntimeError:
            pass  # Event loop closed

    try:
        while True:
            try:
                # Wait for client message with timeout
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0,
                )

                # Handle ping/pong
                if data == "ping":
                    await websocket.send_text("pong")
                    continue

                # Parse JSON message
                try:
                    message = json.loads(data)
                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid JSON",
                    })
                    continue

                action = message.get("action")
                markets = message.get("markets", [])

                if not isinstance(markets, list):
                    markets = [markets] if markets else []

                # Normalize market codes
                markets = [m.upper() for m in markets if m]

                if action == "subscribe" and markets:
                    await service.subscribe_ticker(markets, ticker_callback)
                    subscribed_markets.update(markets)

                    await websocket.send_json({
                        "type": "subscribed",
                        "markets": list(subscribed_markets),
                    })
                    logger.debug(
                        "ticker_client_subscribed",
                        markets=markets,
                    )

                elif action == "unsubscribe" and markets:
                    await service.unsubscribe_ticker(markets, ticker_callback)
                    subscribed_markets.difference_update(markets)

                    await websocket.send_json({
                        "type": "unsubscribed",
                        "markets": markets,
                    })

                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown action: {action}",
                    })

            except asyncio.TimeoutError:
                # Send heartbeat
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break

    except WebSocketDisconnect:
        logger.info("ticker_websocket_disconnected")
    except Exception as e:
        logger.error("ticker_websocket_error", error=str(e))
    finally:
        # Cleanup: unsubscribe from all markets
        if subscribed_markets:
            try:
                await service.unsubscribe_all(ticker_callback)
            except Exception as e:
                logger.warning("ticker_cleanup_error", error=str(e))
