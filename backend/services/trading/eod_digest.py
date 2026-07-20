"""Phase E3 Task 1: eod_digest 조립기 (aggregation, NO LLM) + Task E3-2:
narrate_eod_digest (the module's one deliberate LLM call — see below).

The end-of-day digest joins four otherwise-siloed live/durable sources into
ONE dict that downstream tasks treat as a fixed contract: E3-2's LLM
narrative reads it as the source-of-truth for a Korean briefing, E3-3's
Telegram template and E3-5's FE render both render its sections
verbatim. DS-5 added a 6th (`discovery`).
See docs/superpowers/specs/2026-07-17-three-issues-design.md §3 (Task
E3-1/T6) and docs/superpowers/plans/2026-07-17-three-issues.md's Task E3-1
for the authoritative schema this module implements.

Sources:
  - `coordinator.get_watch_list()` (sync — `services/trading/coordinator.
    py::ExecutionCoordinator.get_watch_list`) → `watch`.
  - `coordinator.get_portfolio_summary()` (sync) → `account`'s deposit/
    total_equity and `holdings`' quantity/avg_price/current_price/
    unrealized P&L.
  - `coordinator.state.positions` (sync property, `List[ManagedPosition]`)
    → best-effort enrichment of `holdings[].stop_loss`/`take_profit`, which
    `get_portfolio_summary()`'s dict does not carry. This is an optional
    read: a coordinator stand-in that only implements the two methods
    above (no `.state`) still assembles holdings fine — stop_loss/
    take_profit just degrade to None per position.
  - `storage.get_daily_perf_snapshots()` (async, scan-then-match on
    trade_date — no server-side date filter, mirrors eod_review.py's own
    idiom) → `account`'s daily_realized_pnl/cumulative_return_pct. Per
    spec §3: today's trades/P&L come from this ledger ONLY — never
    aggregate kr_stock_trades directly here (that table is raw fills, not
    the reconciled daily figure; see the spec's explicit warning).
  - `storage.get_strategy_revisions(limit=1)` (async, already sorted
    `created_at DESC`) → `strategy`, the single latest revision regardless
    of trade_date (it represents "the strategy currently in force", which
    may predate `trade_date` if today's EOD consensus hasn't run yet).
  - `storage.get_regime_snapshots(limit=1)` (async, same "true latest"
    idiom) → `regime`.

Failure-harmless by design, mirroring eod_review.build_eod_review: each
section is built by its own independently try/except-guarded helper, so
one broken/missing source degrades only that section (to None or []),
never the whole digest. The whole body is additionally wrapped so a truly
unexpected failure still returns a dict shaped exactly like the happy path
(all 6 keys present, degraded to None/[]) rather than raising or omitting
keys — every consumer can rely on the 6 keys always existing.

E3-2 adds `narrate_eod_digest(digest) -> Optional[str]` to this same
module: a Korean LLM briefing generated FROM the digest this module
builds. It reuses the shared LLM router exactly like strategy_panel.py's
plain-text call convention (`get_llm_provider().generate(...)`), but with
`TaskType.GENERAL` since this is free-text narration, not a structured
decision. Never-raise like every other function here: any exception,
`asyncio.wait_for` timeout, or blank response returns None, and per
E3-D2 every consumer (Telegram/FE) falls back to a deterministic template
render when narrate returns None.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from agents.llm.tasks import TaskType
from agents.llm_provider import get_llm_provider
from services.discovery.ledger import _top_strategy_tag

logger = logging.getLogger(__name__)

# E3-2: LLM 내러티브 호출 상한 — 느린/멈춘 백엔드가 EOD 체인을 무한정 붙잡지
# 않도록 asyncio.wait_for로 강제 상한. 테스트가 monkeypatch로 낮춰 wait_for
# 배선 자체를 검증한다.
_NARRATE_TIMEOUT_SECONDS = 120.0

# Upper bound on how many recent daily_perf_snapshot rows we scan to find
# trade_date's row in Python — there's no server-side date filter on
# get_daily_perf_snapshots. Mirrors eod_review.py's
# _DAILY_PERF_SNAPSHOT_SCAN_LIMIT.
_DAILY_PERF_SNAPSHOT_SCAN_LIMIT = 60

# strategy/regime sections want the single TRUE latest row (not scoped to
# trade_date — see module docstring), and both getters already return
# newest-first, so limit=1 is sufficient.
_LATEST_ROW_LIMIT = 1

# rationale is free-form Korean text (can run to several KB); the digest
# only ever needs a short excerpt for a briefing.
_RATIONALE_EXCERPT_CHARS = 300

# DS-5: today's discovery_candidates rows are queried exact-scoped
# (trade_date=trade_date) with a generous limit mirroring
# ledger.backfill_forward_returns/get_discovery_performance's own
# limit=5000 idiom -- a single day's full-universe discovery sweep can
# ledger-record ~2,500 rows (promoted AND skipped AND quality-excluded
# alike, see ranker.promote_candidates), so this must cover one whole
# day, not just the promoted handful.
_DISCOVERY_TODAY_LIMIT = 5000

# "어제 후보" (the most recent trade_date strictly before today) is found
# by scanning the newest rows and bucketing by trade_date -- a scan-then-
# match idiom (mirrors _DAILY_PERF_SNAPSHOT_SCAN_LIMIT above), not an
# exact previous-trading-day lookup (which would need krx_holiday, a
# dependency this module deliberately stays free of). Best-effort: if a
# day's universe exceeds this window the prev-day summary may under-count,
# acceptable for an informational digest section, not the ledger itself.
_DISCOVERY_RECENT_SCAN_LIMIT = 6000

_EMPTY_ACCOUNT: dict[str, Any] = {
    "deposit": None,
    "total_equity": None,
    "daily_realized_pnl": None,
    "cumulative_return_pct": None,
}


async def build_eod_digest(
    *, coordinator: Any, storage: Any, trade_date: str
) -> dict[str, Any]:
    """Assemble the end-of-day digest for `trade_date`.

    NOTE: keyword-only (the leading `*`) is deliberate -- `coordinator`/
    `storage` are both duck-typed `Any` with no structural type to catch a
    transposed call at import/type-check time. Before this fix, a
    positional-argument swap (`build_eod_digest(storage, coordinator,
    trade_date)`) would silently degrade EVERY section to empty/None
    (each section's own try/except swallows the resulting AttributeError)
    rather than raising -- i.e. a caller bug produces a quietly-corrupted
    but structurally valid digest instead of a loud failure. Keyword-only
    turns that swap into an immediate `TypeError` at the call site.

    Args:
        coordinator: ExecutionCoordinator (or any stand-in exposing
            synchronous `.get_watch_list()`/`.get_portfolio_summary()`,
            and optionally `.state.positions`).
        storage: StorageService (or compatible) — reads
            get_daily_perf_snapshots/get_strategy_revisions/
            get_regime_snapshots/get_discovery_candidates. Never writes.
        trade_date: "YYYY-MM-DD" — the day this digest is attributed to
            (scopes the `account` and `discovery` sections; `strategy`/
            `regime` are each the single latest row regardless of date).

    Returns:
        {"trade_date", "watch": [...], "account": {...}, "holdings": [...],
        "strategy": {...} | None, "regime": {...} | None,
        "discovery": {...} | None}. Failure-harmless: a broken/missing
        individual source degrades only its section (to None or []); this
        function itself never raises. NOTE (DS-5): at the time
        run_eod_review's own build_eod_digest call actually runs (this
        module's usual caller), `discovery` will typically still show
        YESTERDAY's/no data — the coordinator's discovery post-processing
        (services/discovery/orchestrator.py::run_discovery_pipeline) only
        runs LATER in the same market-close tick, after run_eod_review.
        _notify_eod_summary (coordinator.py, the chain's true last step)
        re-fetches just this section afterward and patches the persisted
        row, mirroring the same freshness fix already in place for
        `strategy` (see that function's "Important 1" docstring note).
    """
    try:
        watch = _build_watch_section(coordinator)
        account = await _build_account_section(coordinator, storage, trade_date)
        holdings = _build_holdings_section(coordinator)
        strategy = await _build_strategy_section(storage)
        regime = await _build_regime_section(storage)
        discovery = await _build_discovery_section(storage, trade_date)

        return {
            "trade_date": trade_date,
            "watch": watch,
            "account": account,
            "holdings": holdings,
            "strategy": strategy,
            "regime": regime,
            "discovery": discovery,
        }
    except Exception as e:
        # Each section builder above is already independently
        # try/except-guarded, so this branch should be unreachable in
        # practice — it exists purely as defense-in-depth so the contract
        # ("always a dict with all 6 keys") holds even against a bug in
        # the assembly code itself, not just in a data source.
        logger.warning(f"[EODDigest] build_eod_digest failed for {trade_date}: {e}")
        return {
            "trade_date": trade_date,
            "watch": [],
            "account": dict(_EMPTY_ACCOUNT),
            "holdings": [],
            "strategy": None,
            "regime": None,
            "discovery": None,
            "error": str(e),
        }


def _build_watch_section(coordinator: Any) -> list[dict[str, Any]]:
    try:
        watch_list = coordinator.get_watch_list()
    except Exception as e:
        logger.warning(f"[EODDigest] coordinator.get_watch_list failed: {e}")
        return []

    result = []
    for w in watch_list or []:
        try:
            current_price = getattr(w, "current_price", None)
            target_entry_price = getattr(w, "target_entry_price", None)
            result.append(
                {
                    "ticker": getattr(w, "ticker", None),
                    "stock_name": getattr(w, "stock_name", None),
                    "signal": getattr(w, "signal", None),
                    "confidence": getattr(w, "confidence", None),
                    "current_price": current_price,
                    "target_entry_price": target_entry_price,
                    "gap_pct": _gap_pct(current_price, target_entry_price),
                }
            )
        except Exception as e:
            logger.warning(f"[EODDigest] watch item skipped: {e}")
    return result


def _gap_pct(current_price: Any, target_entry_price: Any) -> Optional[float]:
    if current_price is None or not target_entry_price:
        return None
    try:
        return (current_price - target_entry_price) / target_entry_price * 100
    except (TypeError, ZeroDivisionError):
        return None


async def _build_account_section(
    coordinator: Any, storage: Any, trade_date: str
) -> dict[str, Any]:
    deposit = None
    total_equity = None
    try:
        summary = coordinator.get_portfolio_summary()
        deposit = summary.get("cash")
        total_equity = summary.get("total_equity")
    except Exception as e:
        logger.warning(f"[EODDigest] coordinator.get_portfolio_summary failed: {e}")

    daily_realized_pnl = None
    cumulative_return_pct = None
    try:
        snapshots = await storage.get_daily_perf_snapshots(
            limit=_DAILY_PERF_SNAPSHOT_SCAN_LIMIT
        )
        for row in snapshots:
            if row.get("trade_date") == trade_date:
                daily_realized_pnl = row.get("realized_pnl")
                cumulative_return_pct = row.get("cumulative_return_pct")
                break
    except Exception as e:
        logger.warning(f"[EODDigest] get_daily_perf_snapshots failed: {e}")

    return {
        "deposit": deposit,
        "total_equity": total_equity,
        "daily_realized_pnl": daily_realized_pnl,
        "cumulative_return_pct": cumulative_return_pct,
    }


def _build_holdings_section(coordinator: Any) -> list[dict[str, Any]]:
    try:
        summary = coordinator.get_portfolio_summary()
        positions = summary.get("positions") or []
    except Exception as e:
        logger.warning(f"[EODDigest] coordinator.get_portfolio_summary failed: {e}")
        return []

    # Best-effort stop_loss/take_profit enrichment: get_portfolio_summary's
    # dict doesn't carry these two fields (portfolio_agent.py deliberately
    # omits them), but coordinator.state.positions (ManagedPosition) has
    # them. Optional read — any failure (missing `.state`, malformed
    # position, etc.) just leaves the lookup empty so every holding falls
    # back to stop_loss/take_profit = None rather than raising.
    stops_by_ticker: dict[Any, tuple[Any, Any]] = {}
    try:
        for p in coordinator.state.positions:
            stops_by_ticker[p.ticker] = (
                getattr(p, "stop_loss", None),
                getattr(p, "take_profit", None),
            )
    except Exception as e:
        logger.debug(f"[EODDigest] coordinator.state.positions unavailable: {e}")

    holdings = []
    for p in positions:
        try:
            ticker = p.get("ticker")
            stop_loss, take_profit = stops_by_ticker.get(ticker, (None, None))
            holdings.append(
                {
                    "ticker": ticker,
                    "stock_name": p.get("stock_name"),
                    "quantity": p.get("quantity"),
                    "avg_price": p.get("avg_price"),
                    "current_price": p.get("current_price"),
                    "unrealized_pnl": p.get("unrealized_pnl"),
                    "unrealized_pnl_pct": p.get("unrealized_pnl_pct"),
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                }
            )
        except Exception as e:
            logger.warning(f"[EODDigest] holding entry skipped: {e}")
    return holdings


async def _build_strategy_section(storage: Any) -> Optional[dict[str, Any]]:
    try:
        rows = await storage.get_strategy_revisions(limit=_LATEST_ROW_LIMIT)
    except Exception as e:
        logger.warning(f"[EODDigest] get_strategy_revisions failed: {e}")
        return None
    if not rows:
        return None

    row = rows[0]
    rationale = row.get("rationale") or ""
    key_knobs = {
        "stop_loss_pct": None,
        "take_profit_pct": None,
        "max_position_pct": None,
        "max_trade_notional_pct": None,
    }
    try:
        strategy_json = row.get("strategy_json")
        if strategy_json:
            parsed = json.loads(strategy_json)
            exit_conditions = parsed.get("exit_conditions") or {}
            position_sizing = parsed.get("position_sizing") or {}
            key_knobs = {
                "stop_loss_pct": exit_conditions.get("stop_loss_pct"),
                "take_profit_pct": exit_conditions.get("take_profit_pct"),
                "max_position_pct": position_sizing.get("max_position_pct"),
                "max_trade_notional_pct": position_sizing.get("max_trade_notional_pct"),
            }
    except Exception as e:
        logger.warning(f"[EODDigest] strategy_json parse failed: {e}")

    return {
        "stance": row.get("stance"),
        "rationale_excerpt": rationale[:_RATIONALE_EXCERPT_CHARS],
        "key_knobs": key_knobs,
        "changed": bool(row.get("changed")),
    }


async def _build_regime_section(storage: Any) -> Optional[dict[str, Any]]:
    try:
        rows = await storage.get_regime_snapshots(limit=_LATEST_ROW_LIMIT)
    except Exception as e:
        logger.warning(f"[EODDigest] get_regime_snapshots failed: {e}")
        return None
    if not rows:
        return None

    row = rows[0]
    return {
        "label": row.get("market_sentiment_label"),
        "index_kospi_chg_pct": row.get("index_kospi_chg_pct"),
        "index_kosdaq_chg_pct": row.get("index_kosdaq_chg_pct"),
        # FI-2: SC-3가 regime_snapshot에 이미 저장하는 스캔 커버리지(%) --
        # 이전까지 이 함수가 label/index 3필드만 골라 반환해 EOD 응답 도달
        # 전에 잘렸다(spec §1 FE-E 실측). additive -- 기존 3필드는 무변경.
        "scan_coverage_pct": row.get("scan_coverage_pct"),
    }


async def _build_discovery_section(
    storage: Any, trade_date: str
) -> Optional[dict[str, Any]]:
    """DS-5 폐루프(spec §6): 오늘 승격 종목(티커·이름·composite·최고 기여
    전략 태그) + 스킵 통계(사유별 카운트) + 어제 후보 fwd_1d 요약.

    None (null 내성, strategy/regime 섹션과 동일 관례) when the discovery
    ledger has never been written to at all (storage error, or the table
    is simply empty because DISCOVERY_ENABLED has never been on) — there
    is nothing meaningful to show. Once the ledger has ANY history,
    degrades to an all-empty-but-present dict for a day discovery simply
    didn't run/promote anything, rather than None, so a caller can
    distinguish "feature never used" from "ran today, nothing to report".
    """
    try:
        today_rows = await storage.get_discovery_candidates(
            trade_date=trade_date, limit=_DISCOVERY_TODAY_LIMIT
        )
    except Exception as e:
        logger.warning(f"[EODDigest] get_discovery_candidates(today) failed: {e}")
        return None

    try:
        recent_rows = await storage.get_discovery_candidates(
            limit=_DISCOVERY_RECENT_SCAN_LIMIT
        )
    except Exception as e:
        logger.warning(f"[EODDigest] get_discovery_candidates(recent) failed: {e}")
        recent_rows = []

    if not today_rows and not recent_rows:
        return None

    promoted: list[dict[str, Any]] = []
    skip_counts: dict[str, int] = {}
    for row in today_rows:
        try:
            if row.get("promoted"):
                promoted.append(
                    {
                        "ticker": row.get("ticker"),
                        "name": row.get("name"),
                        "composite_score": row.get("composite_score"),
                        "top_strategy_tag": _top_strategy_tag(
                            row.get("strategy_scores_json")
                        ),
                    }
                )
            else:
                reason = row.get("skip_reason") or "unknown"
                skip_counts[reason] = skip_counts.get(reason, 0) + 1
        except Exception as e:
            logger.warning(f"[EODDigest] discovery candidate row skipped: {e}")

    prev_day: Optional[dict[str, Any]] = None
    try:
        prev_dates = sorted(
            {
                r.get("trade_date")
                for r in recent_rows
                if r.get("trade_date") and r.get("trade_date") < trade_date
            },
            reverse=True,
        )
        if prev_dates:
            prev_trade_date = prev_dates[0]
            prev_rows = [r for r in recent_rows if r.get("trade_date") == prev_trade_date]
            fwd_values = [r["fwd_1d"] for r in prev_rows if r.get("fwd_1d") is not None]
            prev_day = {
                "trade_date": prev_trade_date,
                "candidate_count": len(prev_rows),
                "fwd_1d_filled_count": len(fwd_values),
                "avg_fwd_1d": (sum(fwd_values) / len(fwd_values)) if fwd_values else None,
            }
    except Exception as e:
        logger.warning(f"[EODDigest] discovery prev-day fwd_1d summary failed: {e}")

    return {
        "promoted": promoted,
        "skip_counts": skip_counts,
        "total_candidates": len(today_rows),
        "prev_day": prev_day,
    }


_NARRATE_SYSTEM_PROMPT = (
    "당신은 한국 주식 자동매매 시스템의 장마감 브리핑 작성자입니다. "
    "아래 장마감 데이터(JSON)를 근거로 오늘 하루를 요약하는 한국어 브리핑을 "
    "정확히 한 편 작성하십시오. 길이는 400~800자. 과장된 표현이나 투자 권유성 "
    "문구를 쓰지 마십시오. 수치는 데이터에 있는 값을 그대로 인용하고 새로운 "
    "수치를 만들어내지 마십시오. strategy 섹션은 데이터의 가장 최근 전략 "
    "리비전이며 오늘(trade_date)이 아닌 다른 날짜에 결정되었을 수 있습니다 — "
    "이를 '오늘의 전략'처럼 단정하지 말고 '익일 적용 전략(EOD 합의)'으로 "
    "서술하십시오. 브리핑 본문만 출력하고 다른 설명은 덧붙이지 마십시오."
)


async def narrate_eod_digest(digest: dict[str, Any]) -> Optional[str]:
    """`digest` (a `build_eod_digest` result) -> a Korean EOD briefing, or
    None on any failure/timeout/blank response.

    Reuses the shared LLM router exactly like strategy_panel.py's plain-
    text convention (`get_llm_provider().generate(...)`); `TaskType.GENERAL`
    since this is a descriptive briefing, not a structured decision (no
    `generate_structured`/schema here). Never-raise by design: every
    exception (backend failure, malformed response, etc.) AND
    `asyncio.wait_for`'s timeout are both funneled into a plain `None`
    return, and per E3-D2, callers (Telegram/FE) fall back to a
    deterministic template render when this returns None — narrate must
    never be able to stall or break the EOD chain that calls it.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    user_prompt = (
        "다음은 오늘의 장마감 데이터입니다. 이를 근거로 브리핑을 작성하십시오.\n\n"
        + json.dumps(digest, ensure_ascii=False, default=str)
    )

    try:
        raw = await asyncio.wait_for(
            get_llm_provider().generate(
                [
                    SystemMessage(content=_NARRATE_SYSTEM_PROMPT),
                    HumanMessage(content=user_prompt),
                ],
                task=TaskType.GENERAL,
            ),
            timeout=_NARRATE_TIMEOUT_SECONDS,
        )
    except Exception as e:
        logger.warning(f"[EODDigest] narrate_eod_digest failed: {e}")
        return None

    if not raw or not raw.strip():
        return None
    return raw.strip()
