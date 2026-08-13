"""Phase 2 Task 2: minimal daily market-regime snapshot (scanner breadth
proxy).

There is no market-wide sentiment/regime signal anywhere in this codebase
(confirmed by audit). The only durable, market-wide artifact is the
background scanner's `scan_sessions` row
(`services/background_scanner/scanner.py`) — its buy/sell/hold/watch/avoid
counts across a full KOSPI/KOSDAQ sweep stand in as a breadth proxy for
market-wide risk appetite. A real index/flow-data fetcher is a later phase;
this is intentionally minimal.

`compute_regime_snapshot` is a pure, SYNCHRONOUS function (no LLM, no
network, no dependency on this app's own storage) that reads the LATEST
completed-OR-partial `scan_sessions` row for a given trade_date directly off
the scanner's own sqlite db via the stdlib `sqlite3` module (there is no
async reader/writer contract to honor here — the scanner db is read
read-only and independently of this app's aiosqlite storage). It does NOT
write anywhere; persisting the returned dict (via
`storage_service.StorageService.save_regime_snapshot`) is left to a later
orchestrator task that decides IF/WHEN to save.

SC-1: a scan that got stopped (timeout/manual stop) before reaching the end
of the universe is recorded by the scanner as status='partial' rather than
being left orphaned at 'running' forever — this function treats 'partial'
the same as 'completed' so a scan that covered most of the day's universe
still contributes its breadth counts instead of being silently discarded
(real incident: a 90-minute-timeout stop once orphaned 3700/4276 collected
stocks at status='running', so breadth was 0/neutral all day). Among same-day
rows the LATEST by started_at still wins regardless of status.

Failure-harmless by design, mirroring `calibration.label_and_calibrate`/
`eod_snapshot.write_daily_snapshot`: any error (missing db file, missing
table, malformed row) — or simply no completed/partial scan for that day —
returns `None` rather than raising, since this must never break whatever EOD
job calls it.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# Mirrors services/background_scanner/scanner.py::DB_PATH's resolution
# exactly (backend/data/scanner_results.db) so a future caller that needs a
# default path agrees with the scanner's own writer. compute_regime_snapshot
# itself takes scanner_db_path as a required param for testability — this
# constant is not used internally, only exposed for callers.
SCANNER_DB_PATH = Path(__file__).parent.parent.parent / "data" / "scanner_results.db"


def compute_regime_snapshot(scanner_db_path: str, trade_date: str) -> Optional[dict]:
    """Compute a market-regime snapshot from the day's latest completed (or
    partial, SC-1) scan.

    Args:
        scanner_db_path: path to the background scanner's sqlite db
            (contains `scan_sessions`).
        trade_date: "YYYY-MM-DD" — the day to look up.

    Returns:
        dict with keys id (new uuid4), trade_date, breadth_buy, breadth_sell,
        breadth_hold, breadth_ratio, regime_label ("risk_on"/"risk_off"/
        "neutral"), source ("scanner"). `None` if no completed-or-partial
        scan exists for trade_date, or on any error (missing db file,
        missing table, etc.) — never raises.
    """
    try:
        conn = sqlite3.connect(scanner_db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT buy_count, sell_count, hold_count, status, completed,
                       total_stocks
                FROM scan_sessions
                WHERE status IN ('completed', 'partial') AND date(started_at) = ?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (trade_date,),
            )
            row = cursor.fetchone()
        finally:
            conn.close()

        if row is None:
            return None

        buy_count = int(row["buy_count"] or 0)
        sell_count = int(row["sell_count"] or 0)
        hold_count = int(row["hold_count"] or 0)

        # SC-3: expose what fraction of the day's universe this breadth is
        # actually sampled from -- a 'partial' row (SC-1) contributes its
        # breadth same as 'completed', but with no coverage figure a partial
        # scan at 5% and one at 95% look identical to any downstream reader.
        # 'completed' is always the full universe by definition (100); a
        # 'partial' row with an unreadable/zero total_stocks (defensive --
        # should not happen given the scanner always sets it) falls back to
        # None rather than a misleading number.
        if row["status"] == "completed":
            scan_coverage_pct = 100.0
        else:  # 'partial' (the only other value the WHERE clause admits)
            total_stocks = row["total_stocks"]
            completed_count = row["completed"]
            if total_stocks:
                scan_coverage_pct = (completed_count or 0) / total_stocks * 100
            else:
                scan_coverage_pct = None

        breadth_ratio = (buy_count - sell_count) / max(
            1, buy_count + sell_count + hold_count
        )

        threshold = get_settings().EOD_REGIME_BREADTH_THRESHOLD
        if breadth_ratio > threshold:
            regime_label = "risk_on"
        elif breadth_ratio < -threshold:
            regime_label = "risk_off"
        else:
            regime_label = "neutral"

        return {
            "id": str(uuid.uuid4()),
            "trade_date": trade_date,
            "breadth_buy": buy_count,
            "breadth_sell": sell_count,
            "breadth_hold": hold_count,
            "breadth_ratio": breadth_ratio,
            "regime_label": regime_label,
            "source": "scanner",
            "scan_coverage_pct": scan_coverage_pct,
        }
    except Exception as e:
        logger.warning(
            f"[Regime] compute_regime_snapshot failed for {trade_date}: {e}"
        )
        return None


def _normalize_pct(pct: Optional[float], cap: float = 3.0) -> Optional[float]:
    """등락률(%)을 [-1, 1]로 정규화(±cap% 포화)."""
    if pct is None:
        return None
    return max(-1.0, min(1.0, pct / cap))


def _sign(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)


def compute_market_regime(
    breadth: Optional[dict],
    index: Optional[dict],
    flow: Optional[dict],
    trade_date: Optional[str],
    threshold: float,
) -> Optional[dict]:
    """breadth 스냅샷에 지수·수급을 병합하고 파생 시장심리를 산출.

    sentiment_score = available한 신호들의 평균:
      - breadth_ratio (이미 [-1,1] 범위)
      - 지수 등락률 정규화 (KOSPI/KOSDAQ 평균, ±3% 포화)
      - 수급 부호 (외국인/기관 순매매 부호 평균)
    셋 다 None이면 None(저장 안 함, 현행과 동일).
    market_sentiment_label = score를 threshold로 bullish/bearish/neutral 라벨링.
    breadth 필드(id/trade_date/breadth_*/regime_label/source)는 보존(하위호환).

    L-5: breadth가 없으면(스캐너 미완료 등) regime_label은 더 이상 'neutral'
    하드코딩이 아니라 sentiment_score 기반 폴백을 쓴다 — score >= threshold면
    'risk_on', <= -threshold면 'risk_off', 그 사이는 'neutral'. 단, 신호 자체가
    하나도 없으면(지수·수급 전부 무의미 -> signals가 빈 리스트) 폴백을 태우지
    않고 스켈레톤의 기존 'neutral'을 그대로 유지한다(threshold=0 같은 극단값에서
    score=0.0이 '>= threshold'를 만족해 'risk_on'으로 오분류되는 것을 방지).
    breadth가 있으면 이 폴백은 전혀 실행되지 않는다 — regime_label은 위에서
    dict(breadth)로 복사된 값 그대로 byte-불변.
    """
    if breadth is None and index is None and flow is None:
        return None

    # 저장형 시작: breadth 필드 보존(없으면 신규 뼈대)
    if breadth is not None:
        out = dict(breadth)
    else:
        out = {
            "id": str(uuid.uuid4()),
            "trade_date": trade_date,
            "breadth_buy": None, "breadth_sell": None, "breadth_hold": None,
            "breadth_ratio": None, "regime_label": "neutral", "source": "market",
            "scan_coverage_pct": None,  # SC-3: no scan session that day
        }

    # 지수/수급 필드 병합(없으면 None)
    idx = index or {}
    flw = flow or {}
    out["index_kospi"] = idx.get("index_kospi")
    out["index_kospi_chg_pct"] = idx.get("index_kospi_chg_pct")
    out["index_kosdaq"] = idx.get("index_kosdaq")
    out["index_kosdaq_chg_pct"] = idx.get("index_kosdaq_chg_pct")
    out["foreign_net_amount"] = flw.get("foreign_net_amount")
    out["institution_net_amount"] = flw.get("institution_net_amount")

    # sentiment_score = available 신호 평균 (regime_label 폴백보다 먼저 계산되어야 함)
    signals: list[float] = []
    if breadth is not None and breadth.get("breadth_ratio") is not None:
        signals.append(float(breadth["breadth_ratio"]))
    idx_pcts = [
        _normalize_pct(idx.get("index_kospi_chg_pct")),
        _normalize_pct(idx.get("index_kosdaq_chg_pct")),
    ]
    idx_pcts = [p for p in idx_pcts if p is not None]
    if idx_pcts:
        signals.append(sum(idx_pcts) / len(idx_pcts))
    flow_signs = [_sign(flw.get("foreign_net_amount")), _sign(flw.get("institution_net_amount"))]
    flow_signs = [s for s in flow_signs if s is not None]
    if flow_signs:
        signals.append(sum(flow_signs) / len(flow_signs))

    score = sum(signals) / len(signals) if signals else 0.0
    out["sentiment_score"] = score
    if score > threshold:
        out["market_sentiment_label"] = "bullish"
    elif score < -threshold:
        out["market_sentiment_label"] = "bearish"
    else:
        out["market_sentiment_label"] = "neutral"

    # L-5 폴백: breadth 없을 때만, 그리고 신호가 하나라도 있을 때만 적용.
    if breadth is None and signals:
        if score >= threshold:
            out["regime_label"] = "risk_on"
        elif score <= -threshold:
            out["regime_label"] = "risk_off"
        else:
            out["regime_label"] = "neutral"

    return out

