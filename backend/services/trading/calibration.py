"""Phase 2 Task 1: per-agent calibration + decision outcome labeling.

Phase 1 backfills `outcome_realized_pnl` onto the ENTRY decision once its
position is matched-closed (see `storage_service.update_decision_outcome`,
wired from the `kr_realized_pnl` close path — the coin close path this used
to also feed from was removed with the rest of the Upbit stack, 2026-08-01)
but leaves `outcome_label` nullable and never scores which agent's vote was
actually right. Without
that, Phase 3's adaptive strategy re-weighting has no data to re-weight
against.

This is pure aggregation over the durable Phase-1 ledger — NO LLM. It:
1. Reads every decision with a non-null `outcome_realized_pnl` (a "closed"
   decision) within the trailing `window_days` window ending `as_of_date`.
2. Labels each one `correct` / `incorrect` / `flat` and backfills that onto
   the decision row (`update_decision_label`).
3. Reads that decision's backing votes and scores each non-abstain,
   non-moderator vote's direction against the actual outcome.
4. Aggregates hits per `agent_type` and persists one `agent_calibration`
   snapshot row per agent (`save_agent_calibration`).

Failure-harmless by design, mirroring `eod_snapshot.write_daily_snapshot`:
a storage hiccup must never break whatever EOD job calls this. Per-decision
and per-vote failures are logged and skipped (partial results still get
scored/persisted) rather than aborting the whole run; any unexpected
top-level failure returns `{}` rather than raising.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# vote -> direction (mirrors services/agent_chat/models.py's
# calculate_consensus/get_majority_direction bullish/bearish grouping).
_BULLISH_VOTES = {"strong_buy", "buy"}
_BEARISH_VOTES = {"strong_sell", "sell"}
_NEUTRAL_VOTES = {"hold"}
# abstain (no opinion expressed) and moderator (doesn't vote at all — see
# calculate_consensus's `if vote.agent_type == AgentType.MODERATOR: continue`)
# are excluded entirely: neither counts toward decisions_scored nor
# accuracy for any agent.
_EXCLUDED_AGENT_TYPES = {"moderator"}

# Upper bound on how many recent decisions we scan for outcome_realized_pnl
# NOT NULL rows within the window. Mirrors eod_snapshot.py's
# _KR_REALIZED_PNL_SCAN_LIMIT scan-then-filter-in-Python pattern —
# get_agent_chat_decisions has no date-range query parameter.
_DECISION_SCAN_LIMIT = 1000


def _decision_label(outcome_realized_pnl: float, flat_threshold: float) -> str:
    """Label a single closed decision's outcome.

    `flat` if the realized P&L sits within `flat_threshold` of zero either
    direction; otherwise `correct` for a profit, `incorrect` for a loss.
    Outcomes are backfilled by Phase 1 onto the ENTRY decision only, so this
    is always judged on an entry (BUY/ADD) basis even though the row that
    triggered the backfill was the matching exit.

    입력이 이제 net이므로(2026-08-08: 수수료 + 매도 증권거래세를 뺀 값이
    `outcome_realized_pnl`로 백필된다 — trade_log.record_kr_realized_pnl_async)
    이 문턱(EOD_FLAT_THRESHOLD_KRW)에 남은 역할은 "너무 작아서 신호가
    아니다" 하나뿐이다. 비용이 아니라 **잡음 대역**이며, 여기에 비용을 또
    얹으면 이중 계상이다.
    """
    if abs(outcome_realized_pnl) < flat_threshold:
        return "flat"
    return "correct" if outcome_realized_pnl > 0 else "incorrect"


def _vote_direction(vote: Optional[str]) -> Optional[str]:
    """Map a raw vote string to bullish/bearish/neutral, or None to exclude
    (abstain or unrecognized)."""
    if not vote:
        return None
    v = vote.lower()
    if v in _BULLISH_VOTES:
        return "bullish"
    if v in _BEARISH_VOTES:
        return "bearish"
    if v in _NEUTRAL_VOTES:
        return "neutral"
    return None


def _vote_hit(direction: str, label: str, outcome_realized_pnl: float) -> bool:
    """Did this agent's vote direction match the decision's actual outcome?

    Note bullish/bearish hits are judged against the raw P&L sign (not the
    `flat`/`correct`/`incorrect` label) — a bullish vote on a `flat`-labeled
    decision still "hits" if the tiny residual P&L happened to be positive.
    Only the neutral (hold) case is judged against the label directly.
    """
    if direction == "bullish":
        return outcome_realized_pnl > 0
    if direction == "bearish":
        return outcome_realized_pnl < 0
    if direction == "neutral":
        return label == "flat"
    return False


def _within_window(trade_date: Optional[str], as_of, cutoff) -> bool:
    """True if trade_date falls in [cutoff, as_of].

    A missing/unparseable trade_date is included (fail-open) rather than
    silently dropped — decision_log.py always sets it in practice, but a
    metadata gap must never be the reason real outcome data goes unscored.
    """
    if not trade_date:
        return True
    try:
        d = datetime.strptime(str(trade_date)[:10], "%Y-%m-%d").date()
    except ValueError:
        return True
    return cutoff <= d <= as_of


async def label_and_calibrate(
    storage: Any, as_of_date: str, window_days: int = 30
) -> dict[str, Any]:
    """Label every closed decision's outcome and recompute per-agent
    calibration (accuracy/avg_confidence) over the trailing window.

    Args:
        storage: StorageService (or compatible) — reads
            get_agent_chat_decisions/get_agent_chat_votes, writes
            update_decision_label/save_agent_calibration.
        as_of_date: "YYYY-MM-DD", the EOD review date this calibration run
            is attributed to (persisted on each agent_calibration row).
        window_days: trailing lookback window in days (inclusive of
            as_of_date), measured against each decision's trade_date.

    Returns:
        {"as_of_date", "window_days", "decisions_scored",
         "per_agent_accuracy": {agent_type: {"decisions_scored", "correct",
         "accuracy", "avg_confidence"}}}. Best-effort: on total failure (or
         an unparseable as_of_date) returns `{}` rather than raising — this
         must never break an EOD job.
    """
    try:
        as_of = datetime.strptime(as_of_date, "%Y-%m-%d").date()
        cutoff = as_of - timedelta(days=window_days)
        flat_threshold = get_settings().EOD_FLAT_THRESHOLD_KRW

        try:
            decisions = await storage.get_agent_chat_decisions(
                limit=_DECISION_SCAN_LIMIT
            )
        except Exception as e:
            logger.warning(f"[Calibration] Failed to read decisions: {e}")
            return {}

        # agent_type -> {"correct": int, "scored": int, "confidences": [float]}
        agent_stats: dict[str, dict[str, Any]] = {}
        decisions_scored = 0

        for d in decisions:
            outcome = d.get("outcome_realized_pnl")
            if outcome is None:
                continue
            if not _within_window(d.get("trade_date"), as_of, cutoff):
                continue

            decision_id = d.get("id")
            outcome = float(outcome)
            label = _decision_label(outcome, flat_threshold)

            try:
                await storage.update_decision_label(decision_id, label)
            except Exception as e:
                logger.warning(
                    f"[Calibration] update_decision_label failed for "
                    f"{decision_id}: {e}"
                )
                continue  # don't score a decision we couldn't label

            decisions_scored += 1

            try:
                votes = await storage.get_agent_chat_votes(decision_id)
            except Exception as e:
                logger.warning(
                    f"[Calibration] get_agent_chat_votes failed for "
                    f"{decision_id}: {e}"
                )
                continue

            for v in votes:
                agent_type = v.get("agent_type")
                if not agent_type or agent_type in _EXCLUDED_AGENT_TYPES:
                    continue
                direction = _vote_direction(v.get("vote"))
                if direction is None:
                    continue

                stats = agent_stats.setdefault(
                    agent_type, {"correct": 0, "scored": 0, "confidences": []}
                )
                stats["scored"] += 1
                if _vote_hit(direction, label, outcome):
                    stats["correct"] += 1
                confidence = v.get("confidence")
                if confidence is not None:
                    stats["confidences"].append(float(confidence))

        per_agent_accuracy: dict[str, dict[str, Any]] = {}
        for agent_type, stats in agent_stats.items():
            scored = stats["scored"]
            accuracy = (stats["correct"] / scored) if scored else 0.0
            confidences = stats["confidences"]
            avg_confidence = (
                (sum(confidences) / len(confidences)) if confidences else None
            )

            record = {
                "id": str(uuid.uuid4()),
                "agent_type": agent_type,
                "as_of_date": as_of_date,
                "window_days": window_days,
                "decisions_scored": scored,
                "correct": stats["correct"],
                "accuracy": accuracy,
                "avg_confidence": avg_confidence,
            }
            try:
                await storage.save_agent_calibration(record)
            except Exception as e:
                logger.warning(
                    f"[Calibration] save_agent_calibration failed for "
                    f"{agent_type}: {e}"
                )
                continue

            per_agent_accuracy[agent_type] = {
                "decisions_scored": scored,
                "correct": stats["correct"],
                "accuracy": accuracy,
                "avg_confidence": avg_confidence,
            }

        return {
            "as_of_date": as_of_date,
            "window_days": window_days,
            "decisions_scored": decisions_scored,
            "per_agent_accuracy": per_agent_accuracy,
        }
    except Exception as e:
        logger.warning(f"[Calibration] label_and_calibrate failed for {as_of_date}: {e}")
        return {}
