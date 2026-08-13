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
    """유동성 한 줄 + 그 줄에 대한 판정 지시문. 값이 없으면 빈 문자열
    (프롬프트에서 줄과 지시문이 **함께** 사라진다).

    ⚠️ 판정 지시문이 이 함수 안에 있는 이유(최종 리뷰 Blocking1):
    지시문("위 참여율이 N%를 초과하면 ...")을 프롬프트 템플릿 본문에 두면
    수치 줄이 사라져도 지시문만 남아, LLM이 존재하지 않는 "위 참여율"을
    판정하게 된다(수치 날조 또는 근거 없는 반대표). 빈 문자열이 되는 경로는
    드물지 않다 — chart_df 빈 DF, total_portfolio 결측, ADTV 표본 10일 미만.
    하필 그 경로들은 C1 사이징 캡도 `adtv_unknown`으로 fail-open되는 상황이라
    하드 게이트와 보조 방어선이 동시에 무너진 채 프롬프트만 유동성을 판정한
    척하게 된다. 따라서 **수치와 지시문은 하나의 소스에서 함께 나온다.**

    `is_new_entry`: True면 `position_notional`이 실제 보유가 아니라
    신규 진입 예상 규모(호출부 가정)라는 뜻 — 문구를 "이 포지션의 참여율"
    (이미 들고 있다는 오해를 부를 수 있음)이 아니라 "예상 진입 규모 기준
    참여율"로 바꾼다. 숫자 계산에는 영향 없음 — 순수 표시 문구 분기.

    ⚠️ 판정 지시문도 `is_new_entry`로 갈라진다(최종 리뷰 Blocking1):
    신규 진입에서 "반대표"는 "들어가지 마라"지만, **보유 포지션 토론에서
    같은 문장은 SELL(전량 청산) 지시로 읽힌다.** 저유동성은 "지금 팔아라"의
    근거가 아니라 "더 사지 마라"의 근거이며, 저유동성 종목의 강제 청산은
    정확히 이 아크가 막으려는 슬리피지를 유발한다.

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
    # 판정 지시문의 문턱도 자동으로 따라간다(하드코딩 0.01/"1%" 금지,
    # Global Constraint. 최종 리뷰: 지시문의 "1%"가 하드코딩이라 상수 조정
    # 시 note 경고 문턱과 프롬프트 판정 기준이 어긋났다).
    gate_pct_text = f"{GATE_PARTICIPATION_PCT * 100:.0f}%"
    warn = (
        f" ⚠️ 참여율 {gate_pct_text} 초과 — 손절 시 "
        f"하락일 호가가 얇아 청산 위험"
        if rate > GATE_PARTICIPATION_PCT
        else ""
    )
    label = "예상 진입 규모 기준 참여율" if is_new_entry else "이 포지션의 참여율"

    if is_new_entry:
        verdict = (
            f"- **유동성 판정 기준: 위 참여율이 {gate_pct_text}를 초과하면 "
            f"반대표(SELL 또는 HOLD)를 던지십시오.** 저유동성 종목은 손절이 "
            f"발동하는 하락일에 매수호가가 증발해 설계된 손절가에 체결되지 "
            f"않습니다."
        )
    else:
        verdict = (
            f"- **유동성 판정 기준: 위 참여율이 {gate_pct_text}를 초과하면 "
            f"이 사실은 신규 진입·추가매수(ADD)에 반대할 근거이며, 즉시 "
            f"청산의 근거가 아닙니다.** 저유동성 종목의 강제 청산은 "
            f"슬리피지를 키웁니다 — 청산 판단은 손절·익절 규율과 종목 자체의 "
            f"악재에 근거해야 하고, 유동성은 포지션을 늘리지 않을 근거로만 "
            f"쓰십시오."
        )

    return (
        f"\n### 유동성\n"
        f"- 일평균 거래대금(20일 중앙값): {adtv / 1e8:,.1f}억원\n"
        f"- {label}: {rate * 100:.1f}%{warn}\n"
        f"{verdict}"
    )
