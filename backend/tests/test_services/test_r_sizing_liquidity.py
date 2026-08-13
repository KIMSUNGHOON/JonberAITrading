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


# --- 최종 리뷰 Blocking3: skip-floor가 무로그로 비활성화되던 경로 ---
# `equity > 0`이 skip-floor 분기의 선행 조건이라 equity=0이면 분기 자체가
# 평가되지 않고 통과했고, 사유는 "liquidity_cap"/None으로만 보여 방어선이
# 빠진 상태와 정상 동작이 로그에서 구분되지 않았다. equity=0은 드문 사고가
# 아니라 확정 경로다(coordinator._state.account.total_equity 기본값 0).


def test_zero_equity_surfaces_skip_floor_disabled_reason():
    cap, reason = apply_liquidity_cap(20_000_000, 20 * 억, 0.0)
    assert reason == "skip_floor_disabled"
    # 캡 결합 자체는 평소와 동일(둘 중 작은 쪽) — 안전 방향은 유지된다.
    assert cap == pytest.approx(10_000_000)


def test_zero_equity_still_binds_cap_when_cap_is_tighter():
    """사유가 바뀌어도 유동성 캡 자체는 계속 좁힌다 — fail-open이 아니다."""
    cap, _ = apply_liquidity_cap(20_000_000, 5 * 억, 0.0)   # 0.5% = 250만원
    assert cap == pytest.approx(2_500_000)


def test_negative_equity_also_surfaces_skip_floor_disabled():
    _, reason = apply_liquidity_cap(20_000_000, 20 * 억, -1.0)
    assert reason == "skip_floor_disabled"


def test_positive_equity_reason_unchanged():
    """회귀 가드: 정상 equity에서는 기존 사유 문자열이 그대로여야 한다."""
    assert apply_liquidity_cap(20_000_000, 20 * 억, EQUITY)[1] == "liquidity_cap"
    assert apply_liquidity_cap(20_000_000, 400 * 억, EQUITY)[1] is None
    assert apply_liquidity_cap(20_000_000, 5 * 억, EQUITY)[1] == "liquidity_too_thin"


def test_adtv_unknown_wins_over_skip_floor_disabled():
    """ADTV를 아예 모르면 skip-floor 이전에 캡 자체가 불가능하다."""
    assert apply_liquidity_cap(20_000_000, None, 0.0)[1] == "adtv_unknown"
