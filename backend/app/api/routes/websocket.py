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
import time
from datetime import datetime, timezone
from typing import Optional, Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from services.session_manager import get_session_manager

logger = structlog.get_logger()
router = APIRouter()

# /session/{id} wait interval. SessionManager pub/sub notifications are the
# primary wake source (all analysis producers register + mirror into sm as of
# P7 Phase 2); this poll is only the safety net — it covers sessions whose sm
# registration failed (producers degrade to legacy-dict-only writes) and any
# producer path that writes without notifying. The old 0.3s legacy fast poll
# was deleted with the last un-migrated producer.
SAFETY_POLL_SECONDS = 1.0
# Keep the connection open briefly after the complete frame so slow clients read it.
COMPLETE_LINGER_SECONDS = 2.0

# P0-2: a session id with no snapshot anywhere (legacy dicts AND SessionManager)
# will never produce frames. Give producers a short grace to register the
# session (start-path race), then close with a dedicated code instead of
# safety-polling forever — the FE drops its card and never reconnects on 4404.
NOT_FOUND_GRACE_SECONDS = 10.0
WS_CLOSE_SESSION_NOT_FOUND = 4404

# Cap the initial full-log replay on connect: long sessions (hundreds of
# reasoning entries) were serialized+sent back-to-back in a tight loop on
# every reconnect, bursting past the dev proxy's buffer (EPIPE -> ws close
# 1006) and pinning the event loop during json-encode. Only the initial
# connect snapshot is capped — live deltas after connect are unaffected
# because the cursor is positioned at the true (uncapped) log length, not
# the capped send count, so no gap/dup appears once streaming continues.
SNAPSHOT_MAX_REASONING = 100
# Send pacing: yield to the loop after every frame, and take a slightly
# longer breather every N frames, so the proxy can flush the socket buffer
# instead of getting hit with a burst of hundreds of frames in one tick.
SNAPSHOT_PACE_SLEEP_EVERY = 20
SNAPSHOT_PACE_SLEEP_SECONDS = 0.01


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
# Trade Notification Manager
# -------------------------------------------


class TradeNotificationManager:
    """Manages WebSocket connections for trade execution notifications."""

    def __init__(self):
        self.subscribers: set[WebSocket] = set()

    async def subscribe(self, websocket: WebSocket):
        """Accept and register a WebSocket for trade notifications."""
        await websocket.accept()
        self.subscribers.add(websocket)
        logger.info(
            "trade_notification_subscribed",
            total_subscribers=len(self.subscribers),
        )

    def unsubscribe(self, websocket: WebSocket):
        """Remove a WebSocket from trade notifications."""
        self.subscribers.discard(websocket)
        logger.info(
            "trade_notification_unsubscribed",
            total_subscribers=len(self.subscribers),
        )

    async def broadcast(self, notification: dict):
        """Broadcast trade notification to all subscribers."""
        if not self.subscribers:
            return

        dead_connections = set()

        for ws in self.subscribers:
            try:
                await ws.send_json(notification)
            except Exception as e:
                logger.warning(
                    "trade_notification_send_failed",
                    error=str(e),
                )
                dead_connections.add(ws)

        # Clean up dead connections
        for conn in dead_connections:
            self.subscribers.discard(conn)


# Global trade notification manager
trade_notification_manager = TradeNotificationManager()


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


async def _get_session_snapshot(session_id: str) -> Optional[dict]:
    """
    Look up a session snapshot.

    P1 (session-SSOT): the SessionManager is the sole read source -- legacy
    in-memory dicts were retired in P3-1 (see app/api/routes/approval.py for
    the same read path).
    """
    sm = await get_session_manager()
    return await sm.get_session_dict(session_id)


