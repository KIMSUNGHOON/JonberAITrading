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
