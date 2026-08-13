"""HTML 렌더 — 값이 실제로 문서에 들어가는지, 결측이 죽이지 않는지."""
import pytest

from services.reports.models import AgentVote, NewsItem, PositionResearch, ReportContext
from services.reports.render import render

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


def _full_position() -> PositionResearch:
    return PositionResearch(
        ticker="028670", name="팬오션", quantity=3115, avg_price=5969.0,
        current_price=5710.0, pnl_pct=-5.13, stop_loss=5520.0,
        stop_loss_source="coordinator", discussion_count=6, action="HOLD",
        consensus=0.7425,
        votes=[
            AgentVote("technical", "hold", 0.58, "정배열·MACD +47", False),
            AgentVote("fundamental", "buy", 0.62, "PER 10.11배 저평가", True),
        ],
        signals={"rsi": 57.19, "volume_ratio": 0.6, "trend": "bullish"},
        per=10.11, pbr=0.53, eps=564.0,
        news=[NewsItem("운임 지수 3주째 상승", "한국경제", "2시간 전", "positive",
                       "http://x/1")],
    )


def _ctx(positions) -> ReportContext:
    return ReportContext(
        kind="premarket", trade_date="2026-08-13",
        generated_at="2026-08-13 08:30",
        regime={"regime": "bull", "confidence": 0.78, "effective_target_pct": 0.0801},
        positions=positions,
    )


def test_renders_position_research_into_html():
    html = render(_ctx([_full_position()]))
    for needle in ("팬오션", "028670", "HOLD", "PER", "10.11",
                   "정배열·MACD +47", "운임 지수 3주째 상승", "한국경제"):
        assert needle in html, needle


def test_dissent_is_marked():
    html = render(_ctx([_full_position()]))
    assert "반대표" in html


def test_unanimous_position_has_no_dissent_badge():
    p = _full_position()
    p.votes = [AgentVote("technical", "hold", 0.58, "정배열", False)]
    assert "반대표" not in render(_ctx([p]))


def test_missing_everything_still_renders():
    """신규 편입 직후 — 토론도 뉴스도 PER도 없다."""
    p = PositionResearch(
        ticker="005930", name="삼성전자", quantity=10, avg_price=70000.0,
        current_price=71000.0, pnl_pct=1.43, stop_loss=None, stop_loss_source=None,
    )
    html = render(_ctx([p]))
    assert "삼성전자" in html
    assert "토론 없음" in html


def test_news_error_is_shown_not_hidden():
    p = _full_position()
    p.news, p.news_error = [], "quota exceeded"
    assert "조회 실패" in render(_ctx([p]))


def test_output_is_a_self_contained_document():
    """외부 CSS·폰트·이미지를 부르면 폰에서 깨진다."""
    html = render(_ctx([_full_position()]))
    assert html.lstrip().startswith("<!doctype html>")
    assert "<style>" in html
    for bad in ("<link", "<script", "https://fonts", "cdn."):
        assert bad not in html, bad


def test_stop_loss_source_is_shown():
    """두 엔진이 다른 손절가를 든다 — 출처 없는 숫자는 오독을 만든다."""
    assert "coordinator" in render(_ctx([_full_position()]))


def test_breached_stop_loss_bar_is_danger_not_leaked_negative_width():
    """손절가 아래로 내려간 포지션 — 막대에 음수 width가 새면 브라우저가
    이를 버리고 트랙 기본값(가득 참)으로 폴백해 '가장 안전'으로 보인다(teal 배경 그대로).
    2026-08-12 손절 주문 3분할 미체결로 실제 발생한 상태.
    올바른 표현은 막대를 가득(100%) 채우되 빨강(danger)으로 읽히게 하는 것이다."""
    p = _full_position()
    p.stop_loss = 5520.0
    p.current_price = 5200.0  # 손절가 아래 — stop_margin_pct == -6.153...%
    html = render(_ctx([p]))
    assert "width:-" not in html
    assert "이탈" in html
    assert 'class="fill breached"' in html
    assert "width:100%" in html


def test_missing_stop_loss_source_omits_none_parens():
    p = _full_position()
    p.stop_loss_source = None
    assert "(None)" not in render(_ctx([p]))
