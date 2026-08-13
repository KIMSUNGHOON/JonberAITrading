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
