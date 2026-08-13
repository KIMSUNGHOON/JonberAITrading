"""리포트 파일 저장·보존, 그리고 '리포트가 알림을 죽이지 않는다'."""
import time
from pathlib import Path

import pytest

from services.reports.delivery import prune_old_reports, save_report

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


def test_saves_with_kind_and_date_filename(tmp_path):
    p = save_report(tmp_path, "premarket", "2026-08-13", "<html>x</html>")
    assert p.name == "premarket-2026-08-13.html"
    assert p.read_text(encoding="utf-8") == "<html>x</html>"


def test_prunes_files_older_than_keep_days(tmp_path):
    old = tmp_path / "premarket-2026-07-01.html"
    new = tmp_path / "premarket-2026-08-13.html"
    old.write_text("o"); new.write_text("n")
    fifteen_days_ago = time.time() - 15 * 86400
    import os
    os.utime(old, (fifteen_days_ago, fifteen_days_ago))

    removed = prune_old_reports(tmp_path, keep_days=14)
    assert removed == 1
    assert not old.exists() and new.exists()


def test_prune_on_unwritable_dir_does_not_raise(tmp_path):
    missing = tmp_path / "nope"
    assert prune_old_reports(missing, keep_days=14) == 0


@pytest.mark.asyncio
async def test_build_and_send_never_raises(monkeypatch):
    """리포트 예외가 EOD 체인이나 브리핑을 죽이면 안 된다."""
    from services import reports

    def _boom(*a, **k):
        raise RuntimeError("render exploded")

    monkeypatch.setattr("services.reports.render.render", _boom)
    assert await reports.build_and_send_report("premarket", "2026-08-13") is False


@pytest.mark.asyncio
async def test_build_and_send_calls_send_document(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock
    from services import reports

    monkeypatch.setattr("services.reports.delivery.REPORT_ROOT", tmp_path)
    monkeypatch.setattr("services.reports.collect.collect_positions",
                        AsyncMock(return_value=[]))
    notifier = AsyncMock()
    notifier.is_ready = True
    notifier.send_document = AsyncMock(return_value=True)
    monkeypatch.setattr("services.telegram.get_telegram_notifier",
                        AsyncMock(return_value=notifier))

    assert await reports.build_and_send_report("premarket", "2026-08-13") is True
    notifier.send_document.assert_awaited_once()
    assert notifier.send_document.await_args.args[1] == "premarket-2026-08-13.html"


# ---------------------------------------------------------------------------
# 2026-08-13 최종 브랜치 리뷰 Critical 2: 개장전 리포트는 `attach_research`에
# `trade_date`(오늘)를 그대로 넘겼다. 08:30엔 agent-chat 코디네이터가 장외
# idle이라(services/agent_chat/coordinator.py:790-793) 오늘자
# agent_chat_decisions는 항상 0행이고, 모든 카드가 discussion_count=0 ->
# "토론 없음" + 투표 0으로 나간다. 스펙 §5-1은 "어제 토론 기준"을 명시한다.
# 표지 날짜(trade_date)는 오늘로 남아야 하고, 토론 조회 날짜만
# `research_date`로 분리한다(기본값은 trade_date -- postmarket/discovery
# 호출부는 이 인자를 안 쓰므로 기존 동작이 그대로 보존된다).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_research_date_defaults_to_trade_date(monkeypatch, tmp_path):
    """research_date를 안 주면(postmarket/discovery 호출부처럼) 기존 동작
    그대로 trade_date로 토론을 조회해야 한다."""
    from unittest.mock import AsyncMock
    from services import reports
    from services.reports.models import PositionResearch

    monkeypatch.setattr("services.reports.delivery.REPORT_ROOT", tmp_path)
    pos = PositionResearch(
        ticker="028670", name="팬오션", quantity=1, avg_price=1.0,
        current_price=1.0, pnl_pct=0.0, stop_loss=None, stop_loss_source=None,
    )
    monkeypatch.setattr("services.reports.collect.collect_positions",
                        AsyncMock(return_value=[pos]))
    monkeypatch.setattr("services.reports.collect.make_fundamentals_fetch",
                        lambda: None)
    monkeypatch.setattr("services.reports.collect.make_news_fetch", lambda: None)

    captured: dict = {}

    async def _spy_attach_research(positions, date_arg, storage):
        captured["date"] = date_arg

    monkeypatch.setattr("services.reports.collect.attach_research",
                        _spy_attach_research)

    notifier = AsyncMock(); notifier.is_ready = False
    monkeypatch.setattr("services.telegram.get_telegram_notifier",
                        AsyncMock(return_value=notifier))

    await reports.build_and_send_report("premarket", "2026-08-13")
    assert captured["date"] == "2026-08-13"


@pytest.mark.asyncio
async def test_research_date_overrides_trade_date_for_attach_research(
    monkeypatch, tmp_path
):
    """research_date가 오면 표지(trade_date)는 그대로 두고 토론 조회만
    그 날짜로 간다."""
    from unittest.mock import AsyncMock
    from services import reports
    from services.reports.models import PositionResearch

    monkeypatch.setattr("services.reports.delivery.REPORT_ROOT", tmp_path)
    pos = PositionResearch(
        ticker="028670", name="팬오션", quantity=1, avg_price=1.0,
        current_price=1.0, pnl_pct=0.0, stop_loss=None, stop_loss_source=None,
    )
    monkeypatch.setattr("services.reports.collect.collect_positions",
                        AsyncMock(return_value=[pos]))
    monkeypatch.setattr("services.reports.collect.make_fundamentals_fetch",
                        lambda: None)
    monkeypatch.setattr("services.reports.collect.make_news_fetch", lambda: None)

    captured: dict = {}

    async def _spy_attach_research(positions, date_arg, storage):
        captured["date"] = date_arg

    monkeypatch.setattr("services.reports.collect.attach_research",
                        _spy_attach_research)

    saved: dict = {}

    def _spy_save(root, kind, trade_date, html):
        saved["trade_date"] = trade_date
        return tmp_path / f"{kind}-{trade_date}.html"

    monkeypatch.setattr("services.reports.delivery.save_report", _spy_save)

    notifier = AsyncMock(); notifier.is_ready = False
    monkeypatch.setattr("services.telegram.get_telegram_notifier",
                        AsyncMock(return_value=notifier))

    await reports.build_and_send_report(
        "premarket", "2026-08-13", research_date="2026-08-12"
    )
    assert captured["date"] == "2026-08-12"      # 토론 조회는 어제
    assert saved["trade_date"] == "2026-08-13"   # 표지는 오늘
