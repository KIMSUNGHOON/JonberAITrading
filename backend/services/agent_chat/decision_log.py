"""
Decision Log — durable persistence for completed agent-chat ChatSessions.

Phase1 data-foundation, C1/C4: a finished ChatSession (decision + votes +
sentiment/behavioral context) used to live only in the coordinator's
in-memory `_session_history` list and evaporated on restart. This module
serializes a completed session into the `agent_chat_decisions` /
`agent_chat_votes` shape Task 1's `StorageService.save_agent_chat_decision`
expects, and wires that write behind a failure-harmless helper the
coordinator calls at every append site (auto watch-list discussions AND
manual /discuss discussions — the `on_session_complete` callback path has
zero production registrants and the manual path never fires it, so direct
calls are the only way to cover both).
"""

from typing import Any, Optional

import structlog

from services.agent_chat.models import ChatSession
from services.storage_service import get_storage_service

logger = structlog.get_logger()


def _extract_behavioral(indicators: Optional[dict]) -> dict:
    """Extract {volume_ratio, trend, cross, rsi} from an `indicators` dict
    that may come in either of two shapes:

      - FLAT (agents.tools.kr_market_data.calculate_kr_technical_indicators):
        top-level `volume_ratio` / `cross` / `rsi` / `trend` (a string like
        "bullish").
      - NESTED (services.../technical_indicators.calculate_all): `volume.ratio`
        / `momentum.rsi` / `trend.direction` (a dict with a `direction` key).

    Flat keys win when present; a missing value (in either shape) becomes
    None. `cross` has no nested equivalent, so it's flat-only. `indicators`
    being None/empty yields all-None.
    """
    result: dict = {"volume_ratio": None, "trend": None, "cross": None, "rsi": None}
    if not indicators:
        return result

    volume_ratio = indicators.get("volume_ratio")
    if volume_ratio is None:
        volume = indicators.get("volume")
        if isinstance(volume, dict):
            volume_ratio = volume.get("ratio")
    result["volume_ratio"] = volume_ratio

    trend = indicators.get("trend")
    if isinstance(trend, dict):
        trend = trend.get("direction")
    result["trend"] = trend

    result["cross"] = indicators.get("cross")

    rsi = indicators.get("rsi")
    if rsi is None:
        momentum = indicators.get("momentum")
        if isinstance(momentum, dict):
            rsi = momentum.get("rsi")
    result["rsi"] = rsi

    return result


def serialize_session(
    session: ChatSession,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Pure serializer: ChatSession -> (decision dict, list of vote dicts).

    No I/O. When `session.decision` is None (the session ended without a
    decision — e.g. cancelled/timeout), `action` is hardcoded to "NO_ACTION"
    and the decision-derived fields (confidence/rationale/dissenting_opinions/
    entry_price/stop_loss/take_profit/position_pct) are all None;
    `consensus_level` still falls back to the session's own field.
    """
    decision = session.decision

    if decision is not None:
        action = decision.action.value
        confidence = decision.confidence
        consensus_level = decision.consensus_level
        rationale = decision.rationale
        dissenting_opinions = decision.dissenting_opinions
        entry_price = decision.entry_price
        stop_loss = decision.stop_loss
        take_profit = decision.take_profit
        position_pct = decision.position_pct
    else:
        action = "NO_ACTION"
        confidence = None
        consensus_level = session.consensus_level
        rationale = None
        dissenting_opinions = None
        entry_price = None
        stop_loss = None
        take_profit = None
        position_pct = None

    trade_date_source = session.ended_at or session.created_at
    trade_date = (
        trade_date_source.strftime("%Y-%m-%d") if trade_date_source else None
    )

    context = session.context
    news_sentiment = context.news_sentiment if context else None
    news_count = context.news_count if context else None
    behavioral_signals = _extract_behavioral(context.indicators if context else None)

    dec: dict[str, Any] = {
        "id": session.id,
        "ticker": session.ticker,
        "stock_name": session.stock_name,
        "trade_date": trade_date,
        "status": session.status.value,
        "action": action,
        "confidence": confidence,
        "consensus_level": consensus_level,
        "rationale": rationale,
        "dissenting_opinions": dissenting_opinions,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "position_pct": position_pct,
        "news_sentiment": news_sentiment,
        "news_count": news_count,
        "behavioral_signals": behavioral_signals,
        "market_sentiment": None,
        "flow": None,
        "regime_snapshot_id": None,
        "outcome_realized_pnl": None,
        "outcome_label": None,
        # Phase4: provenance — the consensus weights actually used to reach
        # this decision (None = legacy DEFAULT_AGENT_WEIGHTS, no calibration
        # tilt was active). save_agent_chat_decision JSON-serializes this the
        # same way it does dissenting_opinions/behavioral_signals/etc.
        "agent_weights": session.agent_weights,
    }

    votes: list[dict[str, Any]] = [
        {
            "decision_id": session.id,
            "agent_type": v.agent_type.value,
            "vote": v.vote.value,
            "confidence": v.confidence,
            "reasoning": v.reasoning,
            "key_factors": v.key_factors,
            "suggested_position_pct": v.suggested_position_pct,
            "suggested_stop_loss_pct": v.suggested_stop_loss_pct,
            "suggested_take_profit_pct": v.suggested_take_profit_pct,
        }
        for v in session.votes
    ]

    return dec, votes


async def persist_session(session: ChatSession) -> None:
    """Persist a completed ChatSession to durable storage.

    Failure-harmless by design: a storage outage (or any unexpected session
    shape) must never break the discussion flow that's calling this right
    after appending to `_session_history` — so every failure is caught and
    logged, never raised.
    """
    try:
        storage = await get_storage_service()
        decision, votes = serialize_session(session)
        await storage.save_agent_chat_decision(decision, votes)
    except Exception as e:
        logger.warning(
            "agent_chat_session_persist_failed",
            session_id=getattr(session, "id", None),
            error=str(e),
        )
