"""Telegram 시각 리포트 — 개장전·개장후·발굴."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


async def build_and_send_report(
    kind: str, trade_date: str, *, research_date: Optional[str] = None, **ctx_extra
) -> bool:
    """리포트를 만들어 Telegram에 첨부 발송한다. **never-raise.**

    호출자는 이미 텍스트 알림을 보낸 뒤다 — 여기서 무엇이 실패하든
    사용자는 이미 핵심 정보를 받았다. 예외를 올리면 EOD 체인이나 발굴
    파이프라인이 리포트 때문에 죽는다.

    `research_date`: 보유 종목 카드에 그날의 4에이전트 토론을 붙일 때
    조회할 날짜. 표지에 찍히는 `trade_date`와 분리한다 — 개장전 리포트가
    대표 사례다(2026-08-13 최종 리뷰 Critical 2): 08:30엔 agent-chat
    코디네이터가 장외 idle이라 **오늘자** `agent_chat_decisions`는 항상
    0행이고, `trade_date`로 토론을 조회하면 표지는 오늘인데 모든 카드가
    매일 "토론 없음"으로 나간다(스펙 §5-1은 "어제 토론 기준"을 명시).
    생략하면 `trade_date`로 폴백한다 — postmarket/discovery 호출부는
    당일 토론을 그대로 보는 게 맞으므로 이 인자를 넘기지 않는다.
    """
    research_date = research_date or trade_date
    # ⚠️ 킬스위치를 여기 첫 줄에서 검사한다 -- 예전엔 `TelegramNotifier.
    # send_document` 안에서만 봐서, 게이트가 꺼져 있어도 Kiwoom 5회·뉴스
    # 5회·파일 쓰기·prune을 전부 치른 뒤에야 발송 단계에서 False를 받았다
    # (2026-08-13 최종 리뷰 Important 4). 이 레포의 다른 킬스위치
    # (REGIME_EXPOSURE_ENABLED·DISCOVERY_ENABLED·US_SIGNAL_ENABLED)는 전부
    # 진입 자체를 막으므로 여기도 맞춘다.
    try:
        from services.telegram.config import get_telegram_config

        if not get_telegram_config().TELEGRAM_REPORT_HTML_ENABLED:
            logger.info("report_html_disabled", kind=kind)
            return False
    except Exception as e:  # noqa: BLE001 -- 설정 조회 실패로 리포트를 죽이지 않는다
        logger.warning("report_html_gate_check_failed", kind=kind, error=str(e))

    try:
        from services.reports import collect, delivery
        from services.reports.models import ReportContext
        from services.reports.render import render
        from services.telegram import get_telegram_notifier

        positions: list = []
        if kind == "discovery":
            # ⚠️ 발굴 리포트는 보유 종목을 렌더하지 않는다(discovery.html은
            # ctx.extra["candidates"]만 쓴다) -- 그런데도 여기서 수집을
            # 돌리면 레이트리밋 사고다. 발굴 파이프라인은 이 리포트를
            # 만드는 바로 그 시각에 승격 심사로 Kiwoom ka10001을 top-25에
            # 25회 이미 걸어 둔다. 같은 틱에 보유 종목 펀더멘탈로 5회를
            # 더 걸면 Kiwoom 유량(~1.4 req/s)을 넘긴다 -- 2026-08-12에
            # 바로 이 유형(ka10001 연속 호출)으로 유량 초과가 실제로
            # 났다. "경로 하나 유지"보다 사고 재현 방지가 우선이다.
            logger.info("report_discovery_skips_position_collection", kind=kind)
        else:
            from services.storage_service import get_storage_service

            positions = await collect.collect_positions()
            storage = await get_storage_service()
            await collect.attach_research(positions, research_date, storage)
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
