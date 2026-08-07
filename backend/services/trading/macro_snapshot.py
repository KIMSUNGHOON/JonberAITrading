"""매크로 스냅샷 — 레짐 판정의 입력. 미국 실물 시세를 쓴다.

국내 지수·시세는 실제 시장 데이터다(`KIWOOM_IS_MOCK=true`는 **주문 실행만**
모의투자 서버로 보낸다 — 시세·지수·재무는 실물이고, Yahoo `^KS11`과 행 단위로
대조해 반증했다). 변동성 계산은 `index_series.py`의 `index_daily`(KOSPI)를
쓴다 — 여기서는 그 값을 다루지 않는다.

여기서 미국 시세를 받는 이유는 레짐 판정의 LLM 입력으로 간밤 미국장 흐름이
유용해서다 — EWY(iShares MSCI South Korea, 미국 상장)는 외국인이 실제로
값을 매기는 한국 시장 대리 가격이고, SPY·VIXY 등은 간밤 리스크 심리를
보여준다.

설계: docs/superpowers/specs/2026-08-07-regime-aware-exposure-design.md ·
정정: docs/superpowers/specs/2026-08-07-volatility-correction-design.md
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import structlog

from services.storage_service import get_storage_service
from services.trading.us_market_data import fetch_us_ai_overnight

logger = structlog.get_logger(__name__)

# 순서에 의미가 있다 — EWY가 먼저다(한국 시장의 대리, 판정의 1순위 근거).
MACRO_TICKERS: list[str] = ["EWY", "SPY", "QQQ", "VIXY", "TLT", "UUP", "USO", "GLD"]


async def refresh_macro_snapshot() -> Optional[dict]:
    """8종을 받아 오늘 행으로 적는다. never-raise.

    부분 실패는 허용한다 — 받은 것만 저장하고 못 받은 티커를 남긴다.
    전량 실패면 행을 만들지 않고 None을 돌려준다(빈 행은 진짜 데이터와
    구별되지 않는다).
    """
    try:
        quotes = await fetch_us_ai_overnight(MACRO_TICKERS)
    except Exception as e:
        logger.warning("macro_snapshot_fetch_failed", error=str(e))
        return None

    if not quotes:
        logger.warning("macro_snapshot_empty", tickers=len(MACRO_TICKERS))
        return None

    missing = [t for t in MACRO_TICKERS if t not in quotes]
    trade_date = date.today().isoformat()

    try:
        storage = await get_storage_service()
        ok = await storage.insert_macro_snapshot(
            trade_date=trade_date, quotes=quotes, missing=missing
        )
    except Exception as e:
        logger.warning("macro_snapshot_persist_failed", error=str(e))
        return None

    if not ok:
        # insert_macro_snapshot는 실패-무해(자체 예외를 삼키고 False만 반환)라
        # 위 try/except로는 이 실패를 절대 못 잡는다 — 반환값을 직접 확인해야
        # "기록됨" 로그가 거짓 성공을 보고하지 않는다.
        logger.warning("macro_snapshot_persist_failed", trade_date=trade_date)
        return None

    logger.info(
        "macro_snapshot_recorded",
        trade_date=trade_date,
        received=len(quotes),
        missing=missing,
    )
    return {"quotes": quotes, "missing": missing}
