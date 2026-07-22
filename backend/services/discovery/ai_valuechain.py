"""한국 AI 밸류체인 종목 큐레이션 — US AI 크로스마켓 신호가 적용될 대상.
코드베이스에 섹터 매핑이 없어 손 큐레이션(DEFAULT_REGIME_WEIGHTS 관행과 동일).
v1 코어는 메모리/HBM 대장(삼성전자·SK하이닉스) — 리서치상 US AI lead-lag이
가장 확실한 종목. 확장 시 신중히(리서치: 한미반도체 등은 이 채널 약함)."""

AI_VALUECHAIN_TICKERS: dict[str, str] = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
}


def is_ai_valuechain(ticker: str) -> bool:
    """ticker가 AI 밸류체인 큐레이션 목록에 있으면 True."""
    return bool(ticker) and ticker in AI_VALUECHAIN_TICKERS
