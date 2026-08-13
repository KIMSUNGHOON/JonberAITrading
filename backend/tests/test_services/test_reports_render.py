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


def test_non_dict_regime_sentinel_does_not_break_render():
    """`RegimeUnavailable()`(레짐 조회 **실패** 센티널, `services.telegram.
    briefing`)은 `__bool__`을 오버라이드하지 않은 평범한 객체라 truthy지만
    dict가 아니다. `premarket.html`의 `{% if ctx.regime %}`는 그것만으로
    통과해 버려 `ctx.regime.confidence`(헤더 칩)·`ctx.regime.
    effective_target_pct`("오늘의 제약")에서 속성 접근을 시도하고, jinja2는
    dict가 아닌 객체에 없는 속성을 `Undefined`로 접었다가 산술 연산
    (`Undefined * 100`)에서 `UndefinedError`를 raise한다 — 레짐 조회가
    실패한 바로 그날, '오늘의 제약'이 가장 필요한 그날 리포트가 통째로
    죽는다(2026-08-13 리뷰 Important).
    """
    from services.telegram.briefing import RegimeUnavailable

    ctx = ReportContext(
        kind="premarket", trade_date="2026-08-13",
        generated_at="2026-08-13 08:30",
        regime=RegimeUnavailable(),
        positions=[_full_position()],
    )
    html = render(ctx)  # 예외 없이 성공해야 한다
    assert "신뢰" not in html, "헤더 칩 블록이 non-dict 레짐으로 렌더되면 안 된다"


def test_null_confidence_does_not_break_render():
    """2026-08-13 최종 브랜치 리뷰 Important 2 -- `regime_judgment.
    confidence`는 nullable이고 실제로 `None`이 된다(`regime_judge.py:118`
    LLM이 필드를 빠뜨렸을 때 / `:144` 직전 판정을 그대로 승계할 때 그
    직전 값이 다시 `None`이었을 때). `premarket.html`의 헤더 칩은
    `(ctx.regime.confidence * 100)|num(0)`인데, 곱셈이 `|num` 필터
    (`TypeError`/`ValueError`만 잡는다) **이전에** 평가되므로
    `None * 100`이 그 자리에서 `TypeError`를 던지고 jinja2가 이를 잡지
    않아 `render()` 전체가 실패한다 -- `RegimeUnavailable` 센티널과 같은
    계열의 두 번째 구멍이다. `effective_target_pct`는 판정이 성공한 행에서
    절대 `None`이 될 수 없으므로(`regime_judge.py`: `effective is None`이면
    행 자체를 안 쓴다) 여기서는 건드리지 않는다."""
    ctx = ReportContext(
        kind="premarket", trade_date="2026-08-13",
        generated_at="2026-08-13 08:30",
        regime={"regime": "bull", "confidence": None, "effective_target_pct": 0.0801},
        positions=[_full_position()],
    )
    html = render(ctx)  # 예외 없이 성공해야 한다
    assert "신뢰" not in html, "confidence가 None이면 신뢰 조각을 생략해야 한다"
    assert "bull" in html, "레짐 라벨 자체는 confidence와 무관하게 나와야 한다"
