"""Phase 3: the strategy-level panel — context assembly from the Phase1/2
ledgers + one parallel structured-vote round by 3 strategy-altitude
panelists.

Deliberately NOT the agent-chat ChatRoom: every agent-chat model
(ChatSession/MarketContext/prompts) is ticker-bound and a fake-ticker
session would pollute the agent_chat_decisions ledger that EOD aggregation
reads. This panel is a new, lightweight loop that reuses only the shared
LLM layer (get_llm_provider().generate_structured — JSON parse + required
keys, raises on failure) with TaskType.STRATEGIC_DECISION (opus routing).

Structured-only by contract: a panelist whose call fails (parse error,
LLMAllBackendsFailed, timeout) becomes {"panelist", "error"} — excluded
from the electorate by strategy_consensus.valid_votes. No free-text
parsing, no defaults masquerading as data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import date
from typing import Any, Optional

from agents.llm.tasks import TaskType
from agents.llm_provider import get_llm_provider

from services.discovery.ledger import get_discovery_performance

from .exposure_target import (
    DAILY_TARGET_DELTA_MAX,
    EXPOSURE_FLOOR,
    REGIME_ANCHORS,
    TARGET_CEILING,
    VOL_MULTIPLIER_MAX,
    VOL_WINDOW,
    compute_regime_target,
)
from .index_series import closes_to_returns, is_series_stale
from .strategy_consensus import (
    KNOB_BOUNDS,
    MAX_RELATIVE_DELTA,
    STRATEGY_VOTE_SCHEMA,
)

logger = logging.getLogger(__name__)

# 최근 N일 시계열 창 (컨텍스트 크기 통제)
_REGIME_DAYS = 14
_PERF_ROWS = 30

# DS-5 폐루프(spec §6): get_discovery_performance의 lookback 창 — DS-3의
# 자체 기본값(14)과 동일하게 맞춘다.
_DISCOVERY_PERFORMANCE_DAYS = 14

_SCHEMA_INSTRUCTION = (
    "반드시 아래 JSON 스키마에 맞는 JSON 객체 하나만 출력하십시오. "
    "stance는 aggressive/neutral/defensive 중 하나, confidence는 0.0~1.0. "
    "adjustments에는 조정을 제안하고 싶은 노브만 넣으십시오(강제 아님): "
    "max_position_pct(종목당 최대 비중, 소수분율), min_cash_ratio(최소 현금 비율), "
    "max_positions(최대 보유 종목 수, 정수), stop_loss_pct(손절, 소수분율 예 0.07=7%), "
    "take_profit_pct(익절, 소수분율), max_trade_notional_pct(1건당 명목 상한, "
    "퍼센트 단위 5~30 — 위 소수분율 노브들과 달리 0.15가 아니라 15처럼 그대로 "
    "퍼센트 숫자로 제안), consensus_threshold(4-에이전트 토론의 매수/매도 합의 "
    "문턱, 소수분율 0.60~0.85 — 낮추면 진입 기회가 늘고 오탐도 늘며, 높이면 "
    "반대), "
    "target_vol_pct(변동성 타게팅 기준, 퍼센트 10~40 — 이 변동성에서 전량 "
    "사이즈로 간다. 시장 실현변동성이 이보다 높으면 노출을 줄인다), "
    "vol_multiplier_min(변동성 축소 하한, 분율 0.2~0.8 — 아무리 변동성이 "
    "높아도 이 배수 아래로는 안 줄인다). "
    "제안 값은 현행 값에서 크게 벗어나면 "
    "시스템이 안전 한도로 잘라냅니다.\n"
    "이 둘은 따로 노는 노브가 아니라 하나의 축소 배수를 만듭니다: "
    "m_vol = clamp(target_vol_pct ÷ 시장 실현변동성, vol_multiplier_min, 1.0), "
    "목표 노출도 = 레짐앵커(일일 변화 한도로 제한) × m_vol × 낙폭배수. "
    "양방향을 같은 무게로 적으면:\n"
    "- vol_multiplier_min을 **낮추면** 같은 변동성에서 더 깊이 줄어듭니다"
    "(변동성 방어를 더 세게 두는 선택). **올리면** 방어가 깎을 수 있는 폭 "
    "자체가 줄어 고변동성 국면에서 노출이 덜 줄어듭니다(방어를 그만큼 "
    "약하게 두는 선택). 이 노브는 노출도의 레버이기 전에 **변동성 방어의 "
    "세기**입니다.\n"
    "- target_vol_pct를 **낮추면** 같은 변동성에서 더 줄어들고 **올리면** 덜 "
    "줄어듭니다. 단 배수는 **축소 전용**이라 나눗셈 결과가 1.0을 넘어도 "
    "1.0에서 잘립니다 — 올리는 것만으로 앵커 위로는 못 갑니다.\n"
    "- 반대쪽에도 끝이 있습니다: 실현변동성이 충분히 높아 나눗셈 결과가 "
    "vol_multiplier_min 아래로 내려가면 m_vol은 그 하한에 고정되고, **그 "
    "구간에서는 target_vol_pct를 허용 범위 안에서 어떻게 바꿔도 m_vol이 "
    "1bp도 변하지 않습니다**(그 구간의 값을 정하는 것은 vol_multiplier_min "
    "뿐입니다).\n"
    "지금 어느 구간에 있는지, 각 노브가 실제로 무엇을 바꾸는지(허용 범위·"
    "하한을 벗어나는 데 필요한 값·1회 EOD당 이동 한도 포함), 각 선택이 "
    "목표를 어디로 수렴시키는지는 컨텍스트의 exposure_mechanics 블록에 "
    "실제 값으로 들어 있습니다 — 그 숫자를 근거로 판단하십시오."
)

PANELISTS: dict[str, str] = {
    "performance_reviewer": (
        "당신은 트레이딩 성과 리뷰어입니다. 오늘의 EOD 리뷰(포트폴리오 손익, "
        "종목별 실현손익, thesis_valid)와 최근 성과 시계열을 근거로 '무엇이 "
        "작동했고 무엇이 손실을 냈는지'를 판정하고, 내일의 전략 스탠스"
        "(aggressive/neutral/defensive)와 노브 조정을 제안하십시오. 데이터에 "
        "없는 사실을 만들지 마십시오. " + _SCHEMA_INSTRUCTION
    ),
    "regime_strategist": (
        "당신은 시장 레짐 전략가입니다. 레짐 스냅샷 시계열(risk_on/risk_off/"
        "neutral, breadth_ratio)에 더해 KOSPI/KOSDAQ 지수 등락률, 외국인/기관 "
        "수급(순매매액), 파생 시장심리(market_sentiment_label/sentiment_score)의 "
        "추세를 근거로, 현행 전략이 레짐에 맞는지 판정하고 내일의 전략 스탠스와 "
        "노브 조정을 제안하십시오. 지수·수급·심리 데이터가 없으면(과거 breadth만 "
        "있는 날) breadth로만 판단하되 낮은 confidence로 답하십시오. "
        + _SCHEMA_INSTRUCTION
    ),
    "risk_officer": (
        "당신은 리스크 관리자입니다. 노출도(exposure)·집중도(concentration)·"
        "누적수익률·승패 분포·에이전트 적중률(calibration)을 근거로 사이징과 "
        "손절/익절 노브가 적절한지 판정하십시오. 손실 확대 국면에서는 defensive "
        "스탠스와 보수적 노브(작은 max_position_pct, 높은 min_cash_ratio, 타이트한 "
        "stop_loss_pct)를 제안하는 것이 당신의 책무입니다. " + _SCHEMA_INSTRUCTION
    ),
}


# ---------------------------------------------------------------------------
# exposure_mechanics — 패널이 자기가 돌리는 노브의 효과를 볼 수 있게 하는 블록
#
# 2026-08-11 라이브에서 드러난 것: 실현변동성이 101.7%까지 오르자
# `m_vol = clamp(22.0/101.7, 0.5, 1.0)`가 **하한에 박혔고**, 그 구간에서는
# `target_vol_pct`가 산수에서 통째로 소거된다(하한을 벗어나려면 50.9가
# 필요한데 그 노브의 허용 상한은 40이다). 패널은 전날 EOD에 정확히 그
# 무효인 노브를 18→22로 올렸다 -- 값은 정상 적용됐고 클램프도 안 걸려
# `strategy_knob_discarded`조차 나지 않으니, 패널에게는 자기 투표가
# 무효였다는 것을 알 방법이 없었다.
#
# 그래서 **사실만** 준다: 지금 어디에 묶여 있는지, 그것을 푸는 데 필요한
# 값이 허용 범위 안인지 밖인지, 같은 설정이 유지되면 목표가 어디로
# 수렴하는지. 무엇을 할지는 패널이 정한다.
#
# ⚠️ 전부 **라이브 상태에서 계산한다**. 하드코딩한 설명문은 변동성이
# 바뀌는 순간 조용히 틀려지고, 이 리포는 그 결함을 반복해 왔다.
# ---------------------------------------------------------------------------

_EXPOSURE_FORMULA = (
    "목표 = clamp(레짐앵커, 직전목표 ± daily_ramp_max) × m_vol × m_drawdown, "
    "m_vol = clamp(target_vol_pct ÷ 실현변동성(연율,%), vol_multiplier_min, 1.0)"
)

_CONVERGENCE_ASSUMES = (
    "같은 레짐 라벨·같은 실현변동성·같은 노브가 유지되고 m_drawdown=1.0일 때 "
    "목표가 반복 적용으로 수렴하는 값. min(daily_ramp_max×m/(1−m), 앵커×m)."
)


def convergence_target_pct(
    anchor_pct: float, m: float, ramp: float = DAILY_TARGET_DELTA_MAX
) -> tuple[float, str]:
    """사상 `f(p) = min(anchor, p + ramp) × m`의 고정점과, 무엇이 그것을 정했는지.

    - 앵커가 구속하지 않으면 `p* = ramp × m / (1 − m)` ("ramp")
    - 앵커가 구속하면 `p* = anchor × m` ("anchor")
    - 실제 수렴점은 둘 중 **작은 값**

    ⚠️ `m ≥ 1.0`이면 첫 식이 발산한다 -- 0으로 나누지 않고 `anchor × m`을
    돌려준다(축소 전용 계약상 `m > 1.0`은 나오지 않지만 방어한다).
    """
    by_anchor = anchor_pct * m
    if m <= 0.0:
        return 0.0, "m_vol"
    if m >= 1.0:
        return by_anchor, "anchor"
    by_ramp = ramp * m / (1.0 - m)
    return (by_ramp, "ramp") if by_ramp < by_anchor else (by_anchor, "anchor")


def _as_float(value: Any) -> Optional[float]:
    """숫자면 float, 아니면 None. NaN/±inf도 None이다 -- 그런 값이 블록에
    실리면 패널이 그것을 측정값으로 읽는다."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


