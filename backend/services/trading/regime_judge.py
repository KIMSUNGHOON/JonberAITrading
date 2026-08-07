"""AI 레짐 판정 — 매크로를 읽고 라벨 하나를 낸다.

LLM은 사슬의 한 칸만 담당한다: `bull|neutral|bear` 중 하나. 그 라벨이
숫자가 되는 것은 `exposure_target.compute_regime_target`의 고정 테이블이고,
그 숫자를 집행하는 것은 게이트 검사 8이다. **판단은 AI가, 숫자는 산술이,
집행은 게이트가.**

설계: docs/superpowers/specs/2026-08-07-regime-aware-exposure-design.md
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import structlog

from agents.llm.tasks import TaskType
from agents.llm_provider import create_messages, get_llm_provider
from services.storage_service import get_storage_service
from services.trading.exposure_target import (
    JUDGMENT_MAX_AGE_DAYS,
    REGIME_ANCHORS,
    compute_regime_target,
)
from services.trading.macro_snapshot import refresh_macro_snapshot

logger = structlog.get_logger(__name__)

REGIME_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "regime": {"type": "string", "enum": ["bull", "neutral", "bear"]},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "key_drivers": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["regime", "rationale"],
}

_SYSTEM = """당신은 한국 주식 포트폴리오의 매크로 레짐을 판정한다.

주어진 미국 시장 지표로 오늘 한국 장의 위험선호를 판단하라.

- EWY: 미국에 상장된 한국 ETF. 외국인이 실제로 값을 매기는 한국 시장이다. 가장 무겁게 본다.
- SPY/QQQ: 미국 위험선호. VIXY: 변동성. TLT: 장기금리(오르면 금리 하락).
- UUP: 달러(오르면 신흥국 자금 유출 압력). USO: 유가. GLD: 안전자산 선호.

bull  = 위험선호가 뚜렷하다
neutral = 방향이 불분명하거나 신호가 엇갈린다
bear  = 위험회피가 뚜렷하다

