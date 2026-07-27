"""C1: 유동성 반응형 사이징 캡.

게이트(참여율 1%)를 통과한 종목도 유동성에 비례해 포지션을 줄인다. 게이트가
'진입 자격', 이 캡이 '실제 크기'다."""

import pytest

from services.trading.r_sizing import SKIP_MIN_EQUITY_PCT, apply_liquidity_cap

억 = 100_000_000.0
EQUITY = 500_000_000.0


def test_no_cap_when_adtv_missing():
    """ADTV를 모르면 캡을 적용하지 않는다 — 이미 A1 게이트를 통과한 종목이고,
    R-cap과 4% 캡은 여전히 작동한다(fail-open, 단 경고 사유 반환)."""
    cap, reason = apply_liquidity_cap(20_000_000, None, EQUITY)
    assert cap == 20_000_000
    assert reason == "adtv_unknown"


def test_cap_binds_for_thin_stock():
    """ADTV 20억 -> 0.5% = 1000만원으로 축소."""
    cap, reason = apply_liquidity_cap(20_000_000, 20 * 억, EQUITY)
    assert cap == pytest.approx(10_000_000)
    assert reason == "liquidity_cap"


def test_cap_does_not_bind_for_liquid_stock():
    """ADTV 400억 -> 0.5% = 2억 > 기존 캡 2000만원이므로 기존 캡 유지."""
    cap, reason = apply_liquidity_cap(20_000_000, 400 * 억, EQUITY)
    assert cap == 20_000_000
    assert reason is None


def test_skip_when_cap_below_one_percent_of_equity():
    """캡이 계좌의 1%(500만원) 미만이면 0을 반환해 진입을 포기한다.

    소액 포지션은 체결단위 미달과 고정 수수료·호가단위 마찰로 실효 비용률이
    오히려 올라간다."""
    cap, reason = apply_liquidity_cap(20_000_000, 5 * 억, EQUITY)   # 0.5% = 250만원
    assert cap == 0.0
    assert reason == "liquidity_too_thin"


def test_skip_threshold_is_one_percent_of_equity():
    assert SKIP_MIN_EQUITY_PCT == pytest.approx(0.01)


def test_zero_equity_is_safe():
    cap, reason = apply_liquidity_cap(20_000_000, 20 * 억, 0.0)
    assert cap >= 0.0
