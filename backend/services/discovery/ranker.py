"""
Discovery Regime-Weighted Ranker + LLM Structured Review + Conservative
Promotion Gate (DS-4).

Pipeline (spec Section 3, this module owns the last three of four EOD-chain
sub-steps — the scan itself is DS-2):

    rank_candidates()   -- load today's discovery scan (DS-2 factor_json) +
                            today's regime label -> per-strategy weighted
                            composite score -> sorted Candidate list.
    llm_review_top()    -- top-N candidates only get an LLM suitability
                            verdict (JSON-only prompt, never-raise).
    promote_candidates() -- apply every gate from spec Section 5 in order,
                            call `coordinator.add_to_watch_list(source=
                            'discovery')` for survivors, and persist the
                            FULL candidate batch (promoted AND skipped AND
                            quality-filter-excluded) to the DS-3 ledger
                            (`storage.save_discovery_candidates`).

This module never calls Kiwoom, never writes scan_results/scan_sessions (DS-2
owns that schema) -- it only *reads* the scanner's sqlite db (aiosqlite,
read-only, mirrors services/trading/regime.py's cross-db read precedent) and
reads/writes storage.db via the injected `storage` (a StorageService
instance) and `coordinator` (an ExecutionCoordinator instance).

Fail-closed posture: any gate ambiguity (missing verdict, corrupt weights,
missing regime snapshot, cooldown-lookup failure) resolves to "do not
promote", never to a silent default-approve. LLM/network errors during
`llm_review_top` never raise -- a failed review is recorded as
skip_reason='llm_parse_failed' and the candidate is gated out downstream.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import aiosqlite
import structlog

from agents.llm_provider import get_llm_provider
from services.discovery.factors import STRATEGIES

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Regime weight matrix (spec Section 2) -- seeded into app_settings on first
# read, then the persisted copy is authoritative (an EOD strategy-consensus
# panel is a later arc's extension point; this arc only reads).
# ---------------------------------------------------------------------------

REGIME_WEIGHTS_SETTING_KEY = "discovery:regime_weights"

DEFAULT_REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "bullish": {
        "momentum": 0.40, "pullback": 0.25, "flow": 0.25, "meanrev": 0.10,
        "threshold": 0.55, "daily_cap": 5,
    },
    "neutral": {
        "flow": 0.30, "pullback": 0.30, "momentum": 0.20, "meanrev": 0.20,
        "threshold": 0.55, "daily_cap": 5,
    },
    "bearish": {
        "flow": 0.35, "meanrev": 0.35, "pullback": 0.20, "momentum": 0.10,
        "threshold": 0.65, "daily_cap": 2,
    },
}

# Watch-list total cap (spec Section 5) -- enforced regardless of regime.
WATCH_TOTAL_CAP = 30

# Re-promotion cooldown, in calendar days (spec Section 5).
COOLDOWN_DAYS = 7


# ---------------------------------------------------------------------------
# Candidate -- the unit that flows through rank -> llm_review -> promote.
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    """One ticker's discovery-ranking row. Quality-filter-excluded rows
    (composite is None) still carry enough to be ledger-recorded, they just
    never enter the gate loop in `promote_candidates`."""

    ticker: str
    name: Optional[str]
    trade_date: str
    regime_label: str
    threshold: float
    daily_cap: int
    weights: dict[str, float]
    universe_fallback: bool
    quality_filter_passed: bool
    raw_scores: Optional[dict[str, float]] = None
    composite: Optional[float] = None
    rank: Optional[int] = None
    close_price: Optional[float] = None
    skip_reason: Optional[str] = None
    llm_verdict: Optional[dict[str, Any]] = None
    promoted: bool = False


@dataclass
class PromoteSummary:
    """Return value of `promote_candidates` -- a thin audit trail on top of
    the mutations already applied to each `Candidate` in place."""

    trade_date: Optional[str]
    total_candidates: int
    promoted: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Regime weights: load-or-seed
# ---------------------------------------------------------------------------


async def _load_regime_weights(storage) -> dict[str, dict[str, float]]:
    """Read `discovery:regime_weights` from app_settings; seed it with
    `DEFAULT_REGIME_WEIGHTS` (JSON) if the key doesn't exist yet. A corrupt
    (non-JSON / non-dict / empty) stored value falls back to the in-memory
    default rather than raising -- this gate must never crash the EOD chain
    over a hand-edited settings row."""
    raw = await storage.get_app_setting(REGIME_WEIGHTS_SETTING_KEY)
    if raw is None:
        seed = copy.deepcopy(DEFAULT_REGIME_WEIGHTS)
        await storage.set_app_setting(
            REGIME_WEIGHTS_SETTING_KEY, json.dumps(seed, ensure_ascii=False)
        )
        return seed

    try:
        loaded = json.loads(raw)
        if not isinstance(loaded, dict) or not loaded:
            raise ValueError("regime weights JSON is not a non-empty object")
        return loaded
    except (TypeError, ValueError) as e:
        logger.warning(
            "discovery_regime_weights_corrupt_using_default", error=str(e)
        )
        return copy.deepcopy(DEFAULT_REGIME_WEIGHTS)


def _extract_regime_label(
    snapshot: Optional[dict[str, Any]], weights_cfg: dict[str, dict]
) -> str:
    """market_sentiment_label -> regime_label -> 'neutral' fallback chain
    (spec Section 2). A label that doesn't match a key in the (possibly
    hand-edited) weights config also falls back to 'neutral' rather than
    KeyError-ing the caller."""
    label = None
    if snapshot is not None:
        label = snapshot.get("market_sentiment_label") or snapshot.get("regime_label")
    if not label or label not in weights_cfg:
        return "neutral"
    return label


async def _get_regime_snapshot_for_date(
    storage, trade_date: str
) -> Optional[dict[str, Any]]:
    """Today's regime_snapshot row, if any (newest first, so the first
    trade_date match is the latest one recorded for that day -- accretion
    style, mirrors regime_snapshot's own storage convention). Any storage
    error is swallowed -- absence of a snapshot is a normal 'neutral
    fallback' case, not a hard failure."""
    try:
        snapshots = await storage.get_regime_snapshots(limit=500)
    except Exception as e:
        logger.warning("discovery_regime_snapshot_lookup_failed", error=str(e))
        return None
    for snap in snapshots:
        if snap.get("trade_date") == trade_date:
            return snap
    return None