class _SessionFrameCursor:
    """
    Tracks what one /session connection has already been sent, so both wake
    sources (SessionManager pub/sub push and the fallback poll) emit each
    frame exactly once regardless of how often the loop wakes.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.last_log_index = 0
        self.last_status: Optional[str] = None
        self.last_stage: Optional[str] = None
        self.proposal_sent = False
        self.last_position: Optional[dict] = None
        self.last_auto_approve_at: Optional[str] = None

    async def emit(self, websocket: WebSocket, session: dict) -> bool:
        """Send any not-yet-sent frames for this session. True when complete sent."""
        session_id = self.session_id
        state = session["state"]
        current_status = session["status"]
        reasoning_log = state.get("reasoning_log", [])

        # Send new reasoning log entries
        if len(reasoning_log) > self.last_log_index:
            new_entries = reasoning_log[self.last_log_index:]
            # Only the very first batch this connection ever sees is a
            # "snapshot replay" (last_log_index still at its initial 0);
            # everything after that is an incremental live delta and must
            # never be capped.
            is_initial_snapshot = self.last_log_index == 0
            frames_to_send = new_entries
            if is_initial_snapshot and len(new_entries) > SNAPSHOT_MAX_REASONING:
                omitted = len(new_entries) - SNAPSHOT_MAX_REASONING
                frames_to_send = [
                    f"... (이전 {omitted}줄 생략)",
                    *new_entries[-SNAPSHOT_MAX_REASONING:],
                ]

            for i, entry in enumerate(frames_to_send, start=1):
                await websocket.send_json({
                    "type": "reasoning",
                    "data": entry,
                    "session_id": session_id,
                })
                # Yield every frame so the event loop stays responsive and the
                # proxy can flush; a longer breather every N frames caps the
                # burst rate for long snapshot replays.
                await asyncio.sleep(0)
                if i % SNAPSHOT_PACE_SLEEP_EVERY == 0:
                    await asyncio.sleep(SNAPSHOT_PACE_SLEEP_SECONDS)

            logger.debug(
                "websocket_reasoning_sent",
                session_id=session_id,
                count=len(new_entries),
                sent=len(frames_to_send),
                truncated=frames_to_send is not new_entries,
            )
            # Cursor tracks the true log length, not the capped send count —
            # this is what keeps live streaming gap/dup-free after a capped
            # snapshot: the next emit() only looks at entries appended past
            # the REAL length, never re-sending anything already truncated.
            self.last_log_index = len(reasoning_log)

        # Extract stage value from enum or string
        stage = state.get("current_stage", "")
        if hasattr(stage, "value"):
            stage = stage.value
        else:
            stage = str(stage) if stage else ""

        # Send status updates when status OR stage changes — or when the
        # autonomous-approval countdown appears/changes (R3): the injector
        # writes auto_approve_at AFTER the awaiting_approval transition, so an
        # already-connected client would otherwise never receive it.
        auto_approve_at = state.get("auto_approve_at") or None
        if (
            current_status != self.last_status
            or stage != self.last_stage
            or auto_approve_at != self.last_auto_approve_at
        ):
            status_data = {
                "status": current_status,
                "stage": stage,
                "awaiting_approval": state.get("awaiting_approval", False),
            }
            # Additive, optional: only present while a countdown is pending.
            if auto_approve_at:
                status_data["auto_approve_at"] = auto_approve_at
            await websocket.send_json({
                "type": "status",
                "session_id": session_id,
                "data": status_data,
            })
            logger.debug(
                "websocket_status_sent",
                session_id=session_id,
                status=current_status,
                stage=stage,
            )
            self.last_status = current_status
            self.last_stage = stage
            self.last_auto_approve_at = auto_approve_at

        # Send trade proposal when available (once)
        # proposal is now a dict after serialization fix
        #
        # Gated on current_status too (not just state.awaiting_approval): a
        # restart-stranded session can be reconciled back to a terminal or
        # running status while its state dict still carries a stale
        # awaiting_approval=True + trade_proposal from before the crash. A
        # reconnecting tab must not be told to approve a proposal that is no
        # longer actually pending.
        #
        # P3-3 (session-SSOT) audit: this AND was never a legacy-dict(B)-vs-
        # SessionManager(C) divergence guard (P3-1 deleted B; that class of
        # bug is gone), so it did not become dead weight when B was removed.
        # It guards a same-store gap inside SessionManager itself:
        # reconcile_stranded_sessions() (services/session_manager.py) does
        # NOT clear state["awaiting_approval"] on every terminal transition
        # it applies at startup -- the RUNNING+awaiting+prop branch that
        # flips to ERROR on a stale/unparked proposal, and the
        # AWAITING_APPROVAL branch that flips to CANCELLED off a recorded
        # approval_status=="cancelled", both leave the flag (and
        # trade_proposal) untouched while `status` moves to a terminal
        # value. Collapsing this to state.awaiting_approval alone would
        # re-advertise that stale proposal to a reconnecting tab. Keep both
        # conditions.
        if (
            state.get("trade_proposal")
            and state.get("awaiting_approval")
            and not self.proposal_sent
            and current_status == "awaiting_approval"
        ):
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
            self.proposal_sent = True
            logger.info(
                "websocket_proposal_sent",
                session_id=session_id,
                ticker=ticker_or_market,
                action=action,
            )

        # Send position updates only when the payload actually changes
        # (position is a dict after serialization)
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

            position_data = {
                "session_id": session_id,
                "ticker": str(position_ticker),
                "quantity": quantity,
                "entry_price": entry_price,
                "current_price": current_price,
                "pnl": round(float(pnl), 2),
                "pnl_percent": round(float(pnl_percent), 2),
            }
            if position_data != self.last_position:
                await websocket.send_json({
                    "type": "position",
                    "data": position_data,
                })
                self.last_position = position_data

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
            return True

        return False


@router.websocket("/session/{session_id}")
async def websocket_session(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time session updates.

    Push-first: subscribes to SessionManager pub/sub and treats notifications
    as wake signals (state is re-read from the session snapshot, so coalesced/
    dropped notifications never lose data). A slow poll (SAFETY_POLL_SECONDS)
    remains as the only fallback, covering sessions without sm pub/sub (failed
    sm registration) and producer writes that don't notify.

    Streams:
    - reasoning: New reasoning log entries
    - status: Status changes
    - proposal: Trade proposal when ready
    - position: Position updates (only when the position actually changes)
    - complete: Session completion

    Client can send:
    - "ping": Heartbeat (server responds with "pong")
    - "status": On-demand status frame
    """
    await manager.connect(session_id, websocket)

    sm = await get_session_manager()
    queue: Optional[asyncio.Queue] = None
    cursor = _SessionFrameCursor(session_id)
    recv_task: Optional[asyncio.Task] = None
    queue_task: Optional[asyncio.Task] = None

    try:
        logger.debug(
            "websocket_loop_started",
            session_id=session_id,
        )

        queue = await sm.subscribe(session_id)
        recv_task = asyncio.create_task(websocket.receive_text())
        queue_task = asyncio.create_task(queue.get())
        none_since: Optional[float] = None

        while True:
            session = await _get_session_snapshot(session_id)
            if session is not None:
                none_since = None
                if await cursor.emit(websocket, session):
                    # Keep connection open for a bit, then close
                    await asyncio.sleep(COMPLETE_LINGER_SECONDS)
                    break
            else:
                now = time.monotonic()
                if none_since is None:
                    none_since = now
                elif now - none_since >= NOT_FOUND_GRACE_SECONDS:
                    await websocket.send_json(
                        {"type": "not_found", "data": {"session_id": session_id}}
                    )
                    await websocket.close(code=WS_CLOSE_SESSION_NOT_FOUND)
                    break

            done, _pending = await asyncio.wait(
                {recv_task, queue_task},
                timeout=SAFETY_POLL_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if queue_task in done:
                # Notifications are wake signals only — drain any burst; the
                # next loop iteration re-reads the snapshot and the cursor
                # emits exactly the not-yet-sent frames.
                queue_task.result()
                while True:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                queue_task = asyncio.create_task(queue.get())

            if recv_task in done:
                data = recv_task.result()  # raises WebSocketDisconnect on close
                if data == "ping":
                    await websocket.send_text("pong")
                elif data == "status":
                    # On-demand status request
                    fresh = await _get_session_snapshot(session_id)
                    if fresh:
                        await websocket.send_json({
                            "type": "status",
                            "data": {
                                "session_id": session_id,
                                "status": fresh["status"],
                                "stage": str(fresh["state"].get("current_stage", "")),
                                "awaiting_approval": fresh["state"].get("awaiting_approval", False),
                            },
                        })
                recv_task = asyncio.create_task(websocket.receive_text())

    except WebSocketDisconnect:
        logger.info("websocket_client_disconnected", session_id=session_id)
    except Exception as e:
        logger.error(
            "websocket_error",
            session_id=session_id,
            error=str(e),
        )
    finally:
        for task in (recv_task, queue_task):
            if task is not None:
                task.cancel()
        if queue is not None:
            await sm.unsubscribe(session_id, queue)
        manager.disconnect(session_id, websocket)


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
# Trade Notification WebSocket
# -------------------------------------------


@router.websocket("/trade-notifications")
async def websocket_trade_notifications(websocket: WebSocket):
    """
    WebSocket endpoint for real-time trade execution notifications.

    Broadcasts:
    - trade_executed: Trade was executed (BUY/SELL)
    - trade_queued: Trade was queued for later execution
    - trade_rejected: Trade was rejected by user
    - watch_added: Stock was added to watch list
    - position_update: Position P&L update
    - stop_loss_triggered: Stop loss was hit
    - take_profit_triggered: Take profit was hit

    Client can send:
    - "ping": Heartbeat (server responds with "pong")
    """
    await trade_notification_manager.subscribe(websocket)

    try:
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connected",
            "message": "Trade notification subscription active",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        while True:
            try:
                # Wait for client message with timeout
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0,
                )

                if data == "ping":
                    await websocket.send_text("pong")

            except asyncio.TimeoutError:
                # Send heartbeat
                try:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception:
                    break

    except WebSocketDisconnect:
        logger.info("trade_notification_websocket_disconnected")
    except Exception as e:
        logger.error("trade_notification_websocket_error", error=str(e))
    finally:
        trade_notification_manager.unsubscribe(websocket)


