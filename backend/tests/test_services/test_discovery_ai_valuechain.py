from services.discovery.ai_valuechain import AI_VALUECHAIN_TICKERS, is_ai_valuechain


def test_core_tickers_present():
    # 큐레이션 확장 v1: 코어 2종 + STRONG 4종 + SK스퀘어 = 7종
    for ticker in (
        "005930",  # 삼성전자
        "000660",  # SK하이닉스
        "042700",  # 한미반도체
        "007660",  # 이수페타시스
        "353200",  # 대덕전자
        "009150",  # 삼성전기
        "402340",  # SK스퀘어
    ):
        assert ticker in AI_VALUECHAIN_TICKERS


def test_is_ai_valuechain():
    # 기존 코어
    assert is_ai_valuechain("005930") is True
    assert is_ai_valuechain("000660") is True
    # 확장 신규 4종 + SK스퀘어
    assert is_ai_valuechain("042700") is True  # 한미반도체
    assert is_ai_valuechain("007660") is True  # 이수페타시스
    assert is_ai_valuechain("353200") is True  # 대덕전자
    assert is_ai_valuechain("009150") is True  # 삼성전기
    assert is_ai_valuechain("402340") is True  # SK스퀘어
    # 음성 대조군 — 제외 결정된 함정 종목도 확인
    assert is_ai_valuechain("035420") is False  # NAVER (비-AI밸류체인)
    assert is_ai_valuechain("403870") is False  # HPSP (파운드리 구동, 제외)
    assert is_ai_valuechain("011070") is False  # LG이노텍 (애플 카메라, 제외)
    assert is_ai_valuechain("") is False
    assert is_ai_valuechain(None) is False
