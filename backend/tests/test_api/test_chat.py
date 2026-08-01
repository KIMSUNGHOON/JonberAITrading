"""app/api/routes/chat.py의 `_format_trading_context` 회귀 테스트.

Task 7 스윕(2026-08-01 Upbit 제거)에서 저가 KR 종목을 "$"로 오분류할 수 있던
가격-크기 기반 통화 추정 휴리스틱(`currency = "₩" if price > 1000 else "$"`)을
찾아 단일 시장(₩) 고정으로 고쳤다. 이 파일이 생기기 전엔 `_format_trading_context`
에 테스트가 하나도 없어, 향후 편집이 그 휴리스틱을 되살려도 잡아낼 게 없었다
(코드 리뷰가 지적). ₩1000 미만 한국 종목은 반드시 "₩"로 렌더돼야 한다 — 그게
이번에 찾은 버그이고, 지금은 이 테스트만이 재도입을 막는다.
"""

from app.api.routes.chat import (
    ActiveAnalysis,
    TradeDecision,
    TradingContext,
    _format_trading_context,
)


def test_active_analysis_sub_1000_price_renders_won_not_dollar():
    """₩1000 미만인 저가 KR 종목도 "₩"로 렌더돼야 한다 — 가격 크기로 통화를
    추정하던 옛 휴리스틱은 이 케이스를 "$"로 오분류했다."""
    ctx = TradingContext(
        activeAnalysis=ActiveAnalysis(
            ticker="005930",
            displayName="삼성전자",
            marketType="kiwoom",
            status="completed",
            currentPrice=500,
        )
    )
    formatted = _format_trading_context(ctx)
    assert "₩500" in formatted
    assert "$500" not in formatted
    assert "$" not in formatted


def test_recent_decision_sub_1000_price_renders_won_not_dollar():
    """recentDecisions 쪽도 동일한 가격-크기 휴리스틱 버그가 있었다
    (`currency = "₩" if d.price > 1000 else "$"`) — 같은 클래스의 회귀."""
    ctx = TradingContext(
        recentDecisions=[
            TradeDecision(
                ticker="005930",
                displayName="삼성전자",
                action="approved",
                tradeAction="BUY",
                timestamp="2026-08-01T09:00:00Z",
                quantity=10,
                price=500,
            )
        ]
    )
    formatted = _format_trading_context(ctx)
    assert "₩500" in formatted
    assert "$500" not in formatted
    assert "$" not in formatted
