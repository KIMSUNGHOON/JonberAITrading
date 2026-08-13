"""Telegram 시각 리포트 — 개장전·개장후·발굴."""
from __future__ import annotations

from datetime import datetime

import structlog

logger = structlog.get_logger(__name__)


async def build_and_send_report(kind: str, trade_date: str, **ctx_extra) -> bool:
    """리포트를 만들어 Telegram에 첨부 발송한다. **never-raise.**

    호출자는 이미 텍스트 알림을 보낸 뒤다 — 여기서 무엇이 실패하든
    사용자는 이미 핵심 정보를 받았다. 예외를 올리면 EOD 체인이나 발굴
    파이프라인이 리포트 때문에 죽는다.
    """
    try:
        from services.reports import collect, delivery
        from services.reports.models import ReportContext
        from services.reports.render import render
        from services.storage_service import get_storage_service
        from services.telegram import get_telegram_notifier

        positions = await collect.collect_positions()
        storage = await get_storage_service()
        await collect.attach_research(positions, trade_date, storage)
        await collect.attach_fundamentals(
            positions, fetch=collect.make_fundamentals_fetch()
        )
        await collect.attach_news(positions, fetch=collect.make_news_fetch())

        ctx = ReportContext(
            kind=kind,
            trade_date=trade_date,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            positions=positions,
            extra=ctx_extra,
            regime=ctx_extra.get("regime"),
        )
        html = render(ctx)

        delivery.prune_old_reports(delivery.REPORT_ROOT)
        delivery.save_report(delivery.REPORT_ROOT, kind, trade_date, html)

        notifier = await get_telegram_notifier()
        if not notifier.is_ready:
            logger.warning("report_notifier_not_ready", kind=kind)
            return False
        return await notifier.send_document(
            html.encode("utf-8"), f"{kind}-{trade_date}.html"
        )
    except Exception as e:  # noqa: BLE001 -- 리포트가 알림을 죽이면 안 된다
        logger.warning("report_build_failed", kind=kind, error=str(e))
        return False
