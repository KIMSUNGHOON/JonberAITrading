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


# ------------------------------------------------------------------
# Postmarket 리포트 전용 수집기 (Task 7, 2026-08-13)
#
# `build_eod_digest`가 돌려주는 dict에는 fills/realized/strategy_revisions
# 키가 아예 없다 -- 그 세 종류는 이 함수의 계약 밖이다(반환 shape은
# trade_date/watch/account/holdings/strategy/regime/discovery 7개뿐,
# 실물 확인: `grep -nE '"[a-z_]+":' eod_digest.py`). postmarket.html이
# 필요로 하는 "오늘 체결/실현손익/전략개정 리스트"는 여기 세 함수로 별도
# 조립해 coordinator.py가 `build_eod_digest`와 별개로 직접 호출한다 --
# `build_eod_digest` 자체의 반환 계약은 넓히지 않는다(narrate_eod_digest·
# FE·Telegram 텍스트 요약이 전부 그 계약을 그대로 읽어서, 넓히면 그만큼
# 회귀 표면이 커진다).
# ------------------------------------------------------------------

# 하루치 체결/실현손익은 보통 한 자릿수~수십 건이라(2026-08 라이브 관측),
# newest-first로 200행만 긁어 날짜 문자열로 거르는 것으로 충분하다 --
# `kr_stock_trades`/`kr_realized_pnl` 둘 다 trade_date 컬럼이 없어 서버측
# 날짜 필터가 없다(daily_perf_snapshot과 같은 scan-then-match 관례).
_POSTMARKET_FILL_SCAN_LIMIT = 200
_POSTMARKET_REALIZED_SCAN_LIMIT = 200


async def _build_postmarket_fills(storage: Any, trade_date: str) -> list[dict[str, Any]]:
    """그날 체결 목록(시각순) -- `kr_stock_trades`가 유일한 소스다(원장의
    다른 어떤 표도 개별 체결의 시각/가격/수량을 이 해상도로 갖지 않는다).
    이 모듈 docstring 29행의 경고("kr_stock_trades를 여기서 집계하지
    말라")는 daily_realized_pnl 재계산 얘기다 -- 개별 체결을 나열하는
    것은 그 경고가 막는 "재구성한 집계 숫자"가 아니라 이 표 본연의 용도다.

    ⚠️ `kr_stock_trades.created_at`은 `agent_chat_decisions`와 달리 이미
    KST 로컬시각이다(실물 대조: 2026-08-12 13:2x~13:3x대 체결 행이 그대로
    장중 시각과 일치). `get_day_rollup`처럼 `date(created_at,'+9 hours')`를
    적용하면 15시 이후 체결이 다음 날짜로 밀려버려 여기서는 쓰지 않고,
    문자열 앞 10자리(YYYY-MM-DD)만 그대로 비교한다.

    `reason`은 `entry_or_exit`(entry/exit 두 값뿐)에서만 파생한다 -- 손절/
    익절/재량청산을 구분할 근거(포지션·의사결정 조인)가 이 테이블에
    없어서, 확인 안 된 사유를 "손절"처럼 단정해 적으면 틀린 정보가 된다.

    known limitation: 같은 체결이 드물게 두 행으로 중복 기록되는 결함이
    별도로 있다(order_id+수량+가격 전부 일치가 진짜 중복) -- 이 함수는
    그 중복을 걸러내지 않는다(별건으로 미수정, 여기서 손대지 않는다).
    """
    try:
        rows = await storage.get_kr_stock_trades(limit=_POSTMARKET_FILL_SCAN_LIMIT)
    except Exception as e:
        logger.warning(f"[EODDigest] postmarket fills collect failed: {e}")
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            created = str(row.get("created_at") or "")
            if created[:10] != trade_date:
                continue
            out.append(
                {
                    "time": created[11:16],
                    "ticker": row.get("stk_cd"),
                    "side": (row.get("side") or "").upper(),
                    "quantity": row.get("executed_quantity"),
                    "price": row.get("price"),
                    "reason": "청산" if row.get("entry_or_exit") == "exit" else None,
                }
            )
        except Exception as e:
            logger.warning(f"[EODDigest] postmarket fill row skipped: {e}")
    out.sort(key=lambda f: f["time"])
    return out