# ---------------------------------------------------------------------------
# Scanner DB reads (aiosqlite direct, mirrors services/trading/regime.py's
# cross-db read precedent -- scanner_results.db is a separate file this
# module never writes to).
# ---------------------------------------------------------------------------


async def _load_discovery_session(
    scanner_db_path, trade_date: str
) -> Optional[dict[str, Any]]:
    """Latest completed-or-partial (SC-1) scan_mode='discovery' session for
    `trade_date`, or None if no such session exists yet (scan didn't run /
    hasn't finished/stopped). A 'partial' row (stopped before covering the
    whole universe -- see scanner.py's stop_scan) is treated the same as
    'completed' so a timed-out scan's collected tickers still get ranked
    instead of the whole day's session being discarded."""
    async with aiosqlite.connect(str(scanner_db_path)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM scan_sessions
            WHERE status IN ('completed', 'partial') AND scan_mode = 'discovery'
              AND date(started_at) = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (trade_date,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def _load_scan_results(scanner_db_path, session_id: str) -> list[dict[str, Any]]:
    """All scan_results rows for `session_id` (stk_cd/stk_nm/factor_json)."""
    async with aiosqlite.connect(str(scanner_db_path)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT stk_cd, stk_nm, factor_json FROM scan_results "
            "WHERE scan_session_id = ?",
            (session_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# rank_candidates
# ---------------------------------------------------------------------------


async def rank_candidates(storage, scanner_db_path, trade_date: str) -> list[Candidate]:
    """Load today's discovery scan + regime label, compute the regime-weighted
    composite score per ticker, and return a Candidate list.

    Ordering: quality-filter-passed candidates first, sorted by composite
    descending with `rank` assigned 1..N; quality-filter-excluded candidates
    (composite=None, rank=None) follow, unranked but still returned so the
    caller can ledger-record them (spec: "품질 필터 탈락 행은 랭킹 제외하되
    원장 기록 대상"). Returns [] if no completed-or-partial (SC-1) discovery
    session exists yet for `trade_date` (nothing to rank).
    """
    weights_cfg = await _load_regime_weights(storage)

    session = await _load_discovery_session(scanner_db_path, trade_date)
    if session is None:
        return []

    universe_fallback = bool(session.get("universe_fallback"))

    snapshot = await _get_regime_snapshot_for_date(storage, trade_date)
    regime_label = _extract_regime_label(snapshot, weights_cfg)
    regime_cfg = weights_cfg.get(regime_label) or DEFAULT_REGIME_WEIGHTS["neutral"]

    strategy_weights = {
        k: float(regime_cfg.get(k, 0.0)) for k in STRATEGIES
    }
    threshold = float(
        regime_cfg.get("threshold", DEFAULT_REGIME_WEIGHTS["neutral"]["threshold"])
    )
    daily_cap = int(
        regime_cfg.get("daily_cap", DEFAULT_REGIME_WEIGHTS["neutral"]["daily_cap"])
    )

    rows = await _load_scan_results(scanner_db_path, session["id"])

    ranked: list[Candidate] = []
    excluded: list[Candidate] = []

    for row in rows:
        ticker = row.get("stk_cd")
        name = row.get("stk_nm")
        raw_json = row.get("factor_json")

        factor: Optional[dict[str, Any]] = None
        if raw_json:
            try:
                factor = json.loads(raw_json)
            except (TypeError, ValueError):
                factor = None

        common = dict(
            ticker=ticker,
            name=name,
            trade_date=trade_date,
            regime_label=regime_label,
            threshold=threshold,
            daily_cap=daily_cap,
            weights=dict(strategy_weights),
            universe_fallback=universe_fallback,
        )

        if not factor or not factor.get("quality_filter_passed"):
            reason = (factor or {}).get("skip_reason") or "missing_factor_json"
            excluded.append(
                Candidate(
                    **common,
                    quality_filter_passed=False,
                    skip_reason=reason,
                )
            )
            continue

        scores = factor.get("scores") or {}
        raw_scores = {k: float(scores.get(k) or 0.0) for k in STRATEGIES}
        composite = sum(raw_scores[k] * strategy_weights[k] for k in STRATEGIES)

        ranked.append(
            Candidate(
                **common,
                quality_filter_passed=True,
                raw_scores=raw_scores,
                composite=composite,
                close_price=factor.get("close_price"),
            )
        )

    ranked.sort(key=lambda c: c.composite, reverse=True)
    for idx, c in enumerate(ranked, start=1):
        c.rank = idx

    return ranked + excluded


# ---------------------------------------------------------------------------
# llm_review_top
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = (
    "당신은 보수적인 한국 주식 발굴 스크리너의 최종 검토자다. 아래 정량 팩터 "
    "요약만 근거로 이 종목이 신규 관심종목(워치리스트) 등록 후보로 적합한지 "
    "판단하라. 확실하지 않으면 반려하라(suitable=false).\n\n"
    "반드시 아래 JSON 스키마 하나만 출력하라 — 그 외 텍스트, 설명, 마크다운, "
    "코드펜스는 절대 포함하지 마라:\n"
    '{"suitable": <bool>, "confidence": <0.0~1.0 사이 숫자>, '
    '"rationale": "<한 줄 근거>", "risks": "<한 줄 리스크>"}'
)


def _build_llm_messages(candidate: Candidate) -> list:
    from langchain_core.messages import HumanMessage, SystemMessage

    scores = candidate.raw_scores or {}
    composite = candidate.composite if candidate.composite is not None else 0.0
    user_prompt = (
        f"종목: {candidate.name or candidate.ticker}({candidate.ticker})\n"
        f"레짐: {candidate.regime_label}\n"
        f"레짐가중 종합점수: {composite:.4f} (문턱 {candidate.threshold:.2f})\n"
        f"전략별 원점수(0~1): momentum={scores.get('momentum', 0.0):.3f}, "
        f"pullback={scores.get('pullback', 0.0):.3f}, "
        f"flow={scores.get('flow', 0.0):.3f}, "
        f"meanrev={scores.get('meanrev', 0.0):.3f}\n"
        f"종가: {candidate.close_price}\n"
        f"발굴 랭킹: #{candidate.rank}\n"
    )
    return [
        SystemMessage(content=_LLM_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]


def _strip_code_fence(text: str) -> str:
    """Tolerate a markdown code fence wrapping the JSON (```json ... ``` or
    ``` ... ```) -- NOT a prefix-parsing/regex-extraction fallback (that's
    explicitly forbidden by the global constraints). Anything else that isn't
    already-valid JSON stays untouched and fails json.loads downstream."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_llm_verdict(raw: Any) -> Optional[dict[str, Any]]:
    """json.loads only (plus the markdown-fence concession above) -- a
    malformed/non-JSON/non-object response, or a response missing a boolean
    'suitable' key, is treated as a parse failure (returns None). Never
    raises."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        parsed = json.loads(_strip_code_fence(raw))
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    if not isinstance(parsed.get("suitable"), bool):
        return None
    return parsed


async def llm_review_top(candidates: list[Candidate], top_n: int = 25) -> None:
    """Send the top `top_n` quality-passed candidates (by rank) to the LLM
    for a structured suitability verdict, mutating each Candidate's
    `llm_verdict` (dict on success, None otherwise) and `skip_reason`
    ('llm_parse_failed' on a malformed response or an LLM/network exception)
    in place. Candidates beyond `top_n`, and quality-filter-excluded ones
    (composite is None), are left untouched -- their `llm_verdict` stays
    None, which `promote_candidates` treats as "not suitable" downstream.

    Never raises -- an LLM exception for one candidate is logged and treated
    identically to a parse failure; it never aborts the review of the rest.
    """
    reviewable = [c for c in candidates if c.composite is not None]
    reviewable.sort(key=lambda c: c.rank if c.rank is not None else 10**9)
    top = reviewable[:top_n]

    if not top:
        return None

    provider = get_llm_provider()

    for c in top:
        try:
            raw = await provider.generate(_build_llm_messages(c), task="discovery")
        except Exception as e:
            logger.warning("discovery_llm_review_exception", ticker=c.ticker, error=str(e))
            c.llm_verdict = None
            c.skip_reason = "llm_parse_failed"
            continue

        verdict = _parse_llm_verdict(raw)
        if verdict is None:
            logger.warning("discovery_llm_review_parse_failed", ticker=c.ticker)
            c.llm_verdict = None
            c.skip_reason = "llm_parse_failed"
        else:
            c.llm_verdict = verdict

    return None


# ---------------------------------------------------------------------------
# promote_candidates
# ---------------------------------------------------------------------------


def _parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


async def _cooldown_blocked(storage, ticker: str, trade_date: str) -> bool:
    """True if `ticker` was promoted within the last `COOLDOWN_DAYS` calendar
    days (strictly before `trade_date`) per the discovery_candidates ledger.
    A storage error fails OPEN here on purpose -- a lookup failure blocking
    promotion would silently starve the whole pipeline, and the ledger write
    at the end of `promote_candidates` still records this candidate's fate,
    so nothing is lost; the other gates (threshold/LLM/dedup/caps) remain in
    force regardless."""
    try:
        rows = await storage.get_discovery_candidates(ticker=ticker, limit=50)
    except Exception as e:
        logger.warning("discovery_cooldown_lookup_failed", ticker=ticker, error=str(e))
        return False

    today = _parse_date(trade_date)
    for row in rows:
        if not row.get("promoted"):
            continue
        row_trade_date = row.get("trade_date")
        if not row_trade_date:
            continue
        try:
            row_date = _parse_date(row_trade_date)
        except ValueError:
            continue
        delta_days = (today - row_date).days
        if 0 <= delta_days < COOLDOWN_DAYS:
            return True
    return False


def _evict_worst_discovery_watch(coordinator) -> bool:
    """Remove the lowest-confidence `source == 'discovery'` ACTIVE watch
    entry to free a cap slot. Returns False (nothing evicted) if every active
    entry is manual -- manual entries are never touched."""
    active = coordinator.get_watch_list()
    discovery_entries = [
        w for w in active if getattr(w, "source", "manual") == "discovery"
    ]
    if not discovery_entries:
        return False
    worst = min(discovery_entries, key=lambda w: w.confidence)
    return coordinator.remove_discovery_watch(worst.ticker)


def _ensure_watch_room(coordinator, cap: int = WATCH_TOTAL_CAP) -> bool:
    """True if there's room for one more watch-list entry under `cap`,
    evicting the worst discovery entry first if the list is already at cap.
    False if at cap and nothing evictable (all manual) -- promotion must be
    skipped."""
    if len(coordinator.get_watch_list()) < cap:
        return True
    return _evict_worst_discovery_watch(coordinator)


def _resolve_exit_pcts(coordinator) -> tuple[float, float]:
    """(stop_loss_pct, take_profit_pct) as FRACTIONS (e.g. 0.045 == 4.5%) for
    discovery-promoted watch entries (P2-D1/E-1).

    Source of truth is the active strategy's `exit_conditions`
    (already fraction-scaled, ExitConditions.stop_loss_pct/take_profit_pct).
    No active strategy (`get_strategy()` returns None) or a lookup failure
    both fall back to `coordinator.risk_params`' account-level defaults
    (`default_stop_loss_pct`/`default_take_profit_pct`) -- those are stored
    as PERCENTAGE POINTS (e.g. 8.0 == 8%), so they're divided by 100 here to
    match ExitConditions' fraction convention. This mirrors
    `_detect_opportunity`'s best-effort strategy-lookup pattern in
    services/agent_chat/coordinator.py -- a strategy-access hiccup degrades
    to the pre-existing account default, it never blocks promotion."""
    try:
        strategy = coordinator.get_strategy()
        if strategy is not None:
            return (
                strategy.exit_conditions.stop_loss_pct,
                strategy.exit_conditions.take_profit_pct,
            )
    except Exception as e:
        logger.warning("discovery_strategy_lookup_failed", error=str(e))

    risk_params = coordinator.risk_params
    return (
        risk_params.default_stop_loss_pct / 100.0,
        risk_params.default_take_profit_pct / 100.0,
    )


def _candidate_summary_text(c: Candidate) -> str:
    return (
        f"발굴 랭킹 #{c.rank} · 레짐={c.regime_label} · "
        f"종합점수={c.composite:.3f}(문턱 {c.threshold:.2f})"
    )


def _candidate_key_factors(c: Candidate) -> list[str]:
    return [f"{k}={v:.2f}" for k, v in (c.raw_scores or {}).items()]


async def _persist_ledger(storage, candidates: list[Candidate]) -> None:
    """Write the FULL candidate batch (promoted, gated-out, and
    quality-filter-excluded alike) to the DS-3 ledger in one batch call.
    strategy_scores_json carries the RAW (un-weighted) 4-strategy scores plus
    the regime weights actually applied, under a separate '_weights' key
    (DS-3 review carryover: raw scores drive strategy-tag performance
    grouping in services/discovery/ledger.py::_top_strategy_tag, which only
    picks up numeric values and so silently ignores '_weights')."""
    if not candidates:
        return

    rows = []
    for c in candidates:
        scores_payload: dict[str, Any] = dict(c.raw_scores) if c.raw_scores else {}
        scores_payload["_weights"] = dict(c.weights) if c.weights else {}
        rows.append(
            {
                "trade_date": c.trade_date,
                "ticker": c.ticker,
                "name": c.name,
                "composite_score": c.composite,
                "strategy_scores_json": scores_payload,
                "regime_label": c.regime_label,
                "rank": c.rank,
                "llm_verdict_json": c.llm_verdict,
                "promoted": 1 if c.promoted else 0,
                "skip_reason": c.skip_reason,
                "close_price": c.close_price,
            }
        )

    try:
        await storage.save_discovery_candidates(rows)
    except Exception as e:
        logger.error("discovery_ledger_persist_failed", error=str(e))


async def promote_candidates(coordinator, storage, candidates: list[Candidate]) -> PromoteSummary:
    """Apply every conservative gate (spec Section 5) in order, promote
    survivors into `coordinator`'s watch list (`source='discovery'`), and
    persist the full batch to the DS-3 ledger.

    Gate order (fixed, do not reorder):
        1. universe_fallback session -> skip ALL candidates outright.
        2. composite >= regime threshold.
        3. LLM verdict.suitable == True (never-reviewed / parse-failed ->
           not suitable).
        4. Cooldown: not promoted again within COOLDOWN_DAYS.
        5. Not already held (coordinator.state.positions) or already an
           ACTIVE watch entry.
        6. Regime daily cap (this call's own promotion count so far).
        7. Watch-list total cap (WATCH_TOTAL_CAP), evicting the worst
           discovery-sourced entry first; skip if nothing evictable.

    Every candidate ends this call with a final `skip_reason` (None only for
    ones actually promoted) and `promoted` flag, which is what gets written
    to the ledger.
    """
    trade_date = candidates[0].trade_date if candidates else None
    summary = PromoteSummary(trade_date=trade_date, total_candidates=len(candidates))

    if not candidates:
        return summary

    if any(c.universe_fallback for c in candidates):
        for c in candidates:
            c.skip_reason = "universe_fallback"
            c.promoted = False
            summary.skipped[c.ticker] = "universe_fallback"
        await _persist_ledger(storage, candidates)
        return summary

    eligible = sorted(
        (c for c in candidates if c.composite is not None),
        key=lambda c: c.rank if c.rank is not None else 10**9,
    )

    held_tickers = {p.ticker for p in coordinator.state.positions}
    daily_promoted = 0
    stop_pct, tp_pct = _resolve_exit_pcts(coordinator)

    for c in eligible:
        if c.composite < c.threshold:
            c.skip_reason = "below_threshold"
            summary.skipped[c.ticker] = c.skip_reason
            continue

        if c.llm_verdict is None or not c.llm_verdict.get("suitable"):
            # DS-4 리뷰 이월(DS-5): top_n 밖이라 llm_review_top이 아예 손대지
            # 않은 후보(llm_verdict is None, skip_reason은 아직 None)는
            # "LLM이 부적합 판정했다"(llm_not_suitable)가 아니라 "애초에
            # 검토조차 안 됐다"(not_reviewed)로 구분 기록한다 — 파싱 실패
            # (llm_parse_failed)와도 다른, 별개의 원장 사유.
            if c.skip_reason == "llm_parse_failed":
                reason = "llm_parse_failed"
            elif c.llm_verdict is None:
                reason = "not_reviewed"
            else:
                reason = "llm_not_suitable"
            c.skip_reason = reason
            summary.skipped[c.ticker] = reason
            continue

        if await _cooldown_blocked(storage, c.ticker, c.trade_date):
            c.skip_reason = "cooldown"
            summary.skipped[c.ticker] = c.skip_reason
            continue

        current_watch_tickers = {w.ticker for w in coordinator.get_watch_list()}
        if c.ticker in held_tickers or c.ticker in current_watch_tickers:
            c.skip_reason = "already_held_or_watched"
            summary.skipped[c.ticker] = c.skip_reason
            continue

        if daily_promoted >= c.daily_cap:
            c.skip_reason = "daily_cap"
            summary.skipped[c.ticker] = c.skip_reason
            continue

        if not _ensure_watch_room(coordinator):
            c.skip_reason = "watch_cap"
            summary.skipped[c.ticker] = c.skip_reason
            continue

        # P2-D1/E-1: seed target/stop/take from the discovery close price so
        # _detect_opportunity's price-proximity branch (services/agent_chat/
        # coordinator.py) can actually fire on this entry -- previously all
        # three were omitted (None), which silently starved discovery
        # promotions of any entry-price signal and left them dependent on
        # the (much stricter) high-confidence-only fallback branch.
        target_entry_price: Optional[float] = None
        stop_loss: Optional[float] = None
        take_profit: Optional[float] = None
        if c.close_price:
            target_entry_price = c.close_price
            stop_loss = c.close_price * (1 - stop_pct)
            take_profit = c.close_price * (1 + tp_pct)

        coordinator.add_to_watch_list(
            session_id=f"discovery:{c.trade_date}",
            ticker=c.ticker,
            stock_name=c.name,
            signal="discovery",
            confidence=c.composite,
            current_price=c.close_price or 0.0,
            target_entry_price=target_entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            analysis_summary=_candidate_summary_text(c),
            key_factors=_candidate_key_factors(c),
            source="discovery",
        )
        logger.info(
            "discovery_candidate_promoted",
            ticker=c.ticker,
            target_entry_price=target_entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=c.composite,
        )
        c.skip_reason = None
        c.promoted = True
        summary.promoted.append(c.ticker)
        daily_promoted += 1

    await _persist_ledger(storage, candidates)
    return summary
