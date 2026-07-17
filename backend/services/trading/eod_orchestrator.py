"""Phase 2 Task 4: EOD orchestrator — wires Tasks 1-3 (regime snapshot,
per-agent calibration, EOD review) into ONE market-close run, and backfills
the `regime_snapshot_id` FK that Phase1/Task2 left nullable onto both
`daily_perf_snapshot` and that day's `agent_chat_decisions`.

`run_eod_review` is the single entry point the LIVE trading coordinator's
market-close edge calls
(services/trading/coordinator.py::_check_queue_on_market_open, immediately
after `.eod_snapshot.write_daily_snapshot` — this MUST run after that row
exists since `build_eod_review` reads `daily_perf_snapshot`). Steps 1-3
are pure/rule-based (no LLM); E3-2 added ONE LLM call (step 4,
`narrate_eod_digest`) — see that step's note below for why an inline,
never-raise, timeout-bounded await is safe here.

Steps, in order:
  1. `compute_regime_snapshot` (pure, SYNCHRONOUS stdlib-sqlite3 — run off
     the event loop thread via `asyncio.to_thread` so a slow/locked scanner
     db never blocks it) against the background scanner's own db
     (`regime.SCANNER_DB_PATH`), then persist it via `save_regime_snapshot`.
  2. `label_and_calibrate` — labels every closed decision's outcome and
     recomputes per-agent calibration over the trailing window.
  3. `build_eod_review` — assembles the day's portfolio/per-stock/agent/
     regime sections.
  4. E3-2: `build_eod_digest` (watch/account/holdings/strategy/regime,
     itself failure-harmless — see eod_digest.py) then
     `narrate_eod_digest(digest)` (LLM, never-raise, up to 120s via
     `asyncio.wait_for` — see eod_digest.py's own docstring for why this
     is safe to await inline here rather than split into a second save/
     UPDATE step: `run_eod_review`'s only caller,
     coordinator.py::_check_queue_on_market_open, awaits this from a
     30s-interval scheduler tick with NO surrounding timeout of its own,
     and this call fires at most once/day at market close when no new
     fills are expected — a slow/timed-out LLM delays that one tick's
     `_poll_tracked_fills`/`reconcile` by at most 120s, once a day, never
     drops them). Both `digest` and `narrative` (None on failure) are
     merged into the SAME `review` dict as new keys before the single
     existing `save_eod_review` call below — report_json's SCHEMA is
     unchanged (still one JSON blob via INSERT OR REPLACE), only its
     CONTENT grows two keys. Every pre-existing key/step is untouched.
  5. `save_eod_review` — persists the (now digest/narrative-augmented)
     report.
  6. `backfill_regime_id` — attaches the freshly-saved regime_snapshot_id
     onto `daily_perf_snapshot` + `agent_chat_decisions` for `trade_date`.

Failure-harmless by design, mirroring every other Phase1/Phase2 EOD step
(`eod_snapshot.write_daily_snapshot`/`calibration.label_and_calibrate`/
`eod_review.build_eod_review`): the WHOLE body is one try/except ->
logger.warning -> return False. This runs off the LIVE market-close
scheduler tick and must never break it. `build_eod_digest`/
`narrate_eod_digest` are each independently never-raise too (defense in
depth — see their own docstrings), so a digest/LLM failure degrades only
`report["digest"]`/`report["narrative"]` to None/None, never the rest of
`report` or this function's own True/False contract.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.config import get_settings

from .calibration import label_and_calibrate
from .eod_digest import build_eod_digest, narrate_eod_digest
from .eod_review import build_eod_review
from .market_data import fetch_index_snapshot, fetch_market_flow
from .regime import SCANNER_DB_PATH, compute_regime_snapshot, compute_market_regime

logger = logging.getLogger(__name__)


async def run_eod_review(coordinator: Any, storage: Any, trade_date: str) -> bool:
    """Run the full EOD review chain for `trade_date`, off the market-close
    edge: regime snapshot -> per-agent calibration -> EOD review report ->
    regime FK backfill.

    Args:
        coordinator: ExecutionCoordinator (or compatible) — passed through
            to `build_eod_review` for its synchronous
            `.get_portfolio_summary()`.
        storage: StorageService (or compatible) — reads/writes the
            Phase1/Phase2 ledger tables only.
        trade_date: "YYYY-MM-DD" — the day this EOD review is attributed to.

    Returns:
        True if the chain completed. False on ANY failure (never raises) —
        this runs off the live scheduler tick and must never break it.
    """
    try:
        snap = await asyncio.to_thread(
            compute_regime_snapshot, SCANNER_DB_PATH, trade_date
        )
        # Phase 5: 지수·수급 심화 (실패-무해, 핫패스 무관 EOD 1회)
        # PHASE5_MARKET_DATA_ENABLED=False = 진짜 킬스위치(레거시 breadth만 저장,
        # compute_market_regime 자체를 호출하지 않음 — C6).
        settings = get_settings()
        if settings.PHASE5_MARKET_DATA_ENABLED:
            index = flow = None
            kiwoom = getattr(coordinator, "_kiwoom", None)
            if kiwoom is not None:
                try:
                    index = await fetch_index_snapshot(kiwoom)
                    flow = await fetch_market_flow(kiwoom)
                except Exception as e:
                    logger.warning(f"[EODOrchestrator] market-data enrich failed: {e}")
            enriched = compute_market_regime(
                snap, index, flow, trade_date, settings.PHASE5_SENTIMENT_THRESHOLD
            )
        else:
            enriched = snap
        rid = None
        if enriched:
            await storage.save_regime_snapshot(enriched)
            rid = enriched["id"]

        await label_and_calibrate(storage, trade_date)

        review = await build_eod_review(storage, coordinator, trade_date, rid)

        # E3-2: LLM 내러티브 + digest 병합 저장 (기존 review 키·순서·
        # failure-harmless 무변경 — 실패 시 각각 None으로 저장, 체인 진행).
        digest = await build_eod_digest(
            coordinator=coordinator, storage=storage, trade_date=trade_date
        )
        review["digest"] = digest
        review["narrative"] = await narrate_eod_digest(digest)

        await storage.save_eod_review(
            {"trade_date": trade_date, "report_json": json.dumps(review)}
        )

        if rid:
            await storage.backfill_regime_id(trade_date, rid)
            if enriched and enriched.get("market_sentiment_label"):
                sentiment_json = json.dumps({
                    "label": enriched.get("market_sentiment_label"),
                    "score": enriched.get("sentiment_score"),
                })
                flow_json = json.dumps({
                    "foreign_net_amount": enriched.get("foreign_net_amount"),
                    "institution_net_amount": enriched.get("institution_net_amount"),
                })
                await storage.backfill_market_context(
                    trade_date, sentiment_json, flow_json
                )

        return True
    except Exception as e:
        logger.warning(
            f"[EODOrchestrator] run_eod_review failed for {trade_date}: {e}"
        )
        return False