async def _build_postmarket_realized(
    storage: Any, trade_date: str
) -> list[dict[str, Any]]:
    """그날 실현손익(종목별, **합산**) -- `kr_realized_pnl`은 매도 체결
    **1건당 1행**이다(`record_kr_realized_pnl_async`가 `_apply_sell_fill`
    에서 체결마다 호출한다). 부분체결로 나뉜 청산은 같은 종목이 여러 행으로
    쌓인다(2026-08-12 리뷰 실측: 316140 청산이 183+183+92+91=549주, 4행).

    합산 없이 그대로 내보내면 사람이 리포트를 볼 때 "정상적인 부분청산
    4건"과 `kr_stock_trades`의 알려진 중복 기록 버그
    ([[finding-duplicate-fill-rows]], 같은 체결이 31초 간격으로 두 번
    기록됨)를 구별할 수 없다(2026-08-13 리뷰 Critical 2). 그래서 종목별로
    quantity/net을 더해 한 줄로 만들되, 합쳐졌다는 사실 자체는 숨기지
    않는다 -- 슬라이스(원본 행) 개수를 `slices`에 남겨 템플릿이 2건 이상일
    때만 "(N건)"을 붙인다.

    `net_amount`(수수료·세금 차감 후)를 합산한다. `realized_amount`(gross)
    를 쓰면 실현이익을 과대계상한다(왕복비용 미차감 -- 실측 사례 gross
    대비 순이익 43% 과대). `net_amount`가 없는 행(마이그레이션 이전 옛
    행)만 그 행에 한해 gross로 물러난다 -- 같은 종목의 다른 행이
    `net_amount`를 갖고 있어도 섞어 합산한다(둘 다 "그 종목의 실현손익"
    이라는 같은 단위이기 때문).

    `stk_cd='ALL'` 행은 계좌 백필이지 거래가 아니다 -- `get_day_rollup`과
    같은 관례로 제외한다.
    """
    try:
        rows = await storage.get_kr_realized_pnl(limit=_POSTMARKET_REALIZED_SCAN_LIMIT)
    except Exception as e:
        logger.warning(f"[EODDigest] postmarket realized collect failed: {e}")
        return []

    agg: dict[Any, dict[str, Any]] = {}
    order: list[Any] = []
    for row in rows:
        try:
            ticker = row.get("stk_cd")
            if ticker == "ALL":
                continue
            created = str(row.get("created_at") or "")
            if created[:10] != trade_date:
                continue
            net = row.get("net_amount")
            if net is None:
                net = row.get("realized_amount")
            qty = row.get("quantity") or 0
            net = net or 0

            if ticker not in agg:
                agg[ticker] = {"ticker": ticker, "quantity": 0, "net": 0.0, "slices": 0}
                order.append(ticker)
            entry = agg[ticker]
            entry["quantity"] += qty
            entry["net"] += net
            entry["slices"] += 1
        except Exception as e:
            logger.warning(f"[EODDigest] postmarket realized row skipped: {e}")
    return [agg[t] for t in order]


# knob 이름 -> strategy_json 안의 "section.field" 경로. strategy_apply.py의
# STRATEGY_MAPPED_FIELDS/_source_values와 같은 8개 노브(그 allowlist가
# "전략이 실제로 실효값에 도달하는 노브"의 SSOT -- GATE_PROTECTED 노브는
# 일부러 뺐다, 전략이 못 움직이는 값의 변화를 "개정"으로 보여주면 오도).
# exit_conditions 둘은 strategy_json에 분율(0~1)로 있다 -- default_stop_
# loss_pct 같은 ×100 퍼센트 파생값이 아니라 원본 분율 그대로 보여준다
# (리포트는 방향만 보이면 충분하고, 여기서 또 ×100 하면 strategy_apply.py
# 로그의 숫자와 어긋나 보인다).
_REVISION_KNOB_PATHS: dict[str, str] = {
    "stop_loss_pct": "exit_conditions.stop_loss_pct",
    "take_profit_pct": "exit_conditions.take_profit_pct",
    "max_position_pct": "position_sizing.max_position_pct",
    "min_cash_ratio": "position_sizing.min_cash_ratio",
    "max_trade_notional_pct": "position_sizing.max_trade_notional_pct",
    "risk_budget_pct": "position_sizing.risk_budget_pct",
    "target_vol_pct": "position_sizing.target_vol_pct",
    "vol_multiplier_min": "position_sizing.vol_multiplier_min",
}


def _dig(d: Optional[dict], path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


async def _build_postmarket_revisions(
    storage: Any, trade_date: str
) -> list[dict[str, Any]]:
    """오늘 전략 개정 -- 오늘자 최신 리비전과 그 직전 리비전을 노브별로
    대조해 [{knob, before, after}]로 돌려준다(값 하나만 보여주면 "4일
    연속 축소" 같은 흐름이 안 보인다 -- 방향 표시는 postmarket.html이
    before<after로 판단하므로 여기는 원값 두 개만 정확히 내면 된다).

    `changed=0`(오늘 EOD 합의가 돌긴 했지만 실제로는 아무것도 안 바꿈)
    이거나 최신 행의 `trade_date`가 오늘이 아니면(합의가 아직 안 돌았거나
    실패해 어제 이전 행이 최신) 빈 리스트 -- "오늘 무엇이 바뀌었나"이지
    "현재 전략이 무엇인가"가 아니다(그건 이미 digest['strategy']가 보여
    준다, `_build_strategy_section` 참고).
    """
    try:
        rows = await storage.get_strategy_revisions(limit=2)
    except Exception as e:
        logger.warning(f"[EODDigest] postmarket revisions collect failed: {e}")
        return []

    if len(rows) < 2:
        return []
    latest, prev = rows[0], rows[1]
    if latest.get("trade_date") != trade_date or not latest.get("changed"):
        return []

    try:
        latest_json = json.loads(latest.get("strategy_json") or "{}")
        prev_json = json.loads(prev.get("strategy_json") or "{}")
    except Exception as e:
        logger.warning(f"[EODDigest] postmarket revisions parse failed: {e}")
        return []

    out: list[dict[str, Any]] = []
    for knob, path in _REVISION_KNOB_PATHS.items():
        before = _dig(prev_json, path)
        after = _dig(latest_json, path)
        if before is None or after is None:
            continue
        try:
            if abs(float(before) - float(after)) < 1e-9:
                continue
        except (TypeError, ValueError):
            if before == after:
                continue
        out.append({"knob": knob, "before": before, "after": after})
    return out


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