# `m_vol`을 움직이는 `target_vol_pct`를 찾을 때 훑는 상한. 노브의 허용
# 상한(40)보다 훨씬 크게 잡는 이유는 **허용 범위 밖이라는 사실 자체가
# 패널이 알아야 할 답**이기 때문이다 -- 40에서 멈춰 탐색하면 "그런 값이
# 없다"와 "손이 안 닿는다"가 구별되지 않는다.
_TARGET_VOL_SEARCH_MAX: float = 1e6
_BISECTION_STEPS: int = 200


def _mechanics_skeleton() -> dict:
    """블록의 **키 집합**. 정상 경로도 실패 경로도 이 스켈레톤에서 출발한다 --
    실패했다고 키를 생략하면 '데이터 없음'과 '기능 없음'이 구별되지 않는다
    (리뷰 M5). 두 경로가 같은 생성자를 쓰므로 키가 어긋날 수 없다."""
    return {
        "status": "unavailable",
        "unknown": [],
        "formula": _EXPOSURE_FORMULA,
        "projection_degraded": None,

        "realized_vol_annualized_pct": None,
        "realized_vol_samples": 0,
        "index_latest_date": None,
        "index_series_stale": None,

        "target_vol_pct": None,
        "vol_multiplier_min": None,
        "m_vol_unclamped": None,
        "m_vol": None,
        "m_vol_binding": "unknown",
        "m_drawdown_used": None,

        "regime_label": None,
        "regime_anchor_pct": None,
        "daily_ramp_max": DAILY_TARGET_DELTA_MAX,
        "prev_target_pct": None,
        "ramped_pct": None,
        "anchor_is_binding": None,
        "next_target_pct_projected": None,
        "next_target_assumes": None,
        "next_target_clamp_range": [EXPOSURE_FLOOR, TARGET_CEILING],

        "current_target_pct": None,
        "actual_exposure_pct": None,
        "actual_exposure_as_of": None,

        "target_vol_pct_to_lift_m_vol": None,
        "target_vol_pct_allowed_range": list(KNOB_BOUNDS["target_vol_pct"]),
        "target_vol_pct_can_lift_m_vol": None,
        "target_vol_pct_can_lower_m_vol": None,
        "vol_multiplier_min_allowed_range": list(KNOB_BOUNDS["vol_multiplier_min"]),
        "knob_max_relative_move_per_eod": MAX_RELATIVE_DELTA,

        "convergence": {
            "assumes": _CONVERGENCE_ASSUMES,
            "target_pct": None,
            "binds_on": None,
            "by_regime_anchor": None,
            "by_vol_multiplier_min": None,
        },
    }


