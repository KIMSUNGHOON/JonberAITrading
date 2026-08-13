"""통지 광역화 Task 2: 발송부·수신부 공유 포맷 헬퍼.

같은 숫자를 두 곳에서 다르게 찍으면 운영자가 어느 쪽을 믿을지 모른다.
라이브에서 같은 포지션의 손익이 소스마다 3개다(596,370 / 644,350 / 644,422).
포맷만이라도 한 곳으로 모은다.

금액 3분류가 이 모듈의 핵심 계약이다:
  (a) 주문 가능한 가격 레벨(진입가·손절가·평단·현재가) → 축약 절대 금지
  (b) 집계 금액(총평가·예수금) → 축약 허용
  (c) 손익만 부호 표기. 비손익 값에 부호를 붙이면 안 된다.
"""

from datetime import datetime, timedelta

import pytest

from services.telegram.formatting import (
    display_width,
    effective_stop,
    fmt_money_short,
    fmt_pct,
    fmt_pnl,
    fmt_price,
    fmt_rel_time,
    ko_label,
    stock_label,
    strip_markers,
)


def test_fmt_price_never_abbreviates():
    """주문 가능한 가격 레벨은 축약 금지 — 13,060을 1.3만으로 쓰면 주문을 못 낸다."""
    assert fmt_price(13060) == "13,060"
    assert fmt_price(1313000) == "1,313,000"
    assert fmt_price(13060.4) == "13,060"
    assert fmt_price(None) == "―"


def test_fmt_price_has_no_sign():
    """가격 레벨에 부호를 붙이지 않는다 — _fmt_krw의 '+' 동작을 재사용하지 말 것."""
    assert not fmt_price(13060).startswith("+")


def test_fmt_money_short_abbreviates_aggregates():
    assert fmt_money_short(497_000_000) == "4.97억"
    assert fmt_money_short(17_820_000) == "1,782만"
    assert fmt_money_short(0) == "0원"
    assert fmt_money_short(None) == "―"


def test_fmt_money_short_rounding_does_not_overflow_into_10000_man():
    """99,999,999는 억 문턱(1억) 미만이라 만 분기로 가지만 n/10_000을 반올림하면
    10,000이 나온다 — "10,000만"은 곧 1억이라는 자기모순 표기다. 반올림 후
    10,000에 도달하면 억 분기로 승격해야 한다."""
    result = fmt_money_short(99_999_999)
    assert "10,000만" not in result
    assert result == "1.00억"


def test_fmt_pnl_forces_sign():
    """손익만 부호를 강제한다."""
    assert fmt_pnl(644350) == "+644,350"
    assert fmt_pnl(-3432361) == "-3,432,361"
    assert fmt_pnl(0) == "0"


def test_fmt_pct():
    assert fmt_pct(3.75) == "+3.75%"
    assert fmt_pct(-6.1, digits=1) == "-6.1%"
    assert fmt_pct(None) == "―"


def test_fmt_rel_time():
    now = datetime.now()
    assert fmt_rel_time(now - timedelta(seconds=40)).endswith("전")
    assert "분 전" in fmt_rel_time(now - timedelta(minutes=1, seconds=5))
    assert "시간" in fmt_rel_time(now - timedelta(hours=2, minutes=23))
    assert fmt_rel_time(None) == "―"


def test_stock_label_uses_parens_and_avoids_duplication():
    """요구 형식은 `종목이름(티커번호)`. 이름이 없거나 티커와 같으면
    `094840(094840)` 같은 자기중복 대신 `종목 094840`로 폴백 — 폴백이
    티커를 한 번만 쓴다."""
    assert stock_label("슈프리마에이치큐", "094840") == "슈프리마에이치큐(094840)"
    assert stock_label(None, "094840") == "종목 094840"
    assert stock_label("094840", "094840") == "종목 094840"
    assert stock_label("슈프리마에이치큐", None) == "슈프리마에이치큐"


def test_strip_markers_removes_unbalanced_llm_markup():
    """워치 402340 key_factors에 '차 지지선**: 1,194,000원'이 실재한다."""
    assert strip_markers("차 지지선**: 1,194,000원") == "차 지지선: 1,194,000원"
    assert strip_markers("`코드` _기울임_") == "코드 기울임"
    assert strip_markers(None) == ""


def test_display_width_counts_hangul_as_two():
    assert display_width("abc") == 3
    assert display_width("가나다") == 6
    assert display_width("🟢 보유") == 2 + 1 + 4


def test_display_width_handles_variation_selector_emoji():
    """'⚠️'는 코드포인트 2개(U+26A0 본체 + U+FE0F 변형 선택자)다. 선택자는
    폭 없는 결합 문자(category='Mn')라 폭 판정에서 걸러내지 않으면 +1이
    더 붙어 폰에서 실제로 차지하는 폭(2)보다 과다계산된다. 이 프로젝트의
    고정 이모지 어휘에 '⚠️'가 실재해(경고·엔진 불일치 라벨) 상시 영향을 준다."""
    assert display_width("⚠️") == 2
    assert display_width("⚠️ 손절") == 7
    # 변형 선택자 없는 단일 코드포인트 이모지도 계속 폭 2로 처리돼야 한다
    assert display_width("🟢 보유") == 2 + 1 + 4


def test_ko_label_maps_system_identifiers():
    """시스템 식별자는 이스케이프가 아니라 한글 매핑으로 밑줄을 없앤다."""
    assert ko_label("below_threshold") == "문턱 미달"
    assert ko_label("liquidity_low") == "유동성 부족"
    assert ko_label("llm_not_suitable") == "LLM 반려"
    assert "_" not in ko_label("insufficient_history")
    # 미등록 코드는 원문 유지 — 조용히 삼키면 새 사유가 보이지 않는다
    assert ko_label("brand_new_reason") == "brand_new_reason"


def test_effective_stop_takes_higher_and_flags_mismatch():
    """실효 손절 = max(PM, 원장). 라이브에서 13,224 vs 12,492로 5.9% 벌어져
    여유가 2.41% vs 8.42%로 갈린다 — 라벨 없는 단일 숫자는 거짓 안심이다."""
    assert effective_stop(13224.0, 12492.0) == (13224.0, True)
    assert effective_stop(12492.0, 12492.0) == (12492.0, False)
    assert effective_stop(None, 12492.0) == (12492.0, False)
    assert effective_stop(13224.0, None) == (13224.0, False)
    assert effective_stop(None, None) == (None, False)
