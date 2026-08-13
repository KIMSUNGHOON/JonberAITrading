"""C2: 리스크 에이전트 유동성 한 줄 주입.

하드 게이트(A1/C1) 뒤의 보조 방어선이다. LLM 판단은 결정론적이지 않으므로
이 테스트는 '문자열이 올바르게 만들어지는지'만 검증한다."""

import pytest

from services.agent_chat.liquidity_note import build_liquidity_note

억 = 100_000_000.0


def test_note_present_when_adtv_known():
    text = build_liquidity_note(20 * 억, 20_000_000)
    assert "20.0억" in text
    assert "1.0%" in text


def test_note_omitted_when_adtv_missing():
    assert build_liquidity_note(None, 20_000_000) == ""


def test_note_omitted_when_notional_missing():
    assert build_liquidity_note(20 * 억, None) == ""
    assert build_liquidity_note(20 * 억, 0) == ""


def test_note_flags_high_participation():
    text = build_liquidity_note(5 * 억, 20_000_000)   # 참여율 4.0%
    assert "4.0%" in text
    assert "초과" in text


def test_note_no_warning_at_or_below_one_percent():
    text = build_liquidity_note(20 * 억, 20_000_000)   # 정확히 1.0%
    # 판정 지시문은 항상 "N%를 초과하면"이라는 조건절을 포함하므로 "초과"
    # 자체로는 경고 유무를 구분할 수 없다 — 경고 마커(⚠️)로 판정한다.
    assert "⚠️" not in text
    assert "청산 위험" not in text


def test_note_never_raises_on_zero_adtv():
    assert build_liquidity_note(0, 20_000_000) == ""


# --- 최종 리뷰 Blocking1: 판정 지시문은 note와 운명을 함께한다 ---
# 지시문이 프롬프트 템플릿 본문에 하드코딩돼 있으면 수치 줄만 사라지고
# "위 참여율을 판정하라"는 지시만 남는다. 그 회귀를 순수함수 층에서 핀으로
# 고정한다(왕복 배선은 test_agent_chat/test_liquidity_context_injection.py).

VERDICT_MARKER = "유동성 판정 기준"


def test_verdict_present_whenever_note_is_present():
    text = build_liquidity_note(20 * 억, 20_000_000)
    assert VERDICT_MARKER in text
    assert text.index("참여율") < text.index(VERDICT_MARKER), (
        "지시문은 반드시 자기가 참조하는 수치 줄 뒤에 와야 한다"
    )


@pytest.mark.parametrize(
    "adtv,notional",
    [
        (None, 20_000_000),      # ADTV 결측(표본 부족/빈 chart_df)
        (20 * 억, None),          # total_portfolio 결측
        (20 * 억, 0),             # notional 0
        (0, 20_000_000),         # ADTV 0
        (float("nan"), 20_000_000),
        (20 * 억, float("inf")),
    ],
)
def test_verdict_disappears_together_with_note(adtv, notional):
    """수치가 없으면 지시문도 없어야 한다 — 하나의 소스."""
    text = build_liquidity_note(adtv, notional)
    assert text == ""
    assert VERDICT_MARKER not in text


def test_verdict_threshold_follows_gate_constant():
    """문장 안의 문턱은 GATE_PARTICIPATION_PCT에서 파생돼야 한다 —
    하드코딩 '1%'면 상수 조정 시 경고 문턱과 판정 기준이 어긋난다."""
    from services.discovery.liquidity import GATE_PARTICIPATION_PCT

    text = build_liquidity_note(20 * 억, 20_000_000)
    assert f"{GATE_PARTICIPATION_PCT * 100:.0f}%를 초과하면" in text


# --- 최종 리뷰 Blocking1: 보유 포지션에 전량청산 지시로 작동하면 안 된다 ---


def test_new_entry_verdict_asks_for_opposing_vote():
    text = build_liquidity_note(5 * 억, 20_000_000, is_new_entry=True)
    assert "반대표" in text


def test_holding_verdict_forbids_forced_liquidation():
    """보유 포지션 토론에서 '반대표(SELL)'는 전량 청산 지시로 읽힌다.
    저유동성은 '더 사지 마라'의 근거이지 '지금 팔아라'의 근거가 아니다."""
    text = build_liquidity_note(5 * 억, 20_000_000, is_new_entry=False)
    assert "반대표" not in text
    assert "즉시 청산의 근거가 아닙니다" in text
    assert "슬리피지" in text
    assert "추가매수(ADD)" in text


def test_new_entry_and_holding_verdicts_differ():
    new_text = build_liquidity_note(5 * 억, 20_000_000, is_new_entry=True)
    hold_text = build_liquidity_note(5 * 억, 20_000_000, is_new_entry=False)

    def _verdict(t):
        return t[t.index(VERDICT_MARKER):]

    assert _verdict(new_text) != _verdict(hold_text)


# --- 리뷰 수정: 신규 진입 vs 기존 보유 문구 분기 ---
# 신규 후보(미보유)는 아직 실제 포지션이 없으므로 "이 포지션의 참여율"이라고
# 하면 에이전트가 "이미 그만큼 들고 있다"로 오해할 수 있다. coordinator.py가
# is_new_entry=True로 호출할 때는 문구가 달라져야 한다.


def test_note_uses_new_entry_phrasing_when_not_holding():
    text = build_liquidity_note(20 * 억, 20_000_000, is_new_entry=True)
    assert "예상 진입" in text
    assert "이 포지션의 참여율" not in text


def test_note_uses_holding_phrasing_by_default():
    text = build_liquidity_note(20 * 억, 20_000_000)
    assert "이 포지션의 참여율" in text
    assert "예상 진입" not in text
