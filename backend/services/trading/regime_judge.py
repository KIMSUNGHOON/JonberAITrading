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
                degraded.append("regime_unparseable")
                logger.warning("regime_judge_unparseable", got=candidate)
        except Exception as e:
            degraded.append("llm_unavailable")
            logger.warning("regime_judge_llm_failed", error=str(e))

        if regime is None:
            if prev_row is None:
                # 직전도 없다 -- 실패 유형(llm_unavailable/regime_unparseable)과
                # 무관하게 임의의 숫자를 만들지 않는다. `bear`조차도 폴백으로
                # 안 된다 -- 기존 실제 비중(예: 13%)에서 일일 램프(+15%)로
                # 계산하면 판정 실패가 오히려 상한을 열어버릴 수 있다(스펙 §3
                # U2: "neutral을 폴백으로 쓰지 않는다"는 원칙은 임의의 숫자 전체에
                # 적용된다, bear도 예외가 아니다). 행을 안 적으면
                # get_effective_target()이 None을 돌려주고 게이트는 검사를
                # 건너뛴다(기존 천장이 그대로 남는다) -- 이것이 스펙이 의도한
                # "판정 못 함"의 결과다.
                logger.warning("regime_judge_no_fallback_available")
                return None
            regime = prev_row["regime"]
            rationale = f"(직전 판정 유지) {prev_row.get('rationale') or ''}"
            key_drivers = prev_row.get("key_drivers") or []
            confidence = prev_row.get("confidence")

        equity, equity_peak, actual_pct, portfolio_degraded = await _portfolio_state()
        degraded.extend(portfolio_degraded)

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


async def _portfolio_state() -> tuple[float, float, float, list[str]]:
    """(equity, equity_peak, actual_stock_pct, degraded).

    계좌 조회 자체가 실패하면 (0.0, 0.0, 0.0, ["portfolio_state_unavailable"])을
    돌려준다 — 호출자가 seed로만 쓰므로 0이면 램프가 바닥에서 시작할 뿐이다.

    `StorageService.get_equity_peak()`은 "스냅샷 없음"(정상, `0.0`)과 "조회
    자체 실패"(`None`)를 명시적으로 구분해서 돌려준다. `peak_raw or 0.0`로
    두 경우를 뭉개면 실제 고점을 잃어버린 채로 오늘 equity를 고점처럼
    취급하게 되고, `_drawdown_multiplier`가 무감쇠(1.0)로 조용히 넘어간다 —
    계좌가 실제로 낙폭 중인 날 하필 이 조회가 실패하면 낙폭 방어가 흔적
    없이 꺼진다. 그래서 `None`인 경우를 따로 감지해 `degraded`에 남긴다
    (숫자 자체는 바꾸지 않는다 — `peak_raw or 0.0`와 결과값은 동일하다.
    그 값을 어떻게 쓸지는 이 태스크의 범위 밖이고, 지금 필요한 건 기록이다).
    """
    degraded: list[str] = []
    try:
        from app.core.kiwoom_singleton import get_shared_kiwoom_client_async

        client = await get_shared_kiwoom_client_async()
        balance = await client.get_account_balance()
        equity = float(balance.evlu_amt + balance.d2_ord_psbl_amt)
        stock_value = float(balance.evlu_amt)

        storage = await get_storage_service()
        peak_raw = await storage.get_equity_peak()
        if peak_raw is None:
            # 조회 자체 실패 -- "스냅샷 없음"(0.0, 정상)과 다르다. 낙폭
            # 배수를 신뢰할 수 없다는 사실을 판정 행에 남긴다.
            degraded.append("equity_peak_unavailable")
            logger.warning("regime_judge_equity_peak_unavailable")
            peak_value = 0.0
        else:
            peak_value = float(peak_raw)
        equity_peak = max(equity, peak_value)

        actual = stock_value / equity if equity > 0 else 0.0
        return equity, equity_peak, actual, degraded
    except Exception as e:
        logger.warning("regime_judge_portfolio_state_failed", error=str(e))
        if "portfolio_state_unavailable" not in degraded:
            degraded.append("portfolio_state_unavailable")
        return 0.0, 0.0, 0.0, degraded


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


async def _get_trading_coordinator():
    """테스트가 패치할 수 있게 분리한 간접층.

    ⚠️ 실제 싱글턴 접근점은 `app.dependencies.get_trading_coordinator`다
    (`app/core/dependencies.py`는 이 리포에 없다) — Task 5의
    `create_messages` 시그니처, Task 7의 `_persist_fields`/클래스명과 같은
    계열로, 브리프 원문의 추정 경로가 실물과 달랐던 지점이다.
    """
    from app.dependencies import get_trading_coordinator

    return await get_trading_coordinator()


async def run_daily_regime_cycle() -> None:
    """08:05 일일 사이클: 판정 → 슬롯 적용. never-raise.

    휴장일에는 아무것도 하지 않는다. ⚠️ 실제 이름은 `is_trading_day`이고
    `get_holiday_service`는 **async**다 -- 2026-08-06에 존재하지 않는
    `is_business_day`를 await 없이 불러 넓은 except가 삼키는 바람에
    휴장일 스킵이 한 번도 작동하지 않았다.
    """
    try:
        from datetime import date as _date

        from services.krx_holiday import get_holiday_service

        svc = await get_holiday_service()
        if not svc.is_trading_day(_date.today()):
            logger.info("regime_cycle_skipped_non_trading_day")
            return
    except Exception as e:
        # 영업일 판단이 안 되면 진행한다 -- 판정 한 번이 더 도는 것이
        # 열린 장에 판정이 없는 것보다 낫다.
        logger.warning("regime_cycle_trading_day_check_failed", error=str(e))

    try:
        await judge_regime()
    except Exception as e:
        logger.warning("regime_cycle_judge_failed", error=str(e))

    try:
        coordinator = await _get_trading_coordinator()
        await coordinator.apply_regime_slots()
    except Exception as e:
        logger.warning("regime_cycle_slots_failed", error=str(e))


def start_regime_scheduler(hour: int = 8, minute: int = 5):
    """평일 08:05 — 매크로 수집(08:00) 뒤, 브리핑(08:30) 앞.
    REGIME_EXPOSURE_ENABLED off면 스케줄러를 띄우지 않는다."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    from app.config import get_settings

    try:
        if not get_settings().REGIME_EXPOSURE_ENABLED:
            return None
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            run_daily_regime_cycle,
            CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute),
            id="regime_daily_cycle",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("regime_scheduler_started", hour=hour, minute=minute)
        return scheduler
    except Exception as e:
        logger.warning("regime_scheduler_failed", error=str(e))
        return None
