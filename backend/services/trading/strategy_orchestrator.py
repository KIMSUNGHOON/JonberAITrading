"""Phase 3: strategy consensus orchestrator — the market-close chain step
AFTER run_eod_review (services/trading/coordinator.py market-close edge):

  1. build_strategy_context — today's eod_review + regime/perf/calibration
     ledgers (skip the whole run if there's no meaningful review).
  2. run_strategy_panel — 3 structured LLM votes, bounded by
     STRATEGY_CONSENSUS_TIMEOUT_SECONDS (asyncio.wait_for owned HERE so the
     coordinator edge stays a one-line call).
  3. aggregate_stance / apply_consensus — corrected consensus math +
     deterministic knob application (strategy_consensus.py).
  4. Persist a strategy_revisions row + move the
     'strategy:active_revision_id' pointer + coordinator.set_strategy.

Pointer invariant: the pointed revision's strategy_json is ALWAYS the
strategy currently in effect — restore (coordinator._restore_strategy)
never guesses. Hence: no-change WITH a current strategy still writes an
audit row (changed=0, same content) and moves the pointer; no-change with
NO current strategy writes nothing (a pointer to a never-applied strategy
would lie to restore).

Failure-harmless like every EOD step (eod_orchestrator.run_eod_review):
the whole body is one try/except -> logger.warning -> result dict with
ok=False. This runs off the LIVE scheduler tick and must never break it.
Tactical consumption of the applied strategy is Phase 4 — until then the
output is deliberately dormant.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional
from uuid import uuid4

from app.config import get_settings

from .strategy import TradingStrategy
from .strategy_consensus import (
    aggregate_stance,
    apply_consensus,
    semantic_fingerprint,
    valid_votes,
)
from .strategy_panel import build_strategy_context, run_strategy_panel

logger = logging.getLogger(__name__)

ACTIVE_STRATEGY_REVISION_KEY = "strategy:active_revision_id"


def _result(ok: bool, reason: Optional[str] = None, **extra) -> dict:
    base = {
        "ok": ok, "reason": reason, "revision_id": None,
        "stance": None, "consensus_level": None, "changed": None,
    }
    base.update(extra)
    return base


def _current_knobs(strategy: Optional[TradingStrategy]) -> dict:
    if strategy is None:
        strategy = TradingStrategy()
    return {
        "risk_tolerance": strategy.risk_tolerance.value,
        "max_position_pct": strategy.position_sizing.max_position_pct,
        "min_cash_ratio": strategy.position_sizing.min_cash_ratio,
        "max_positions": strategy.position_sizing.max_positions,
        "stop_loss_pct": strategy.exit_conditions.stop_loss_pct,
        "take_profit_pct": strategy.exit_conditions.take_profit_pct,
        "max_trade_notional_pct": strategy.position_sizing.max_trade_notional_pct,
    }


def _rationale(stance: str, consensus_level: float, votes: list[dict]) -> str:
    parts = [f"[{stance}] 합의 {consensus_level:.2f}"]
    for vote in valid_votes(votes):
        reasoning = str(vote.get("reasoning") or "")[:200]
        parts.append(f"{vote.get('panelist')}: {reasoning}")
    errors = [v for v in votes if isinstance(v, dict) and v.get("error")]
    for err in errors:
        parts.append(f"{err.get('panelist')}: (실패 — 배제)")
    return " / ".join(parts)


async def run_strategy_consensus(
    coordinator: Any, storage: Any, trade_date: str, *, force: bool = False
) -> dict:
    """Run the EOD strategy consensus for `trade_date`. Never raises.

    Args:
        coordinator: ExecutionCoordinator (or compatible) — only
            .get_strategy()/.set_strategy() are used; NOT imported to avoid
            the circular import (same convention as eod_orchestrator).
        storage: StorageService (or compatible).
        trade_date: "YYYY-MM-DD".
        force: bypass the STRATEGY_CONSENSUS_ENABLED gate (manual API runs).
    """
    try:
        settings = get_settings()
        if not force and not settings.STRATEGY_CONSENSUS_ENABLED:
            return _result(False, "disabled")

        current = coordinator.get_strategy()
        context = await build_strategy_context(
            storage, trade_date, _current_knobs(current)
        )
        if context is None:
            return _result(False, "no_context")

        try:
            votes = await asyncio.wait_for(
                run_strategy_panel(context),
                timeout=settings.STRATEGY_CONSENSUS_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"[StrategyConsensus] panel timed out for {trade_date} "
                f"({settings.STRATEGY_CONSENSUS_TIMEOUT_SECONDS}s)"
            )
            return _result(False, "timeout")

        # Re-read: a manual POST/PUT/DELETE /strategy landing mid-panel-await
        # would otherwise leave `current` stale, making the revision write +
        # pointer move below describe a strategy no longer in effect (restore
        # would then revert/resurrect it). This shrinks that race window from
        # the panel's up-to-STRATEGY_CONSENSUS_TIMEOUT_SECONDS (≤420s) await
        # down to microseconds.
        current = coordinator.get_strategy()

        stance_result = aggregate_stance(
            votes,
            min_valid=settings.STRATEGY_MIN_VALID_VOTES,
            threshold=settings.STRATEGY_CONSENSUS_THRESHOLD,
        )
        stance = stance_result["stance"]
        consensus_level = stance_result["consensus_level"]
        revision_id = str(uuid4())
        regime_snapshot_id = (context.get("eod_review") or {}).get("regime", {}).get(
            "regime_snapshot_id"
        )
        parent_id = await storage.get_app_setting(ACTIVE_STRATEGY_REVISION_KEY)

        if stance == "no_change":
            if current is None:
                # 적용된 적 없는 전략을 가리키는 포인터를 만들지 않는다.
                logger.info(
                    f"[StrategyConsensus] no consensus and no current strategy "
                    f"for {trade_date} — skipping"
                )
                return _result(False, "no_consensus_no_current",
                               stance=stance, consensus_level=consensus_level)
            new_strategy, changed = current, False
        else:
            baseline = current if current is not None else TradingStrategy()
            new_strategy = apply_consensus(
                baseline, votes, stance, consensus_level, trade_date, revision_id
            )
            changed = semantic_fingerprint(new_strategy) != semantic_fingerprint(baseline)

        record = {
            "id": revision_id,
            "trade_date": trade_date,
            "source": "eod_consensus",
            "stance": stance,
            "consensus_level": consensus_level,
            "changed": 1 if changed else 0,
            "strategy_json": new_strategy.model_dump_json(),
            "parent_revision_id": parent_id or None,
            "rationale": _rationale(stance, consensus_level, votes),
            "votes_json": json.dumps(votes, ensure_ascii=False, default=str),
            "regime_snapshot_id": regime_snapshot_id,
        }
        if not await storage.save_strategy_revision(record):
            return _result(False, "persist_failed",
                           stance=stance, consensus_level=consensus_level)
        await storage.set_app_setting(ACTIVE_STRATEGY_REVISION_KEY, revision_id)

        if stance != "no_change":
            coordinator.set_strategy(new_strategy)

        logger.info(
            f"[StrategyConsensus] {trade_date}: stance={stance} "
            f"consensus={consensus_level:.2f} changed={changed} rev={revision_id}"
        )
        return _result(True, None, revision_id=revision_id, stance=stance,
                       consensus_level=consensus_level, changed=changed)
    except Exception as e:
        logger.warning(
            f"[StrategyConsensus] run failed for {trade_date}: {e}"
        )
        return _result(False, str(e))
