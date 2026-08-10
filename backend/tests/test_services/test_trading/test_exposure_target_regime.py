import math

import pytest

from services.trading import exposure_target as et
from services.trading.exposure_target import (
    DAILY_TARGET_DELTA_MAX,
    EXPOSURE_FLOOR,
    REGIME_ANCHORS,
    REGIME_PER_POSITION_PCT,
    TARGET_CEILING,
    TRADING_DAYS_PER_YEAR,
    VOL_MULTIPLIER_MAX,
    VOL_MULTIPLIER_MIN,
    compute_regime_target,
    slots_for_target,
)


def _returns_with_annual_vol(vol_ann_pct: float, n: int = 20) -> list[float]:
    """연변동성이 정확히 `vol_ann_pct`가 되는 일간 등락률(%) n개.

    ±a를 번갈아 놓으면 표본평균이 0, 표본표준편차가 `a·√(n/(n-1))`이다.
    거기에 √250을 곱한 값이 `annualized_vol()`의 출력이므로 역산한다 —
    "SPY 수준"을 눈대중 상수로 적지 않고 계산으로 못 박는다.
    """
    sd = vol_ann_pct / math.sqrt(TRADING_DAYS_PER_YEAR)
    a = sd / math.sqrt(n / (n - 1))
    return [a if i % 2 == 0 else -a for i in range(n)]


def _t(regime="bear", prev=None, seed=0.0855, returns=None, equity=100.0,
       peak=100.0, series_stale=False, series_lagging=False, vol_min=None):
    """기본 표본은 **목표 변동성과 정확히 같은** 18% -- `m_vol == 1.0`이라
    램프·앵커·클램프를 보는 테스트에서 배수가 잡음이 되지 않는다.

    ⚠️ 예전 기본값은 `[]`(표본 없음)였다. 2026-08-11부터 표본 부족은
    열화이고 배수가 하한(0.5)으로 떨어지므로, `[]`를 계속 기본으로 두면
    램프를 보려던 테스트가 전부 열화 경로를 타게 된다.
    """
    kw = {}
    if vol_min is not None:
        kw["vol_multiplier_min"] = vol_min
    return compute_regime_target(
        regime_label=regime,
        prev_effective_pct=prev,
        seed_actual_pct=seed,
        index_returns=(
            returns if returns is not None else _returns_with_annual_vol(18.0)
        ),
        equity=equity,
        equity_peak=peak,
        series_stale=series_stale,
        series_lagging=series_lagging,
        **kw,
    )


def test_real_kospi_volatility_is_not_rejected():
    """이 케이스가 이번 사고의 원점이다.

    실제 KOSPI 20일 실현 연변동성이 101.7%인데 옛 게이트 [5, 60]이
    그것을 "말이 안 되는 값"으로 거부해 m_vol=1.0으로 만들었다 —
    방어가 가장 필요한 날에 정확히 꺼졌다.
    """
    # 일간 ±6.4%가 20일 이어지면 연 101% 근처
    returns = [6.4, -6.4] * 10
    out = _t(returns=returns)

    assert out.index_vol_annualized is not None
    assert out.index_vol_annualized > 60.0, "실제로 게이트 밖이던 크기"
    assert "index_vol_implausible" not in out.degraded, "게이트가 남아 있다"
    assert out.m_vol == pytest.approx(0.5), "하한까지 깎여야 한다"


def test_vol_gate_constants_are_gone():
    """상수가 남아 있으면 누군가 다시 쓴다."""
    import services.trading.exposure_target as et

    assert not hasattr(et, "VOL_GATE_MIN_PCT")
    assert not hasattr(et, "VOL_GATE_MAX_PCT")