def _m_vol_probe_threshold(probe, m_now: float, lo: float) -> Optional[float]:
    """`m_vol`이 지금 값보다 커지기 시작하는 `target_vol_pct`. 없으면 None.

    **엔진을 오라클로 쓴다** -- 산식을 여기서 뒤집지 않는다(사본이 있으면
    엔진이 바뀔 때 어긋나고, 어느 쪽이 맞는지 알 수 없다). `probe`는
    `target_vol_pct → m_vol`이고 단조 비감소라 이분법이 성립한다.
    """
    if probe(_TARGET_VOL_SEARCH_MAX) <= m_now:
        # 아무리 올려도 안 움직인다 -- 배수가 이미 천장이거나, 열화 분기가
        # 이 노브와 무관하게 값을 정하고 있다.
        return None
    lo_v, hi_v = lo, _TARGET_VOL_SEARCH_MAX
    for _ in range(_BISECTION_STEPS):
        mid = (lo_v + hi_v) / 2.0
        if mid <= lo_v or mid >= hi_v:
            break
        if probe(mid) > m_now:
            hi_v = mid
        else:
            lo_v = mid
    return hi_v


def _eod_runs_to_reach(current: Optional[float], target: float) -> Optional[int]:
    """현행 값에서 목표 값에 닿는 데 필요한 최소 EOD 횟수.

    1회당 `MAX_RELATIVE_DELTA`(=25%) 상대 이동이 상한이라(`_bounded`)
    0.5 → 0.8은 한 번에 못 간다. 표에 이것이 없으면 즉시 도달 가능한
    선택지로 보인다(리뷰 M8).
    """
    if current is None or current <= 0 or target <= 0:
        return None
    if math.isclose(current, target, rel_tol=1e-9):
        return 0
    step = 1.0 + MAX_RELATIVE_DELTA if target > current else 1.0 - MAX_RELATIVE_DELTA
    return max(1, math.ceil(math.log(target / current) / math.log(step)))


