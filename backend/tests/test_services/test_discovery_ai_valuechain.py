from services.discovery.ai_valuechain import AI_VALUECHAIN_TICKERS, is_ai_valuechain


def test_core_tickers_present():
    assert "005930" in AI_VALUECHAIN_TICKERS  # 삼성전자
    assert "000660" in AI_VALUECHAIN_TICKERS  # SK하이닉스


def test_is_ai_valuechain():
    assert is_ai_valuechain("005930") is True
    assert is_ai_valuechain("000660") is True
    assert is_ai_valuechain("035420") is False  # NAVER (비-AI밸류체인)
    assert is_ai_valuechain("") is False
    assert is_ai_valuechain(None) is False
