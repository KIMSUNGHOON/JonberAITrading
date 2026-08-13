"""한국 AI 밸류체인 종목 큐레이션 — US AI 크로스마켓 신호가 적용될 대상.
코드베이스에 섹터 매핑이 없어 손 큐레이션(DEFAULT_REGIME_WEIGHTS 관행과 동일).

v2부터 종목별로 US 신호의 3개 서브신호(memory/accel/demand, 산출은
services.trading.us_market_data.compute_us_ai_signal) 중 하나를 태깅해
매칭 서브신호만 적용한다(all-or-nothing 폐지) — 메모리/HBM 체인 종목에
가속기(NVDA/AVGO) 서프라이즈가, 반대로 가속기 PCB 종목에 메모리(MU) 단독
서프라이즈가 새는 것을 막는다. demand(하이퍼스케일러 capex)는 아직 태깅
대상 종목이 없어 v2에서는 미사용(향후 세트 확장 시 배정).

STRONG 근거(외부 리서치 2024–2026): 한미반도체=HBM TC본더 세계1위·NVDA
동조 문서화, 이수페타시스=AI가속기 PCB·NVDA 주가 동조 문서화, 대덕전자=
FC-BGA/AI서버 PCB, 삼성전기=엔비디아 FC-BGA 1st벤더(단 기판 매출 ~20%로
희석). 402340 SK스퀘어는 지주사(하이닉스 간접노출)로 직접 co-movement
근거는 없으나 워치 활성→즉시 소비 이점으로 사용자 결정 포함 — 하이닉스와
동일한 memory 태그(지주 프록시).

signal_type 배정: memory(메모리/HBM 체인)=005930·000660·042700·402340,
accel(AI가속기/커스텀ASIC PCB 체인)=007660·353200·009150.

제외(희석 방지): HPSP·리노공업·LG이노텍·DB하이텍·KINX 등은 looks-AI지만
미 메모리/반도체 사이클 미추종. MEDIUM(테크윙·심텍·유진테크 등)은 링크는
실재하나 lumpy → 종목별 가중(티어드)이 가능한 v2로 연기.
설계 기록: docs/superpowers/specs/2026-07-22-ai-valuechain-curation-expansion-design.md"""

from typing import Optional

# 값 shape: {code: {"name": str, "signal_type": "memory"|"accel"}}
AI_VALUECHAIN_TICKERS: dict[str, dict[str, str]] = {
    "005930": {"name": "삼성전자", "signal_type": "memory"},      # 메모리/HBM (앵커, 파운드리/모바일로 희석)
    "000660": {"name": "SK하이닉스", "signal_type": "memory"},    # HBM 대장 — 마이크론과 동조 문서화
    "042700": {"name": "한미반도체", "signal_type": "memory"},    # HBM TC본더 세계1위 — NVDA 동조 문서화
    "007660": {"name": "이수페타시스", "signal_type": "accel"},   # AI가속기/스위치 초다층 PCB — NVDA 주가 동조
    "353200": {"name": "대덕전자", "signal_type": "accel"},       # FC-BGA + AI서버 PCB
    "009150": {"name": "삼성전기", "signal_type": "accel"},       # 엔비디아 FC-BGA 1st벤더 (기판 ~20%로 희석)
    "402340": {"name": "SK스퀘어", "signal_type": "memory"},      # 지주사 (하이닉스 간접노출) — 사용자 선택
}


def is_ai_valuechain(ticker: str) -> bool:
    """ticker가 AI 밸류체인 큐레이션 목록에 있으면 True."""
    return bool(ticker) and ticker in AI_VALUECHAIN_TICKERS


def valuechain_signal_type(ticker: Optional[str]) -> Optional[str]:
    """ticker의 매칭 US 서브신호 타입("memory"|"accel") 반환. 비-밸류체인/빈
    값이면 None."""
    v = AI_VALUECHAIN_TICKERS.get(ticker) if ticker else None
    return v.get("signal_type") if v else None
