"""한국 AI 밸류체인 종목 큐레이션 — US AI 크로스마켓 신호가 적용될 대상.
코드베이스에 섹터 매핑이 없어 손 큐레이션(DEFAULT_REGIME_WEIGHTS 관행과 동일).

US 신호는 all-or-nothing으로 적용된다(종목별 가중 없음): 목록에 있으면
SK하이닉스와 동일한 풀 신호(sentiment 넛지 + 발굴 보너스), 없으면 0.
따라서 큐레이션 기준은 "STRONG 티어"만 — 미 반도체(SMH/MU/NVDA) 사이클에
실제로 구동되는 종목. 약한 링크를 넣으면 부당한 풀 신호로 희석된다.

STRONG 근거(외부 리서치 2024–2026): 한미반도체=HBM TC본더 세계1위·NVDA
동조 문서화, 이수페타시스=AI가속기 PCB·NVDA 주가 동조 문서화, 대덕전자=
FC-BGA/AI서버 PCB, 삼성전기=엔비디아 FC-BGA 1st벤더(단 기판 매출 ~20%로
희석). 402340 SK스퀘어는 지주사(하이닉스 간접노출)로 직접 co-movement
근거는 없으나 워치 활성→즉시 소비 이점으로 사용자 결정 포함.

제외(희석 방지): HPSP·리노공업·LG이노텍·DB하이텍·KINX 등은 looks-AI지만
미 메모리/반도체 사이클 미추종. MEDIUM(테크윙·심텍·유진테크 등)은 링크는
실재하나 lumpy → 종목별 가중(티어드)이 가능한 v2로 연기.
설계 기록: docs/superpowers/specs/2026-07-22-ai-valuechain-curation-expansion-design.md"""

AI_VALUECHAIN_TICKERS: dict[str, str] = {
    "005930": "삼성전자",      # 메모리/HBM (앵커, 파운드리/모바일로 희석)
    "000660": "SK하이닉스",    # HBM 대장 — 마이크론과 동조 문서화
    "042700": "한미반도체",    # HBM TC본더 세계1위 — NVDA 동조 문서화
    "007660": "이수페타시스",  # AI가속기/스위치 초다층 PCB — NVDA 주가 동조
    "353200": "대덕전자",      # FC-BGA + AI서버 PCB
    "009150": "삼성전기",      # 엔비디아 FC-BGA 1st벤더 (기판 ~20%로 희석)
    "402340": "SK스퀘어",      # 지주사 (하이닉스 간접노출) — 사용자 선택
}


def is_ai_valuechain(ticker: str) -> bool:
    """ticker가 AI 밸류체인 큐레이션 목록에 있으면 True."""
    return bool(ticker) and ticker in AI_VALUECHAIN_TICKERS
