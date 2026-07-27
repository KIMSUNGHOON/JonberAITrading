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
    assert "초과" not in text


def test_note_never_raises_on_zero_adtv():
    assert build_liquidity_note(0, 20_000_000) == ""


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
