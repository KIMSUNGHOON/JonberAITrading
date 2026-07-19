"""persist_analysis_decision — durable ledger row for LangGraph analysis-path
decisions.

L1 (decision lineage restoration, 2026-07-19, spec D1): agent_chat_decisions
was the only durable per-decision table, written solely by the agent-chat
debate path. The LangGraph analysis/execution path (KR graph approval ->
order placement) never wrote a durable decision row at all, so
kr_stock_trades.decision_id came out 100% NULL for every graph-approved
trade -- the session it was decided in is SessionManager/checkpoint state,
subject to GC (P5), so it is a dangling pointer rather than a durable
lineage anchor.

This module promotes agent_chat_decisions to the single durable ledger for
BOTH paths: `decision_source` distinguishes 'agent_chat' (existing rows,
left NULL -- see storage_service.get_agent_chat_decisions' COALESCE
fallback) from 'analysis' (written here). `session_ref` keeps the
originating session id for traceability even after that session itself is
GC'd or expires -- this row is what survives it.

L2 calls `persist_analysis_decision` from the graph execution node just
before order placement, threading its returned id into
kr_stock_trades.decision_id / ManagedPosition.analysis_session_id the same
way the agent-chat path's session.id already does. Per spec D5 (hot-path
harmlessness), this is best-effort: a ledger-write failure must never block
order placement, so this function never raises -- it logs a warning and
returns None, and L2's caller proceeds with decision_id=None (today's status
quo, not a regression).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

# I3 (final-review fix): fixed UTC+9 offset -- mirrors
# app/api/routes/trading.py's own `KST = timezone(timedelta(hours=9))`
# (that module's `trade_date = request.date or datetime.now(KST).strftime(
# "%Y-%m-%d")` is the existing repo convention this follows), not pytz's
# Asia/Seoul (services/trading/market_hours.py) -- no DST in KST, so the
# fixed offset is exact and avoids the extra dependency here.
_KST = timezone(timedelta(hours=9))


def _trade_date_kst_today() -> str:
    """KST 'today' as "%Y-%m-%d" -- the exact format
    `calibration._within_window` parses and `app/api/routes/trading.py`'s
    trade_date default already produces. A tiny seam (not inlined into
    `persist_analysis_decision` below) so tests can monkeypatch a specific
    date without needing to time-travel the real clock."""
    return datetime.now(_KST).strftime("%Y-%m-%d")


async def persist_analysis_decision(
    storage: Any,
    *,
    session_id: str,
    ticker: str,
    action: str,
    confidence: Optional[float],
    rationale: Optional[str],
    stock_name: Optional[str] = None,
) -> Optional[str]:
    """Persist a compact decision row for a LangGraph analysis-path decision.

    Reuses `StorageService.save_agent_chat_decision` (the existing
    agent_chat_decisions writer) rather than a bespoke INSERT, so this row
    shares that table's schema/indexes/read paths exactly -- tagged
    `decision_source='analysis'` and `session_ref=session_id`. No votes are
    attached (the analysis path has no per-agent vote records), which is
    also what lets calibration's per-agent aggregation (a votes join)
    naturally skip these rows without any source-based guard.

    Args:
        storage: StorageService (or compatible) — must expose
            `save_agent_chat_decision(decision, votes) -> bool`.
        session_id: the originating LangGraph/SessionManager session id,
            stored as `session_ref` for traceability after that session is
            GC'd.
        ticker: stock code the decision concerns.
        action: the decided action (e.g. "BUY"/"SELL"/"ADD"/"REDUCE").
        confidence: decision confidence, if available.
        rationale: free-text rationale, if available.
        stock_name: optional display name (e.g. "삼성전자") — threaded
            through when the caller has it in scope; None keeps existing
            callers byte-for-byte unchanged.

    Returns:
        The new decision id (a fresh uuid4 str) on success, else None. Never
        raises -- any storage exception, or `save_agent_chat_decision`
        returning False, is logged as a warning and swallowed.
    """
    decision_id = str(uuid.uuid4())
    try:
        decision = {
            "id": decision_id,
            "ticker": ticker,
            "stock_name": stock_name,
            # I3 (final-review fix): was never set (always NULL) before this
            # fix -- calibration._within_window fail-opens on a missing
            # trade_date (always included), so every analysis decision
            # silently bypassed `window_days` regardless of staleness.
            "trade_date": _trade_date_kst_today(),
            "status": "decided",
            "action": action,
            "confidence": confidence,
            "rationale": rationale,
            "decision_source": "analysis",
            "session_ref": session_id,
        }
        ok = await storage.save_agent_chat_decision(decision, [])
    except Exception as e:
        logger.warning(
            "analysis_decision_persist_error",
            session_id=session_id,
            ticker=ticker,
            action=action,
            error=str(e),
        )
        return None

    if not ok:
        logger.warning(
            "analysis_decision_persist_failed",
            session_id=session_id,
            ticker=ticker,
            action=action,
        )
        return None

    return decision_id
