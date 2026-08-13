"""개장후 리포트 — 오늘 무슨 일이 있었나."""
import pytest

from services.reports.models import PositionResearch, ReportContext
from services.reports.render import render

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


def _ctx(**extra) -> ReportContext:
    return ReportContext(
        kind="postmarket", trade_date="2026-08-13",
        generated_at="2026-08-13 16:35",
        positions=[PositionResearch(
            ticker="028670", name="팬오션", quantity=3115, avg_price=5969.0,
            current_price=5710.0, pnl_pct=-5.13, stop_loss=5520.0,
            stop_loss_source="coordinator", discussion_count=6, action="HOLD",
            consensus=0.79)],
        extra=extra,
    )


def test_zero_fills_says_zero_not_blank():
    """빈 섹션은 '체결이 없었다'와 '수집이 실패했다'를 구별하지 못한다."""
    html = render(_ctx(fills=[]))
    assert "체결 0건" in html


def test_lists_fills():
    html = render(_ctx(fills=[
        {"time": "13:25", "ticker": "316140", "side": "SELL",
         "quantity": 549, "price": 33106, "reason": "손절"}]))
    assert "316140" in html and "손절" in html


def test_revisions_show_direction_of_change():
    """값 하나만 보면 4일 연속 축소 같은 흐름이 안 보인다."""
    html = render(_ctx(revisions=[
        {"knob": "vol_multiplier_min", "before": 0.4, "after": 0.3}]))
    assert "vol_multiplier_min" in html
    assert "0.4" in html and "0.3" in html
    assert "↓" in html


def test_renders_with_no_extra_at_all():
    assert "팬오션" in render(_ctx())


@pytest.mark.asyncio
async def test_eod_chain_survives_report_failure(monkeypatch):
    """EOD 체인이 리포트 때문에 죽으면 그날 관측이 전부 날아간다."""
    from unittest.mock import AsyncMock  # noqa: F401 -- 브리프 원본 그대로
    from services import reports

    monkeypatch.setattr("services.reports.render.render",
                        lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")))
    assert await reports.build_and_send_report("postmarket", "2026-08-13") is False