def test_stale_series_falls_back_to_the_defensive_end():
    """시계열이 오래됐으면 **가장 방어적인 배수**로 떨어진다(2026-08-11).

    이전에는 `1.0`(= 전혀 깎지 않음, 축소 전용 범위에서 가장 관대한 끝)이었다.
    변동성을 **모르는** 것을 "낮다"로 읽은 것이고, 데이터를 못 읽었다는
    이유만으로 노출도 상한이 두 배가 됐다.
    """
    out = _t(returns=[6.4, -6.4] * 10, series_stale=True)
    assert out.m_vol == pytest.approx(VOL_MULTIPLIER_MIN)
    assert out.m_vol != 1.0
    assert "index_series_stale" in out.degraded
    assert out.index_vol_annualized is not None, "원값은 그대로 실어야 한다"


def test_stale_flag_does_not_open_exposure_upward():
    """열화가 노출도를 위로 여는 일은 없어야 한다.

    ⚠️ 고변동성 표본으로 비교하면 신선한 쪽도 이미 하한(0.5)이라 두 값이
    같아져 가드가 공허해진다. **저변동성 표본**(신선하면 `m_vol=1.0`)으로
    비교해야 "열화가 관대한 끝으로 가는가"를 실제로 본다.
    """
    calm = _returns_with_annual_vol(11.1)
    fresh = _t(regime="bear", prev=0.65, returns=calm, series_stale=False)
    stale = _t(regime="bear", prev=0.65, returns=calm, series_stale=True)
    assert fresh.m_vol == pytest.approx(1.0), "저변동성이면 깎지 않는다"
    assert stale.target_pct < fresh.target_pct
    assert stale.m_vol <= 1.0


def test_anchors_are_exactly_the_specified_values():
    assert REGIME_ANCHORS == {"bull": 0.80, "neutral": 0.65, "bear": 0.55}
    assert DAILY_TARGET_DELTA_MAX == 0.15
    assert REGIME_PER_POSITION_PCT == 0.05


def test_first_run_seeds_from_actual_and_ramps_by_the_limit():
    """prev가 없으면 실제 비중에서 시드하고 한 번에 15%p만 오른다."""
    out = _t(regime="bear", prev=None, seed=0.0855)
    assert out.anchor_pct == pytest.approx(0.55)
    assert out.target_pct == pytest.approx(0.2355)


def test_ramp_reaches_anchor_in_four_steps():
    prev = 0.0855
    for _ in range(4):
        prev = _t(regime="bear", prev=prev).target_pct
    assert prev == pytest.approx(0.55)


def test_downward_move_is_also_limited():
    """강세(0.80)에서 약세로 꺾여도 한 번에 15%p만 내려간다."""
    out = _t(regime="bear", prev=0.80)
    assert out.target_pct == pytest.approx(0.65)


def test_multipliers_may_cut_faster_than_the_daily_limit():
    """방어는 한도보다 빠르게 줄일 수 있어야 한다 — 한도는 앵커에만 건다.
    낙폭 20%면 m_drawdown = 1 - 3*0.2 = 0.4."""
    out = _t(regime="bear", prev=0.50, equity=80.0, peak=100.0)
    assert out.m_drawdown == pytest.approx(0.4)
    # ramped = clamp(0.55, 0.35, 0.65) = 0.55 → 0.55 * 1.0 * 0.4 = 0.22
    assert out.target_pct == pytest.approx(0.22)
    assert out.target_pct < 0.50 - DAILY_TARGET_DELTA_MAX


def test_m_evidence_is_gone():
    """필드 자체가 사라져야 한다. `or ... is None`으로 느슨하게 쓰면
    필드가 남아 있어도 통과해 버린다."""
    out = _t()
    assert not hasattr(out, "m_evidence")


def test_unknown_regime_is_degraded_and_treated_as_bear():
    """모르는 라벨에서 중간값을 고르지 않는다 — 가장 보수적인 앵커를 쓴다."""
    out = _t(regime="sideways")
    assert "regime_unknown" in out.degraded
    assert out.anchor_pct == pytest.approx(REGIME_ANCHORS["bear"])