def _vol_min_candidates(current: Optional[float]) -> list[float]:
    """`vol_multiplier_min`의 허용 범위를 훑는 후보값. 범위는 KNOB_BOUNDS에서
    읽는다 -- 표를 손으로 적어두면 바운드가 바뀌는 날 조용히 틀려진다.

    큐레이션이 아니라 **전 구간 균등 훑기**다. 현행 값이 격자에 없으면
    끼워넣는다(자기 위치가 표에 없으면 비교가 안 된다)."""
    lo, hi = KNOB_BOUNDS["vol_multiplier_min"]
    step = 0.1
    out: list[float] = []
    x = lo
    while x <= hi + 1e-9:
        out.append(round(x, 2))
        x += step
    if current is not None and lo <= current <= hi:
        out.append(round(current, 2))
    return sorted(set(out))


async def _exposure_mechanics(storage: Any, knobs: dict) -> dict:
    """노출도 산식의 **현재 상태**. 절대 raise하지 않는다.

    ⚠️ **엔진의 열화 규칙을 두 번째로 복사하지 않는다**(2026-08-11 리뷰,
    Important 3). `m_vol`도, 열화 시 폴백도, 다음 목표도 전부
    `compute_regime_target`을 **직접 호출해** 얻는다 -- 그 함수가 시계열
    노후/표본 부족에서 무엇을 하든 블록은 자동으로 따라간다. 사본을 두면
    엔진이 바뀌는 날(예: `fix/index-series-fail-closed`의 fail-closed
    폴백 `m_vol = min(1.0, vol_multiplier_min)`) 블록이 조용히 거짓말을
    시작하고, 어느 쪽이 맞는지 알 수 없다.

    노브가 실제로 무엇을 바꾸는지도 산식을 뒤집지 않고 **엔진을 오라클로
    탐침**해서 답한다.

    전략 재평가는 하루 한 번뿐이라 여기서 예외가 나면 그날 전략이 통째로
    갱신되지 않는다. 그래서 모르는 값은 `None` + `unknown` 목록으로
    남기고 진행한다 -- 그럴듯한 기본값을 채우면 패널이 그것을 사실로
    읽는다.
    """
    block = _mechanics_skeleton()
    unknown: list[str] = []

    target_vol = _as_float(knobs.get("target_vol_pct"))
    vol_min = _as_float(knobs.get("vol_multiplier_min"))
    block["target_vol_pct"] = target_vol
    block["vol_multiplier_min"] = vol_min
    if target_vol is None:
        unknown.append("target_vol_pct")
    if vol_min is None:
        unknown.append("vol_multiplier_min")

    # --- 지수 시계열 (엔진 입력 그대로)
    try:
        closes = await storage.get_recent_index_closes(limit=VOL_WINDOW + 1)
    except Exception as e:
        logger.warning(f"[StrategyPanel] index closes unavailable: {e}")
        closes = []
        unknown.append("index_series")
    returns = closes_to_returns([c for _, c in closes]) if closes else []
    if closes:
        block["index_latest_date"] = closes[-1][0]
        block["index_series_stale"] = is_series_stale(closes[-1][0], date.today())

    # --- 레짐 판정 (앵커·직전 목표)
    judgment: Optional[dict] = None
    try:
        judgment = await storage.get_latest_regime_judgment()
    except Exception as e:
        logger.warning(f"[StrategyPanel] regime judgment unavailable: {e}")
        unknown.append("regime_judgment")
    regime_label = (judgment or {}).get("regime")
    known_label = regime_label if regime_label in REGIME_ANCHORS else None
    if known_label is None:
        unknown.append("regime_anchor")
    prev_target = _as_float((judgment or {}).get("effective_target_pct"))
    block["regime_label"] = regime_label
    block["prev_target_pct"] = prev_target
    block["current_target_pct"] = prev_target

    # --- 실제 노출도 · 낙폭 배수 입력 (관측 원장)
    shadow: Optional[dict] = None
    try:
        shadow = await storage.get_latest_exposure_shadow()
    except Exception as e:
        logger.warning(f"[StrategyPanel] exposure shadow unavailable: {e}")
        unknown.append("exposure_shadow")
    else:
        if shadow is None:
            # 행이 **없는** 것도 모르는 것이다 -- 예외만 unknown에 넣으면
            # regime_anchor 쪽과 비대칭이 된다(리뷰 M6).
            unknown.append("exposure_shadow")
    actual_pct = _as_float((shadow or {}).get("actual_pct"))
    equity = _as_float((shadow or {}).get("equity"))
    equity_peak = _as_float((shadow or {}).get("equity_peak"))
    block["actual_exposure_pct"] = actual_pct
    block["actual_exposure_as_of"] = (shadow or {}).get("created_at")

    if target_vol is None or vol_min is None:
        # 노브를 모르면 엔진을 부를 수 없다 -- 모듈 기본값으로 대신 부르면
        # 그 결과가 현행 상태로 읽힌다.
        block["unknown"] = unknown
        block["status"] = "partial"
        return block

    # --- 여기서부터는 전부 엔진에서 파생한다 -------------------------------
    stale = bool(block["index_series_stale"])
    drawdown_known = equity is not None and equity_peak is not None
    if not drawdown_known:
        # 낙폭 배수를 모른다. 1.0(무감쇠)으로 두되 **모른다고 적는다** --
        # 실제 다음 목표는 이보다 낮을 수 있다.
        equity, equity_peak = 1.0, 1.0
        unknown.append("m_drawdown")

    def engine(*, label: str, tv: Optional[float] = None,
               vmin: Optional[float] = None):
        return compute_regime_target(
            regime_label=label,
            prev_effective_pct=prev_target,
            seed_actual_pct=actual_pct if actual_pct is not None else 0.0,
            index_returns=returns,
            equity=equity,
            equity_peak=equity_peak,
            series_stale=stale,
            target_vol_pct=target_vol if tv is None else tv,
            vol_multiplier_min=vol_min if vmin is None else vmin,
        )

    # 레짐 라벨별 계산. `m_vol`은 라벨과 무관해야 하지만 그것도 **확인해서**
    # 쓴다 -- 엔진의 구조를 가정하지 않는다.
    per_anchor = {label: engine(label=label) for label in REGIME_ANCHORS}
    m_vols = {t.m_vol for t in per_anchor.values()}

    primary = per_anchor[known_label] if known_label else None
    if primary is not None:
        m_vol = primary.m_vol
        block["regime_anchor_pct"] = primary.anchor_pct
        block["projection_degraded"] = list(primary.degraded)
    elif len(m_vols) == 1:
        m_vol = next(iter(m_vols))
        block["projection_degraded"] = sorted(
            {tag for t in per_anchor.values() for tag in t.degraded}
            - {"regime_unknown"}
        )
    else:
        m_vol = None
        unknown.append("m_vol_label_dependent")

    any_target = next(iter(per_anchor.values()))
    vol_ann = any_target.index_vol_annualized
    block["realized_vol_annualized_pct"] = vol_ann
    block["realized_vol_samples"] = any_target.index_vol_n
    if vol_ann is None:
        unknown.append("realized_vol")
    else:
        block["m_vol_unclamped"] = target_vol / vol_ann
    block["m_vol"] = m_vol
    block["m_drawdown_used"] = any_target.m_drawdown

    # --- 이 노브가 지금 무엇을 바꾸는가: 엔진 탐침 (산식 역산 없음)
    if m_vol is not None:
        probe_label = known_label or "bear"   # m_vol은 라벨과 무관(위에서 확인)

        def probe(tv: float) -> float:
            return engine(label=probe_label, tv=tv).m_vol

        tv_lo, tv_hi = KNOB_BOUNDS["target_vol_pct"]
        can_lift = probe(tv_hi) > m_vol
        can_lower = probe(tv_lo) < m_vol
        block["target_vol_pct_can_lift_m_vol"] = can_lift
        block["target_vol_pct_can_lower_m_vol"] = can_lower
        block["target_vol_pct_to_lift_m_vol"] = _m_vol_probe_threshold(
            probe, m_vol, tv_lo
        )

        # 배수가 어디에 묶여 있는가. 노브를 허용 양끝으로 밀어도 안 움직이면
        # 묶인 것이고, 그 위치가 하한인지 천장인지는 값으로 판정한다.
        if can_lift or can_lower:
            block["m_vol_binding"] = "free"
        elif math.isclose(m_vol, vol_min, rel_tol=1e-12, abs_tol=1e-12):
            block["m_vol_binding"] = "floor"
        elif math.isclose(m_vol, VOL_MULTIPLIER_MAX, rel_tol=1e-12, abs_tol=1e-12):
            block["m_vol_binding"] = "ceiling"
        else:
            block["m_vol_binding"] = "pinned"

    # --- 램프가 앵커를 붙잡고 있는가 · 다음 목표 (엔진 값 그대로)
    if primary is not None:
        anchor = primary.anchor_pct
        if prev_target is not None:
            ramped = max(prev_target - DAILY_TARGET_DELTA_MAX,
                         min(anchor, prev_target + DAILY_TARGET_DELTA_MAX))
            block["ramped_pct"] = ramped
            block["anchor_is_binding"] = ramped == anchor
        # ⚠️ 엔진이 낸 `target_pct`를 그대로 쓴다 -- `ramped × m_vol`로
        # 재계산하면 `m_drawdown`과 [0.02, 0.80] 클램프가 빠져 낙폭
        # 국면에서 최대 233% 과대가 된다(리뷰 Important 2).
        block["next_target_pct_projected"] = primary.target_pct
        block["next_target_assumes"] = (
            "레짐 라벨·실현변동성·노브가 오늘과 같을 때 엔진이 낼 다음 목표. "
            "m_drawdown과 [0.02, 0.80] 클램프가 **포함**된 값이다"
            + (
                f" (m_drawdown={primary.m_drawdown:.4f}, "
                "exposure_shadow 최신 행의 equity/고점 기준)."
                if drawdown_known
                else " — 단 equity/고점을 못 읽어 m_drawdown을 1.0으로 뒀다. "
                "실제 다음 목표는 이보다 낮을 수 있다."
            )
        )

    # --- 수렴점 (m_drawdown은 빼고 본다: assumes에 명시)
    if m_vol is not None:
        block["convergence"]["by_regime_anchor"] = {
            label: convergence_target_pct(t.anchor_pct, t.m_vol)[0]
            for label, t in per_anchor.items()
        }
        if primary is not None:
            conv_pct, conv_binds = convergence_target_pct(primary.anchor_pct, m_vol)
            block["convergence"]["target_pct"] = conv_pct
            block["convergence"]["binds_on"] = conv_binds
            table: dict = {}
            for cand in _vol_min_candidates(vol_min):
                # ⚠️ 후보별 `m_vol`도 엔진이 낸다 -- 여기서 클램프를 흉내내면
                # 열화 상태(시계열 노후·표본 부족)에서 표가 실제와 어긋난다.
                cand_target = engine(label=known_label, vmin=cand)
                cand_pct, cand_binds = convergence_target_pct(
                    cand_target.anchor_pct, cand_target.m_vol
                )
                table[f"{cand:g}"] = {
                    "m_vol": cand_target.m_vol,
                    "target_pct": cand_pct,
                    "binds_on": cand_binds,
                    "min_eod_runs": _eod_runs_to_reach(vol_min, cand),
                }
            block["convergence"]["by_vol_multiplier_min"] = table

    block["unknown"] = unknown
    block["status"] = "partial" if unknown else "ok"
    return block