rationale에는 반드시 **구체적 수치를 인용**하라. 일반론만 쓰면 판정이 아니다."""


def _format_macro(snapshot: dict, history: dict[str, list[float]]) -> str:
    lines = ["오늘 매크로 (간밤 미국장 마감):"]
    for ticker, q in snapshot["quotes"].items():
        chg = q.get("chg_pct")
        lines.append(f"  {ticker}: {chg:+.2f}%" if chg is not None else f"  {ticker}: 결측")
    if snapshot.get("missing"):
        lines.append(f"  (수신 실패: {', '.join(snapshot['missing'])})")
    for ticker, series in history.items():
        if len(series) >= 2:
            lines.append(f"  {ticker} 최근 {len(series)}일: "
                         + ", ".join(f"{v:+.1f}" for v in series[-10:]))
    return "\n".join(lines)


async def judge_regime() -> Optional[dict]:
    """오늘의 레짐을 판정하고 목표까지 계산해 1행 적는다. never-raise.

    매크로 수집이 실패하면 판정하지 않는다 — 입력 없는 판정은 근거가 없다.
    LLM이 실패하면 **직전 유효 판정을 잇는다**(중간값을 새로 만들지 않는다).
    """
    try:
        snapshot = await refresh_macro_snapshot()
        if not snapshot:
            logger.warning("regime_judge_skipped_no_macro")
            return None

        storage = await get_storage_service()
        prev_row = await storage.get_latest_regime_judgment()

        history: dict[str, list[float]] = {}
        for ticker in ("EWY", "SPY", "VIXY"):
            series = await storage.get_recent_macro_returns(ticker, limit=10)
            if series:
                history[ticker] = series

        degraded: list[str] = []
        regime: Optional[str] = None
        confidence = None
        rationale = ""
        key_drivers: list[str] = []

        try:
            messages = create_messages(
                system_prompt=_SYSTEM, user_message=_format_macro(snapshot, history)
            )
            out = await get_llm_provider().generate_structured(
                messages, REGIME_SCHEMA, task=TaskType.STRATEGIC_DECISION
            )
            candidate = str(out.get("regime", "")).strip().lower()
            if candidate in REGIME_ANCHORS:
                regime = candidate
                confidence = out.get("confidence")
                rationale = str(out.get("rationale") or "")
                key_drivers = list(out.get("key_drivers") or [])
            else:
                # 라벨은 못 믿어도 스냅샷·LLM 응답 자체는 왔다 -- llm_unavailable과
                # 달리 완전한 공백은 아니다. rationale/key_drivers는 참고용으로
                # 남겨 둔다 (아래에서 prev_row가 없으면 bear로 정규화될 수 있다).
                degraded.append("regime_unparseable")
                logger.warning("regime_judge_unparseable", got=candidate)
                rationale = str(out.get("rationale") or "")
                key_drivers = list(out.get("key_drivers") or [])
                confidence = out.get("confidence")
        except Exception as e:
            degraded.append("llm_unavailable")
            logger.warning("regime_judge_llm_failed", error=str(e))

        if regime is None:
            if prev_row is not None:
                regime = prev_row["regime"]
                rationale = f"(직전 판정 유지) {prev_row.get('rationale') or ''}"
                key_drivers = prev_row.get("key_drivers") or []
                confidence = prev_row.get("confidence")
            elif "regime_unparseable" in degraded:
                # 완전한 공백(llm_unavailable)과 다르다 -- 스냅샷과 LLM 응답은
                # 받았고 라벨만 못 믿을 뿐이다. 직전 판정도 없으면
                # exposure_target의 "모르는 라벨 -> 가장 보수적인 앵커" 안전망과
                # 같은 결로 bear(0.55, 가장 낮은 앵커)로 정규화한다. neutral 같은
                # 중간값은 절대 만들어내지 않는다 -- 실패 폴백은 노출도를
                # 위로 열면 안 된다.
                degraded.append("regime_unparseable_no_fallback_defaulted_bear")
                logger.warning("regime_judge_unparseable_no_fallback_using_bear")
                regime = "bear"
            else:
                # llm_unavailable이고 직전도 없다 -- 임의의 숫자를 만들지 않는다.
                # 행을 안 적으면 get_effective_target()이 None을 돌려주고
                # 게이트는 검사를 건너뛴다(기존 천장이 그대로 남는다).
                logger.warning("regime_judge_no_fallback_available")
                return None

        equity, equity_peak, actual_pct = await _portfolio_state()

        target = compute_regime_target(
            regime_label=regime,
            prev_effective_pct=(prev_row or {}).get("effective_target_pct"),
            seed_actual_pct=actual_pct,
            index_returns=(await storage.get_recent_macro_returns("SPY", limit=20)) or [],
            equity=equity,
            equity_peak=equity_peak,
        )
        degraded.extend(target.degraded)

        trade_date = date.today().isoformat()
        persisted = await storage.insert_regime_judgment(
            trade_date=trade_date,
            regime=regime,
            confidence=confidence,
            rationale=rationale,
            key_drivers=key_drivers,
            anchor_target_pct=target.anchor_pct,
            effective_target_pct=target.target_pct,
            prev_effective_pct=target.prev_effective_pct,
            degraded=degraded,
            macro_snapshot_id=None,
        )
        if not persisted:
            # insert_regime_judgment는 실패-무해(자체 예외를 삼키고 False만
            # 반환)라 위 try/except로는 이 실패를 절대 못 잡는다 -- 반환값을
            # 직접 확인해야 "판정됨" 로그가 거짓 성공을 보고하지 않는다.
            logger.warning("regime_judge_persist_failed", trade_date=trade_date, regime=regime)
            return None

        logger.info(
            "regime_judged",
            regime=regime, anchor=target.anchor_pct,
            effective=target.target_pct, degraded=degraded,
        )
        return {
            "trade_date": trade_date,
            "regime": regime,
            "confidence": confidence,
            "rationale": rationale,
            "key_drivers": key_drivers,
            "anchor_target_pct": target.anchor_pct,
            "effective_target_pct": target.target_pct,
            "degraded": degraded,
        }
    except Exception as e:
        logger.warning("regime_judge_failed", error=str(e))
        return None


async def _portfolio_state() -> tuple[float, float, float]:
    """(equity, equity_peak, actual_stock_pct). 조회 실패는 (0,0,0) —
    호출자가 seed로만 쓰므로 0이면 램프가 바닥에서 시작할 뿐이다."""
    try:
        from app.core.kiwoom_singleton import get_shared_kiwoom_client_async

        client = await get_shared_kiwoom_client_async()
        balance = await client.get_account_balance()
        equity = float(balance.evlu_amt + balance.d2_ord_psbl_amt)
        stock_value = float(balance.evlu_amt)
        storage = await get_storage_service()
        peak_raw = await storage.get_equity_peak()
        equity_peak = max(equity, float(peak_raw or 0.0))
        actual = stock_value / equity if equity > 0 else 0.0
        return equity, equity_peak, actual
    except Exception as e:
        logger.warning("regime_judge_portfolio_state_failed", error=str(e))
        return 0.0, 0.0, 0.0


async def get_effective_target() -> Optional[float]:
    """유효한 목표 노출도(분율). 판정이 없거나 만료됐으면 None.

    **DB 오류는 raise한다** — 게이트가 '판정 없음'(검사 스킵)과 '못 읽음'
    (fail-closed deny)을 구별해야 한다.
    """
    storage = await get_storage_service()
    row = await storage.get_latest_regime_judgment()
    if row is None:
        return None
    try:
        judged = datetime.strptime(row["trade_date"], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    if date.today() - judged > timedelta(days=JUDGMENT_MAX_AGE_DAYS):
        logger.warning("regime_judgment_stale", trade_date=row["trade_date"])
        return None
    return float(row["effective_target_pct"])
