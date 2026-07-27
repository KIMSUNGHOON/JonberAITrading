"""리스크 에이전트 프롬프트용 유동성 한 줄 (순수 함수).

US 신호 전파(`us_market_context`, 라이브 소비 확증 402340)와 동일한 패턴이다.
이것은 하드 게이트(A1 발굴 게이트·C1 사이징 캡) **뒤의 보조 방어선**이며,
LLM 판단은 결정론적이지 않으므로 유일한 방어선으로 삼지 않는다.
"""

from __future__ import annotations

import math
from typing import Optional


def build_liquidity_note(
    adtv: Optional[float], position_notional: Optional[float]
) -> str:
    """유동성 한 줄. 값이 없으면 빈 문자열(프롬프트에서 줄 자체가 사라진다).

    never-raise — 프롬프트 조립이 이 함수 때문에 실패하면 안 된다.

    `not adtv or not position_notional`만으로는 NaN을 못 거른다 — NaN은
    파이썬에서 truthy라 `not NaN`이 False다. `participation_rate`도
    `adtv`만 비유한 가드가 있고 `position_notional`에는 없어(T2 리뷰가
    남긴 발견), 이 함수가 둘 다 명시적으로 검증해야 NaN이 프롬프트로
    새어나가지 않는다."""
    from services.discovery.liquidity import participation_rate

    if not adtv or not position_notional:
        return ""
    if not math.isfinite(adtv) or not math.isfinite(position_notional):
        return ""

    rate = participation_rate(position_notional, adtv)
    if rate is None:
        return ""

    warn = " ⚠️ 참여율 1% 초과 — 손절 시 하락일 호가가 얇아 청산 위험" if rate > 0.01 else ""
    return (
        f"\n### 유동성\n"
        f"- 일평균 거래대금(20일 중앙값): {adtv / 1e8:,.1f}억원\n"
        f"- 이 포지션의 참여율: {rate * 100:.1f}%{warn}"
    )