def _latest_per_key(rows: list[dict], key: str) -> list[dict]:
    """Accrete 원장(같은 키로 재실행 시 append)에서 키별 최신 행만.
    rows는 created_at DESC로 들어오므로 첫 등장이 최신이다."""
    seen: set = set()
    out: list[dict] = []
    for row in rows:
        k = row.get(key)
        if k in seen:
            continue
        seen.add(k)
        out.append(row)
    return out


async def build_strategy_context(
    storage: Any, trade_date: str, current_strategy_knobs: dict
) -> Optional[dict]:
    """Assemble the panel's shared evidence. None = not enough data to hold
    a meaningful debate (no/error-only EOD review for `trade_date`) — the
    orchestrator then skips the run entirely."""
    reviews = await storage.get_eod_reviews(limit=40)
    today_row = next((r for r in reviews if r.get("trade_date") == trade_date), None)
    if today_row is None:
        return None
    try:
        report = json.loads(today_row.get("report_json") or "{}")
    except (TypeError, ValueError):
        return None
    if not report or (report.get("error") and not report.get("portfolio")):
        return None

    regimes = _latest_per_key(await storage.get_regime_snapshots(limit=60), "trade_date")
    perf = await storage.get_daily_perf_snapshots(limit=_PERF_ROWS)
    calibration = _latest_per_key(
        await storage.get_agent_calibration(as_of_date=trade_date), "agent_type"
    )

    # DS-5 폐루프(spec §6): 전략별 발굴 성과(승격/미승격·평균 fwd 수익률·
    # 적중률)를 패널 근거에 추가 — 패널리스트가 발굴이 실제로 통했는지를
    # 참고해 스탠스/노브를 조정할 수 있게 한다. 조회 실패는 패널 자체를
    # 죽이지 않고 그냥 None(패널의 나머지 기존 거동은 불변).
    try:
        discovery_performance = await get_discovery_performance(
            storage, days=_DISCOVERY_PERFORMANCE_DAYS
        )
    except Exception as e:
        logger.warning(f"[StrategyPanel] get_discovery_performance failed: {e}")
        discovery_performance = None

    # 노출도 역학. `_exposure_mechanics`가 자체적으로 never-raise지만, 여기서
    # 한 겹 더 받는다 -- 이 블록 하나가 EOD 전략 갱신 전체를 멈추면
    # 그날 전략이 통째로 안 바뀐다(재평가는 하루 한 번뿐이다).
    try:
        exposure_mechanics = await _exposure_mechanics(storage, current_strategy_knobs or {})
    except Exception as e:
        logger.warning(f"[StrategyPanel] exposure mechanics failed: {e}")
        # 같은 스켈레톤에서 출발한다 -- 실패했다고 키를 생략하면 패널이
        # "데이터 없음"과 "기능 없음"을 구별할 수 없다(리뷰 M5).
        exposure_mechanics = _mechanics_skeleton()
        exposure_mechanics["status"] = "error"
        exposure_mechanics["unknown"] = ["all"]
        exposure_mechanics["error"] = str(e)

    return {
        "trade_date": trade_date,
        "eod_review": report,
        "regime_history": [
            {
                "trade_date": r.get("trade_date"),
                "id": r.get("id"),
                "regime_label": r.get("regime_label"),
                "breadth_ratio": r.get("breadth_ratio"),
                "market_sentiment_label": r.get("market_sentiment_label"),
                "sentiment_score": r.get("sentiment_score"),
                "index_kospi_chg_pct": r.get("index_kospi_chg_pct"),
                "index_kosdaq_chg_pct": r.get("index_kosdaq_chg_pct"),
                "foreign_net_amount": r.get("foreign_net_amount"),
                "institution_net_amount": r.get("institution_net_amount"),
            }
            for r in regimes[:_REGIME_DAYS]
        ],
        "perf_history": [
            {
                "trade_date": p.get("trade_date"),
                "equity": p.get("equity"),
                "net_pnl": p.get("net_pnl"),
                "win_trades": p.get("win_trades"),
                "loss_trades": p.get("loss_trades"),
                "cumulative_return_pct": p.get("cumulative_return_pct"),
            }
            for p in perf
        ],
        "calibration": [
            {
                "agent_type": c.get("agent_type"),
                "accuracy": c.get("accuracy"),
                "decisions_scored": c.get("decisions_scored"),
                "avg_confidence": c.get("avg_confidence"),
            }
            for c in calibration
        ],
        "current_strategy": current_strategy_knobs,
        "discovery_performance": discovery_performance,
        "exposure_mechanics": exposure_mechanics,
    }


