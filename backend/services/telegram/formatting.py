"""Telegram 발송부·수신부가 공유하는 포맷 순수 함수.

이 모듈에 외부 의존을 넣지 마라 — settings·storage·httpx를 import하는 순간
테스트가 무거워지고 발송 경로에 새 실패 지점이 생긴다. 값을 받아 문자열을
돌려주는 것만 한다.

금액 3분류가 핵심 계약이다:
  (a) 주문 가능한 가격 레벨(진입가·손절가·익절가·평단·현재가) → fmt_price.
      축약 절대 금지 — 13,060을 "1.3만"으로 쓰면 그 값으로 주문을 못 낸다.
  (b) 집계 금액(총평가·예수금·평가액) → fmt_money_short. 축약 허용.
  (c) 손익만 부호 표기 → fmt_pnl. 비손익 값에 부호를 붙이지 않는다
      (기존 _fmt_krw가 예수금에 '+'를 붙이는 동작을 재사용하지 말 것).
"""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Optional, Tuple

_EMPTY = "―"

# 시스템 식별자 → 한글. 이스케이프가 아니라 매핑으로 밑줄을 없앤다 —
# skip_reason 12종·전략 키·에이전트명·enum이 전부 밑줄을 갖는다.
_KO_LABELS = {
    "below_threshold": "문턱 미달",
    "market_cap_low": "시총 미달",
    "liquidity_low": "유동성 부족",
    "price_too_low": "주가 과소",
    "insufficient_history": "이력 부족",
    "zero_volume_day": "거래 없음",
    "liquidity_inconsistent": "유동성 모순",
    "llm_not_suitable": "LLM 반려",
    "daily_cap": "일일한도",
    "not_reviewed": "미검토",
    "negative_eps": "적자 배제",
}


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt_price(value) -> str:
    """주문 가능한 가격 레벨. 부호 없는 완전 천단위, 축약 금지."""
    parsed = _to_float(value)
    if parsed is None:
        return _EMPTY
    return f"{int(round(parsed)):,}"


def fmt_money_short(value) -> str:
    """집계 금액. 억/만 축약.

    99,999,999는 억 문턱(1억) 미만이라 만 분기로 가지만, `n/10_000`을
    반올림하면 10,000만이 나온다 — 이는 곧 1억이라 "10,000만"이라는
    자기모순 표기가 된다. 반올림 후 10,000에 도달하면 억 분기로 승격한다.
    """
    parsed = _to_float(value)
    if parsed is None:
        return _EMPTY
    sign = "-" if parsed < 0 else ""
    n = abs(parsed)
    if n >= 100_000_000:
        return f"{sign}{n / 100_000_000:.2f}억"
    if n >= 10_000:
        man = int(round(n / 10_000))
        if man >= 10_000:
            return f"{sign}{n / 100_000_000:.2f}억"
        return f"{sign}{man:,}만"
    return f"{sign}{int(round(n)):,}원"


def fmt_pnl(value) -> str:
    """손익. 부호를 강제한다."""
    parsed = _to_float(value)
    if parsed is None:
        return _EMPTY
    n = int(round(parsed))
    if n == 0:
        return "0"
    return f"{n:+,}"


def fmt_pct(value, digits: int = 2) -> str:
    parsed = _to_float(value)
    if parsed is None:
        return _EMPTY
    return f"{parsed:+.{digits}f}%"


def fmt_rel_time(dt: Optional[datetime]) -> str:
    """상대 시각. 마이크로초 ISO 원본을 그대로 찍지 않기 위한 것."""
    if dt is None:
        return _EMPTY
    delta = datetime.now() - dt
    secs = int(delta.total_seconds())
    future = secs < 0
    secs = abs(secs)
    suffix = "후" if future else "전"
    if secs < 60:
        return f"{secs}초 {suffix}"
    mins, s = divmod(secs, 60)
    if mins < 60:
        return f"{mins}분 {suffix}"
    hours, m = divmod(mins, 60)
    if hours < 24:
        return f"{hours}시간 {m}분 {suffix}" if m else f"{hours}시간 {suffix}"
    days = hours // 24
    return f"{days}일 {suffix}"


def stock_label(name: Optional[str], ticker: Optional[str]) -> str:
    """`종목명(티커)`.

    이름이 없거나 이름이 티커와 같으면 `종목 094840`로 폴백한다(중복 방지
    — `094840(094840)` 같은 자기중복 표기를 만들지 않기 위한 것).
    """
    t = (ticker or "").strip()
    n = (name or "").strip()
    if not n or n == t:
        return f"종목 {t}" if t else _EMPTY
    return f"{n}({t})" if t else n


def strip_markers(text: Optional[str]) -> str:
    """LLM 자유텍스트의 `*`/`_`/백틱을 제거한다.

    평문 경로라도 원문의 짝 안 맞는 `**`가 그대로 노출된다 — 워치 402340의
    key_factors에 `차 지지선**: 1,194,000원`이 실재한다.
    """
    if not text:
        return ""
    out = text
    for ch in ("*", "_", "`"):
        out = out.replace(ch, "")
    return out


def display_width(text: Optional[str]) -> int:
    """폰 표시폭. 한글·이모지 2, ASCII 1, 결합 문자(변형 선택자 등) 0.

    한 줄 44를 넘으면 폰에서 접히고 접힘에 들여쓰기가 없어 다음 항목과 섞인다.

    `⚠️`는 코드포인트 2개다: U+26A0(경고 기호 본체) + U+FE0F(이모지 변형
    선택자). 선택자는 폭이 없는 결합 문자(category="Mn")로, 폭 판정 전에
    걸러내지 않으면 else 분기로 떨어져 +1이 더 붙는다 — 이 프로젝트의
    고정 이모지 어휘에 `⚠️`가 실재해 그냥 두면 상시 과다계산된다.
    """
    if not text:
        return 0
    width = 0
    for ch in text:
        if unicodedata.combining(ch) or unicodedata.category(ch) == "Mn":
            continue  # 결합 문자(변형 선택자 등)는 폭 0
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            width += 2
        elif unicodedata.category(ch) == "So":  # 기타 기호(이모지 다수)
            width += 2
        else:
            width += 1
    return width


def ko_label(code: Optional[str]) -> str:
    """시스템 식별자를 한글로. 미등록 코드는 원문을 유지한다 —
    조용히 삼키면 새로 생긴 사유가 화면에서 사라진다."""
    if not code:
        return _EMPTY
    return _KO_LABELS.get(code, code)


def effective_stop(
    pm_stop: Optional[float], ledger_stop: Optional[float]
) -> Tuple[Optional[float], bool]:
    """실효 손절 = max(포지션매니저, 코디네이터 원장)과 불일치 여부.

    두 엔진이 각자 손절을 들고 있고 실제로 먼저 발동하는 것은 높은 쪽이다.
    라이브에서 13,224 vs 12,492로 5.9% 벌어져 여유가 2.41% vs 8.42%로 갈렸다 —
    라벨 없는 단일 숫자는 거짓 안심이다.
    """
    a = _to_float(pm_stop)
    b = _to_float(ledger_stop)
    if a is None and b is None:
        return None, False
    if a is None:
        return b, False
    if b is None:
        return a, False
    return max(a, b), a != b