def test_vol_insufficient_is_recorded_not_silently_neutral():
    out = _t(returns=[0.1, 0.2])
    assert out.m_vol == pytest.approx(VOL_MULTIPLIER_MIN)
    assert out.m_vol != 1.0
    assert "index_vol_insufficient" in out.degraded


# -------------------------------------------
# 열화 폴백은 방어적인 끝으로 (2026-08-11, 외부 데이터 공백)
#
# 발단: `index_daily`에 2026-08-10(월) 종가가 통째로 빠졌다. 코드 결함이
# 아니라 Yahoo가 아직 안 올린 **외부 데이터 공백**이었다. 문제는 우리가
# 그 공백에 어떻게 반응하느냐였다 — 폴백이 `1.0`(축소 전용 범위에서 가장
# 관대한 끝)이라, 못 읽었다는 이유로 목표 노출도가 15.1% → 30.2%로 하루
# 만에 두 배가 될 수 있었다.
# -------------------------------------------


def test_degraded_fallbacks_are_the_defensive_end_not_the_permissive_one():
    """두 열화 분기 **모두** 하한으로 떨어진다.

    `VOL_MULTIPLIER_MAX == 1.0`이므로 배수 범위는 [vol_multiplier_min, 1.0]
    이고 `1.0`은 "전혀 깎지 않는다"는 뜻이다 — 범위의 관대한 끝이다.
    """
    insufficient = _t(returns=[0.1, 0.2])
    stale = _t(returns=[6.4, -6.4] * 10, series_stale=True)

    for out in (insufficient, stale):
        assert out.m_vol == pytest.approx(VOL_MULTIPLIER_MIN)
        assert out.m_vol < VOL_MULTIPLIER_MAX


def test_degraded_fallback_follows_the_panel_knob():
    """폴백은 전략 패널의 `vol_multiplier_min`을 따른다.

    패널이 이 노브를 올린 것은 "이보다 세게 방어하지 말라"는 지시이므로
    열화 폴백도 그 지시 안에 있어야 한다. 상수를 따로 박으면 노브가
    말한 하한과 폴백이 어긋난다.
    """
    for kw in ({"returns": [0.1, 0.2]},
               {"returns": [6.4, -6.4] * 10, "series_stale": True}):
        assert _t(vol_min=0.3, **kw).m_vol == pytest.approx(0.3)
        assert _t(vol_min=0.8, **kw).m_vol == pytest.approx(0.8)


def test_data_gap_cannot_double_the_target():
    """라이브 실측 회귀(2026-08-11).

    직전 목표 15.2%에서 램프하면 `ramped = 0.302`. 옛 폴백(1.0)이면
    목표가 30.2%로 **정확히 두 배**가 됐다. 새 폴백에서는 신선한 날의
    값(15.1%)을 넘지 않아야 한다.
    """
    live_vol = _returns_with_annual_vol(101.78)
    fresh = _t(regime="bear", prev=0.152, returns=live_vol)
    assert fresh.m_vol == pytest.approx(0.5)
    assert fresh.target_pct == pytest.approx(0.151)

    stale = _t(regime="bear", prev=0.152, returns=live_vol, series_stale=True)
    assert stale.target_pct <= fresh.target_pct
    assert stale.target_pct != pytest.approx(0.302)


def test_normal_path_is_unchanged():
    """회귀 가드 — 열화가 아닌 날의 산술은 손대지 않았다."""
    live_vol = _returns_with_annual_vol(101.78)
    out = _t(regime="bear", prev=0.152, returns=live_vol)
    assert out.index_vol_annualized == pytest.approx(101.78)
    assert out.m_vol == pytest.approx(0.5)          # 18.0/101.78 → 하한 0.5
    assert out.m_drawdown == pytest.approx(1.0)
    assert out.target_pct == pytest.approx(0.151)
    assert out.degraded == []

    # 목표 18%·저변동성 쪽 정상 경로도 그대로 (배수가 상한에 붙는다)
    calm = _t(regime="neutral", prev=0.65, returns=_returns_with_annual_vol(11.1))
    assert calm.m_vol == pytest.approx(1.0)
    assert calm.target_pct == pytest.approx(REGIME_ANCHORS["neutral"])
    assert calm.degraded == []