# -------------------------------------------
# Trade Notification Broadcast Helpers
# -------------------------------------------


async def broadcast_trade_executed(
    ticker: str,
    stock_name: str,
    action: str,
    quantity: int,
    price: float,
    total_amount: float,
    session_id: str | None = None,
):
    """Broadcast trade execution notification to all subscribers."""
    await trade_notification_manager.broadcast({
        "type": "trade_executed",
        "data": {
            "ticker": ticker,
            "stock_name": stock_name,
            "action": action,
            "quantity": quantity,
            "price": price,
            "total_amount": total_amount,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    })
    logger.info(
        "trade_executed_broadcast",
        ticker=ticker,
        action=action,
        quantity=quantity,
    )


async def broadcast_trade_queued(
    ticker: str,
    stock_name: str,
    action: str,
    quantity: int,
    price: float,
    queue_position: int | None = None,
    expected_execution: str | None = None,
    session_id: str | None = None,
):
    """Broadcast trade queued notification to all subscribers."""
    await trade_notification_manager.broadcast({
        "type": "trade_queued",
        "data": {
            "ticker": ticker,
            "stock_name": stock_name,
            "action": action,
            "quantity": quantity,
            "price": price,
            "queue_position": queue_position,
            "expected_execution": expected_execution,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    })
    logger.info(
        "trade_queued_broadcast",
        ticker=ticker,
        action=action,
        queue_position=queue_position,
    )


async def broadcast_trade_rejected(
    ticker: str,
    stock_name: str,
    reason: str | None = None,
    session_id: str | None = None,
):
    """Broadcast trade rejection notification to all subscribers."""
    await trade_notification_manager.broadcast({
        "type": "trade_rejected",
        "data": {
            "ticker": ticker,
            "stock_name": stock_name,
            "reason": reason or "User rejected the proposal",
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    })
    logger.info(
        "trade_rejected_broadcast",
        ticker=ticker,
        reason=reason,
    )


async def broadcast_watch_added(
    ticker: str,
    stock_name: str,
    signal: str,
    confidence: float,
    current_price: float,
    session_id: str | None = None,
):
    """Broadcast watch list addition notification to all subscribers."""
    await trade_notification_manager.broadcast({
        "type": "watch_added",
        "data": {
            "ticker": ticker,
            "stock_name": stock_name,
            "signal": signal,
            "confidence": confidence,
            "current_price": current_price,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    })
    logger.info(
        "watch_added_broadcast",
        ticker=ticker,
        signal=signal,
    )


async def broadcast_position_event(
    event_type: str,  # "stop_loss_triggered" or "take_profit_triggered"
    ticker: str,
    stock_name: str,
    trigger_price: float,
    target_price: float,
    pnl: float | None = None,
    pnl_percent: float | None = None,
):
    """Broadcast position event (stop loss or take profit) to all subscribers."""
    await trade_notification_manager.broadcast({
        "type": event_type,
        "data": {
            "ticker": ticker,
            "stock_name": stock_name,
            "trigger_price": trigger_price,
            "target_price": target_price,
            "pnl": pnl,
            "pnl_percent": pnl_percent,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    })
    logger.info(
        f"{event_type}_broadcast",
        ticker=ticker,
        trigger_price=trigger_price,
    )


def _build_eod_summary_headline(digest: dict) -> str:
    """Compact one-line key-figures summary of an EOD digest, shared by the
    WS broadcast (below) and usable as a quick-glance FE fallback when
    `has_narrative` is False. Mirrors telegram/service.py's
    `_fmt_krw`/`_fmt_pct` number formatting so the WS headline and the
    Telegram key-figures header read the same way."""
    account = digest.get("account") or {}
    parts = []

    daily_pnl = account.get("daily_realized_pnl")
    if daily_pnl is not None:
        # Sign convention matches telegram/service.py::_fmt_krw exactly
        # (review fix: the two previously diverged on 0 -- _fmt_krw omits
        # the "+" for 0, this used to add it) -- "+" only for STRICTLY
        # positive values, never for 0.
        sign = "+" if daily_pnl > 0 else ""
        parts.append(f"당일 실현손익 {sign}{daily_pnl:,.0f}원")

    total_equity = account.get("total_equity")
    if total_equity is not None:
        parts.append(f"총평가 {total_equity:,.0f}원")

    regime = digest.get("regime") or {}
    if regime.get("label"):
        parts.append(f"시장 {regime['label']}")

    return " · ".join(parts) if parts else "데이터 없음"


async def broadcast_eod_summary(digest: dict, narrative: str | None = None):
    """E3-3: broadcast the day's EOD digest/narrative to trade-notification
    subscribers -- the FE consumes this (E3-5) to render/refresh an EOD
    summary panel without polling. Mirrors broadcast_trade_executed et
    al.'s TradeNotificationManager convention exactly: fire-and-forget over
    the existing manager (no-op if there are no subscribers), same
    type/data/timestamp shape.

    FE contract (data fields):
      - trade_date: str | None -- digest["trade_date"].
      - headline: str -- compact key-figures summary (see
        _build_eod_summary_headline above); always a non-empty string
        ("데이터 없음" when the digest carries no usable numbers).
      - has_narrative: bool -- whether an LLM narrative was generated for
        this day (narrate_eod_digest didn't return None/blank). The FULL
        digest/narrative body is intentionally NOT pushed over this
        broadcast (mirrors every other broadcast_* helper here staying
        summary-sized) -- a client wanting the full text fetches it via
        the EOD review report endpoint/storage.get_eod_reviews.
      - timestamp: str -- broadcast time (UTC ISO), not trade_date.
    """
    trade_date = digest.get("trade_date")
    headline = _build_eod_summary_headline(digest)

    await trade_notification_manager.broadcast({
        "type": "eod_summary",
        "data": {
            "trade_date": trade_date,
            "headline": headline,
            "has_narrative": bool(narrative and narrative.strip()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    })
    logger.info(
        "eod_summary_broadcast",
        trade_date=trade_date,
        has_narrative=bool(narrative and narrative.strip()),
    )
