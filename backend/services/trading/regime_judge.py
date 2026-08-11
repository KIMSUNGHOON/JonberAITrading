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
    TARGET_VOL_PCT,
    VOL_MULTIPLIER_MIN,
    compute_regime_target,
)
from services.trading.index_series import (
    closes_to_returns,
    evaluate_series_lag,
    is_series_stale,
    refresh_index_daily,
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


async def judge_regime(
    *,
    target_vol_pct: float = TARGET_VOL_PCT,
    vol_multiplier_min: float = VOL_MULTIPLIER_MIN,
) -> Optional[dict]:
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

        # 변동성 입력은 KOSPI다 -- 우리는 한국 주식을 산다.
        # `TARGET_VOL_PCT=18.0`은 KOSPI 20일 실현 연변동성 중앙값
        # 20.6%와 맞물리는 값이고, SPY(9~15%)에서는 배수가 상한으로
        # 클램프돼 영원히 논다(2026-08-07 정정).
        closes = await storage.get_recent_index_closes(limit=21)
        index_returns = closes_to_returns([c for _, c in closes])
        series_stale = (
            is_series_stale(closes[-1][0], date.today()) if closes else False
        )
        # 수집(`refresh_index_daily`, 사이클이 바로 앞에서 돌린다) 직후의
        # 거래일 기준 지연 검사. 배수는 안 바꾸고 `degraded`에만 남는다 --
        # 08-10(월) 종가 누락 때 `degraded`가 `[]`라 아무도 몰랐다.
        series_lagging = (
            evaluate_series_lag(closes[-1][0], date.today()).lagging
            if closes
            else False
        )

        target = compute_regime_target(
            regime_label=regime,
            prev_effective_pct=(prev_row or {}).get("effective_target_pct"),
            seed_actual_pct=actual_pct,
            index_returns=index_returns,
            equity=equity,
            equity_peak=equity_peak,
            series_stale=series_stale,
            series_lagging=series_lagging,
            target_vol_pct=target_vol_pct,
            vol_multiplier_min=vol_multiplier_min,
        )
        degraded.extend(target.degraded)

        effective = _clamp_when_defense_unreliable(
            target.target_pct, degraded, prev_row
        )
        if effective is None:
            return None

        trade_date = date.today().isoformat()
        persisted = await storage.insert_regime_judgment(
            trade_date=trade_date,
            regime=regime,
            confidence=confidence,
            rationale=rationale,
            key_drivers=key_drivers,
            anchor_target_pct=target.anchor_pct,
            effective_target_pct=effective,
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
            effective=effective, degraded=degraded,
        )
        return {
            "trade_date": trade_date,
            "regime": regime,
            "confidence": confidence,
            "rationale": rationale,
            "key_drivers": key_drivers,
            "anchor_target_pct": target.anchor_pct,
            "effective_target_pct": effective,
            "degraded": degraded,
        }
    except Exception as e:
        logger.warning("regime_judge_failed", error=str(e))
        return None


# 낙폭 배수(`M_drawdown`)를 믿을 수 없게 만드는 저하 사유들. 둘 다 결과가
# 같다 -- `_drawdown_multiplier`가 무감쇠(1.0)로 조용히 넘어간다.
DEFENSE_UNRELIABLE_TAGS: tuple[str, ...] = (
    "portfolio_state_unavailable",
    "equity_peak_unavailable",
)


def _clamp_when_defense_unreliable(
    effective: float, degraded: list[str], prev_row: Optional[dict]
) -> Optional[float]:
    """계좌 조회 실패가 **노출도를 위로 열지 않도록** 목표를 눌러 둔다.

    **I-2 (2026-08-07 최종 리뷰)**: `_portfolio_state()`가 실패하면
    `(0.0, 0.0, 0.0)`이 나오고 `_drawdown_multiplier(0, 0)`가 `1.0`을
    돌려준다 -- `degraded`에 태그는 남지만 숫자는 그대로다. `M_vol`을
    축소 전용으로 바꾼 뒤(C-1) 평상시 `m_vol`은 1.0에 가까우므로
    **`m_drawdown`이 사실상 유일하게 남는 안전 배수**다. 계좌가 실제로
    낙폭 중인 날 하필 08:05 키움 조회가 실패하면 그날 하루가 방어 없이
    집행된다.

    - 이어받을 직전 목표가 있으면 그 값 **이하**로 클램프한다. 조회 실패가
      목표를 올리는 일은 없고, 판정 행은 그대로 남아 관측이 끊기지 않는다.
    - 계좌 자체를 못 읽었는데 직전 목표도 없으면 `None`을 돌려준다 -- 행을
      적지 않으면 `get_effective_target()`이 `None`이 되어 검사 8이 스킵되고,
      C-2의 되돌리기가 실효 천장을 브랜치 이전 값으로 되돌린다. 이 파일이
      이미 "직전도 없으면 임의의 숫자를 만들지 않는다"로 처리하는 것과
      같은 규칙이다.
    """
    if not any(tag in degraded for tag in DEFENSE_UNRELIABLE_TAGS):
        return effective

    prev = (prev_row or {}).get("effective_target_pct")
    if prev is None:
        if "portfolio_state_unavailable" in degraded:
            logger.warning("regime_judge_skipped_portfolio_unavailable")
            return None
        return effective

    if effective > float(prev):
        logger.warning(
            "regime_judge_target_clamped_defense_unreliable",
            raw=effective, clamped=float(prev), degraded=degraded,
        )
        degraded.append("target_clamped_defense_unreliable")
        return float(prev)
    return effective


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
    (여기서는 숫자를 바꾸지 않는다 — `peak_raw or 0.0`와 결과값은 동일하다).

    **그 태그를 실제로 소비하는 곳은 `_clamp_when_defense_unreliable`이다**
    (I-2, 2026-08-07): 기록만 남기고 숫자를 그대로 두면 조회 실패가 방어
    없는 목표를 그날 하루 집행하게 만든다.
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
        await refresh_index_daily()
    except Exception as e:
        # never-raise가 계약이지만 방어적으로 한 겹 더 — 수집 실패가
        # 판정을 막으면 안 된다(기존 행으로 계산은 계속된다).
        logger.warning("regime_cycle_index_refresh_failed", error=str(e))

    knobs: dict = {}
    try:
        coordinator = await _get_trading_coordinator()
        rp = getattr(coordinator, "risk_params", None)
        if rp is not None:
            knobs = {
                "target_vol_pct": float(rp.target_vol_pct),
                "vol_multiplier_min": float(rp.vol_multiplier_min),
            }
    except Exception as e:
        logger.warning("regime_cycle_knob_read_failed", error=str(e))

    try:
        await judge_regime(**knobs)
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