# -------------------------------------------
# 지연은 **관측 신호**다 — 배수를 바꾸지 않는다
# -------------------------------------------


def test_lagging_series_is_recorded_but_does_not_move_the_multiplier():
    """거래일 하루 뒤진 것이 20일 변동성을 의미 있게 바꾸지 않는다.

    배수를 바꾸는 것은 `series_stale`(7역일)과 표본 부족뿐이다. 지연에
    배수를 물리면 하루짜리 공백이 노출도를 흔들게 된다.
    """
    calm = _returns_with_annual_vol(11.1)
    base = _t(regime="neutral", prev=0.65, returns=calm)
    lagging = _t(regime="neutral", prev=0.65, returns=calm, series_lagging=True)

    assert "index_series_lagging" in lagging.degraded
    assert lagging.m_vol == pytest.approx(base.m_vol)
    assert lagging.target_pct == pytest.approx(base.target_pct)


def test_lag_unknown_is_a_distinct_tag():
    """달력 조회가 실패해 지연 여부를 **모르는** 것은 "지연 아님"과 다른
    사실이다. 둘을 합치면 달력이 죽은 날 공백이 영원히 안 보인다."""
    out = _t(series_lagging=None, returns=_returns_with_annual_vol(11.1))
    assert "index_series_lag_unknown" in out.degraded
    assert "index_series_lagging" not in out.degraded


def test_no_lag_tag_when_series_is_current():
    out = _t(returns=_returns_with_annual_vol(11.1), series_lagging=False)
    assert not any("lag" in tag for tag in out.degraded)


# -------------------------------------------
# C-1 (2026-08-07 최종 리뷰) — M_vol은 축소 전용이어야 한다
# -------------------------------------------


def test_vol_multiplier_never_amplifies_the_anchor():
    """배수는 앵커를 **깎기만** 한다. 1.0을 넘으면 앵커가 상한이 아니라
    출발점이 되어 사용자가 승인한 값을 넘어선다."""
    assert VOL_MULTIPLIER_MAX == 1.0


def test_spy_level_volatility_does_not_amplify():
    """실물 SPY의 20일 실현변동성(연 9~15%)에서 `m_vol`이 1.0을 넘지 않는다.

    `TARGET_VOL_PCT=18.0`은 모의 KOSPI(연 112%) 기준으로 잡힌 값이라
    `18.0/11.1 ≈ 1.62`가 나온다 — 상한이 1.5였을 때 배수가 포화하던 자리다.
    """
    out = _t(regime="bear", prev=0.65, returns=_returns_with_annual_vol(11.1))
    assert out.index_vol_annualized == pytest.approx(11.1)
    assert out.m_vol <= 1.0


def test_three_regimes_stay_distinct_at_spy_level_volatility():
    """**이 수정의 핵심 속성** — LLM의 판정이 결과에 도달해야 한다.

    상한이 1.5였을 때는 SPY 수준 변동성에서 `m_vol`이 1.5로 포화해
    `bear 0.55×1.5=0.825→0.80`, `neutral→0.80`, `bull→0.80`으로 세 레짐이
    **전부 같은 값**이 됐다(브랜치의 존재 이유가 산술로 소거).
    """
    spy = _returns_with_annual_vol(11.1)
    targets = {
        label: _t(regime=label, prev=0.65, returns=spy).target_pct
        for label in ("bull", "neutral", "bear")
    }
    assert targets["bull"] > targets["neutral"] > targets["bear"]
    assert targets["bull"] == pytest.approx(REGIME_ANCHORS["bull"])
    assert targets["neutral"] == pytest.approx(REGIME_ANCHORS["neutral"])
    assert targets["bear"] == pytest.approx(REGIME_ANCHORS["bear"])