async def _panelist_vote(name: str, system_prompt: str, user_prompt: str) -> dict:
    """One structured vote. Any failure -> {"panelist", "error"} — explicit,
    never a plausible-looking default (the base_agent error-string swallow
    is exactly what we refuse to inherit)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        vote = await get_llm_provider().generate_structured(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
            STRATEGY_VOTE_SCHEMA,
            task=TaskType.STRATEGIC_DECISION,
        )
        return {**vote, "panelist": name}
    except Exception as e:
        logger.warning(f"[StrategyPanel] {name} vote failed: {e}")
        return {"panelist": name, "error": str(e)}


async def run_strategy_panel(context: dict) -> list[dict]:
    """All panelists in parallel over the same evidence. Always returns one
    entry per panelist (vote or error) — the electorate math downstream
    decides what counts."""
    user_prompt = (
        "다음은 오늘의 EOD 종합 데이터입니다. 이를 근거로 전략 스탠스와 "
        "노브 조정을 투표하십시오.\n\n"
        + json.dumps(context, ensure_ascii=False, default=str)
    )
    tasks = [
        _panelist_vote(name, prompt, user_prompt)
        for name, prompt in PANELISTS.items()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    votes: list[dict] = []
    for name, result in zip(PANELISTS, results):
        if isinstance(result, BaseException):  # gather 방어 — _panelist_vote는 삼키지만
            votes.append({"panelist": name, "error": str(result)})
        else:
            votes.append(result)
    return votes
