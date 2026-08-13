"""리포트 파일 저장·보존·발송.

⚠️ 저장 경로는 `.gitignore`에 있다(`backend/data/reports/`). 이 리포는
공개이고 리포트에는 보유 종목·수량·평단·계좌 손익이 들어간다.
"""
from __future__ import annotations

import time
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

REPORT_ROOT = Path(__file__).resolve().parents[2] / "data" / "reports"


def save_report(root: Path, kind: str, trade_date: str, html: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{kind}-{trade_date}.html"
    path.write_text(html, encoding="utf-8")
    return path


def prune_old_reports(root: Path, keep_days: int = 14) -> int:
    """오래된 리포트를 지운다. 실패는 0으로 — 보존이 발송을 막으면 안 된다."""
    try:
        if not root.is_dir():
            return 0
        cutoff = time.time() - keep_days * 86400
        removed = 0
        for f in root.glob("*.html"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except Exception:  # noqa: BLE001
                continue
        return removed
    except Exception as e:  # noqa: BLE001
        logger.warning("report_prune_failed", error=str(e))
        return 0