def test_bear_can_actually_lower_the_target_above_45_percent():
    """흡수 상태가 없어야 한다.

    `m_vol>1`이면 목표가 내려가려면 `prev < 0.15·m_vol/(m_vol−1)`이어야 하고
    `m_vol=1.5`에서는 그 경계가 0.45다 — 목표가 45%를 넘으면 bear 판정이
    목표를 1bp도 못 낮췄다. 축소 전용이면 그런 흡수점이 존재할 수 없다.
    """
    spy = _returns_with_annual_vol(11.1)
    prev = 0.80
    out = _t(regime="bear", prev=prev, returns=spy)
    assert out.target_pct < prev
    # 두 번 더 돌리면 앵커까지 내려간다(±15%p 한도 안에서).
    for _ in range(2):
        out = _t(regime="bear", prev=out.target_pct, returns=spy)
    assert out.target_pct == pytest.approx(REGIME_ANCHORS["bear"])


def test_high_volatility_still_cuts():
    """축소 전용으로 만든 뒤에도 고변동성 축소는 그대로 살아 있어야 한다.
    연 30% → 18.0/30.0 = 0.6배."""
    out = _t(regime="bear", prev=0.65, returns=_returns_with_annual_vol(30.0))
    assert out.m_vol == pytest.approx(0.6)
    assert out.binding == "m_vol"
    assert out.target_pct == pytest.approx(0.55 * 0.6)


# -------------------------------------------
# binding 클램프 분기 (원장에서 이연됐던 것 — 최종 리뷰가 배포 전 필수로 승격)
# -------------------------------------------


def test_binding_ceiling_clamps_and_is_labelled():
    """이미 만기 투자 상태(실제 비중 100%)에서 최초 시드되면 램프가 앵커
    위로 올라간다 — 그때 천장이 잡고 `binding`이 그 사실을 말해야 한다."""
    out = _t(regime="bull", prev=None, seed=1.00)
    # ramped = clamp(0.80, 0.85, 1.15) = 0.85 → 배수 1.0 → 0.85 > 0.80
    assert out.target_pct == pytest.approx(TARGET_CEILING)
    assert out.binding == "ceiling"


def test_binding_floor_clamps_and_is_labelled(monkeypatch):
    """바닥 클램프 분기.

    현행 상수 조합에서는 이 분기가 도달 불가하다(최소 raw = ramped 0.15 ×
    `VOL_MULTIPLIER_MIN` 0.5 × `DRAWDOWN_FLOOR` 0.3 = 0.0225 > 0.02). 그래서
    낙폭 바닥만 낮춰 분기를 때린다 — 클램프를 지우면 이 테스트가 죽는다.
    """
    monkeypatch.setattr(et, "DRAWDOWN_FLOOR", 0.05)
    out = _t(
        regime="bear",
        prev=0.0,
        equity=10.0,
        peak=100.0,
        returns=_returns_with_annual_vol(59.9),
    )
    # ramped = 0.15, m_vol = clamp(18/60) → 0.5, m_drawdown = 0.05
    assert out.m_vol == pytest.approx(0.5)
    assert out.m_drawdown == pytest.approx(0.05)
    assert out.target_pct == pytest.approx(EXPOSURE_FLOOR)
    assert out.binding == "floor"


def test_slots_only_ever_rise():
    assert slots_for_target(0.55, current_max=7) == 11
    assert slots_for_target(0.80, current_max=11) == 16
    # 목표가 내려가도 슬롯은 안 줄어든다 — 줄이면 집중도가 오른다
    assert slots_for_target(0.20, current_max=16) == 16
    assert slots_for_target(0.2355, current_max=7) == 7
