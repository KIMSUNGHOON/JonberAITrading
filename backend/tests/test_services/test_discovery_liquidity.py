"""유동성 계산 순수 함수 테스트.

빅솔론(093190) 실측값을 회귀 픽스처로 고정한다 — ADTV 중앙값 1.2억,
계좌 5억(포지션 2000만원)에서 참여율 16.1%. 이 종목이 반드시 게이트에서
탈락하는 것이 이 아크 전체의 수용 기준이다.
"""

import pandas as pd
import pytest

from services.discovery.liquidity import (
    GATE_PARTICIPATION_PCT,
    HARD_FLOOR_ADTV,
    SIZING_PARTICIPATION_PCT,
    adtv_median,
    downside_consistency_ok,
    has_zero_volume_day,
    liquidity_cap_value,
    liquidity_gate_score,
    participation_rate,
    required_min_adtv,
)

억 = 100_000_000.0


def _df(values, volumes=None):
    n = len(values)
    vols = volumes if volumes is not None else [1000] * n
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n, freq="B"),
        "close": [1000] * n,
        "volume": vols,
        "value": [float(v) for v in values],
    })


# --- adtv_median ---

def test_adtv_median_uses_median_not_mean():
    """급등 하루의 스파이크가 평균을 끌어올리는 것을 중앙값이 차단한다."""
    values = [1 * 억] * 19 + [100 * 억]   # 평균 ≈ 5.95억, 중앙값 = 1억
    assert adtv_median(_df(values)) == pytest.approx(1 * 억)


def test_adtv_median_uses_last_20_only():
    values = [50 * 억] * 10 + [2 * 억] * 20   # 최근 20일은 전부 2억
    assert adtv_median(_df(values)) == pytest.approx(2 * 억)


def test_adtv_median_returns_none_when_insufficient():
    assert adtv_median(_df([1 * 억] * 9)) is None


def test_adtv_median_returns_none_without_value_column():
    """구 캐시(value 컬럼 없음)에서 KeyError 대신 None."""
    df = pd.DataFrame({"close": [1000] * 20, "volume": [1] * 20})
    assert adtv_median(df) is None


def test_bixolon_regression_adtv():
    """빅솔론 실측 20일 거래대금 — 중앙값 약 1.2억."""
    values = [0.70, 2.42, 1.09, 0.69, 0.32, 0.90, 1.5, 1.1, 1.3, 0.8,
              1.2, 1.4, 0.95, 1.25, 1.15, 1.35, 1.05, 0.85, 1.45, 1.6]
    adtv = adtv_median(_df([v * 억 for v in values]))
    assert 1.0 * 억 <= adtv <= 1.4 * 억


# --- required_min_adtv / participation_rate ---

def test_required_min_adtv_is_position_over_one_percent():
    assert required_min_adtv(20_000_000) == pytest.approx(20 * 억)


def test_required_min_adtv_respects_hard_floor():
    """소액 포지션이라도 10억 하드플로어는 절대 뚫리지 않는다."""
    assert required_min_adtv(1_000_000) == HARD_FLOOR_ADTV


def test_participation_rate_bixolon():
    assert participation_rate(20_000_000, 1.24 * 억) == pytest.approx(0.1613, abs=1e-3)


def test_participation_rate_none_on_zero_adtv():
    assert participation_rate(20_000_000, 0) is None
    assert participation_rate(20_000_000, None) is None


# --- liquidity_cap_value ---

def test_liquidity_cap_is_half_percent():
    assert liquidity_cap_value(40 * 억) == pytest.approx(20_000_000)
    assert liquidity_cap_value(20 * 억) == pytest.approx(10_000_000)


def test_liquidity_cap_none_when_adtv_missing():
    assert liquidity_cap_value(None) is None


# --- liquidity_gate_score (로그 스케일) ---

def test_gate_score_log_scale_endpoints():
    assert liquidity_gate_score(10 * 억) == pytest.approx(0.0, abs=1e-6)
    assert liquidity_gate_score(100 * 억) == pytest.approx(1.0, abs=1e-6)


def test_gate_score_clamped_outside_range():
    assert liquidity_gate_score(1 * 억) == 0.0
    assert liquidity_gate_score(1000 * 억) == 1.0
    assert liquidity_gate_score(None) == 0.0


def test_gate_score_a1_survivor_floor():
    """A1 게이트(20억)를 통과한 종목은 liq_gate >= 0.30 (스펙 §3.4)."""
    assert liquidity_gate_score(20 * 억) >= 0.30


# --- downside_consistency / zero volume ---

def test_downside_consistency_allows_five_violations():
    values = [20 * 억] * 15 + [5 * 억] * 5      # 위반 5일 = 경계 통과
    assert downside_consistency_ok(_df(values), 20 * 억) is True


def test_downside_consistency_rejects_six_violations():
    values = [20 * 억] * 14 + [5 * 억] * 6
    assert downside_consistency_ok(_df(values), 20 * 억) is False


def test_downside_consistency_floor_ratio_is_60_percent():
    """min_adtv의 60% 이상이면 위반이 아니다 (20억 기준 12억)."""
    values = [12.1 * 억] * 20
    assert downside_consistency_ok(_df(values), 20 * 억) is True


def test_zero_volume_day_detected():
    assert has_zero_volume_day(_df([1 * 억] * 20, volumes=[100] * 19 + [0])) is True
    assert has_zero_volume_day(_df([1 * 억] * 20)) is False
