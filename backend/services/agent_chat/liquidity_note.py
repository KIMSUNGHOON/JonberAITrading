"""리스크 에이전트 프롬프트용 유동성 한 줄 (순수 함수).

US 신호 전파(`us_market_context`, 라이브 소비 확증 402340)와 동일한 패턴이다.
이것은 하드 게이트(A1 발굴 게이트·C1 사이징 캡) **뒤의 보조 방어선**이며,
LLM 판단은 결정론적이지 않으므로 유일한 방어선으로 삼지 않는다.
"""

from __future__ import annotations

import math
from typing import Optional


def build_liquidity_note(
    adtv: Optional[float],
    position_notional: Optional[float],
    is_new_entry: bool = False,
) -> str:
    """유동성 한 줄. 값이 없으면 빈 문자열(프롬프트에서 줄 자체가 사라진다).

    `is_new_entry`: True면 `position_notional`이 실제 보유가 아니라
    신규 진입 예상 규모(호출부 가정)라는 뜻 — 문구를 "이 포지션의 참여율"
    (이미 들고 있다는 오해를 부를 수 있음)이 아니라 "예상 진입 규모 기준
    참여율"로 바꾼다. 숫자 계산에는 영향 없음 — 순수 표시 문구 분기.

    never-raise — 프롬프트 조립이 이 함수 때문에 실패하면 안 된다.

    `not adtv or not position_notional`만으로는 NaN을 못 거른다 — NaN은
    파이썬에서 truthy라 `not NaN`이 False다. `participation_rate`도
    `adtv`만 비유한 가드가 있고 `position_notional`에는 없어(T2 리뷰가
    남긴 발견), 이 함수가 둘 다 명시적으로 검증해야 NaN이 프롬프트로
    새어나가지 않는다."""
    from services.discovery.liquidity import (
        GATE_PARTICIPATION_PCT,
        participation_rate,
    )

    if not adtv or not position_notional:
        return ""
    if not math.isfinite(adtv) or not math.isfinite(position_notional):
        return ""

    rate = participation_rate(position_notional, adtv)
    if rate is None:
        return ""

    # 발굴 게이트와 같은 상수를 재사용 — 게이트 문턱이 재조정되면 이 경고도
    # 자동으로 따라간다(하드코딩 0.01 금지, Global Constraint).
    warn = (
        f" ⚠️ 참여율 {GATE_PARTICIPATION_PCT * 100:.0f}% 초과 — 손절 시 "
        f"하락일 호가가 얇아 청산 위험"
        if rate > GATE_PARTICIPATION_PCT
        else ""
    )
    label = "예상 진입 규모 기준 참여율" if is_new_entry else "이 포지션의 참여율"
    return (
        f"\n### 유동성\n"
        f"- 일평균 거래대금(20일 중앙값): {adtv / 1e8:,.1f}억원\n"
        f"- {label}: {rate * 100:.1f}%{warn}"
    )
