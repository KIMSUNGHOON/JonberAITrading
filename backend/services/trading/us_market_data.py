"""US AI 크로스마켓 신호 — 간밤 미 반도체/AI 섹터 성과를 fetch하고 bounded 신호로
산출·캐시한다. US 매매 아님, 신호 데이터만. never-raise: 실패는 None."""
import json
from datetime import date, datetime, timezone
from typing import Optional

import httpx
import structlog

from app.config import get_settings
from services.storage_service import get_storage_service

logger = structlog.get_logger(__name__)

# v1 코어 티커 + 가중(섹터베타 SMH 우세, MU 메모리 read-through, NVDA HBM 수요)
US_AI_TICKERS: dict[str, float] = {"SMH": 0.5, "MU": 0.25, "NVDA": 0.25}
_SIGNAL_SCALE_PCT = 3.0  # 가중 %change 3% = ±1.0 포화 (v1 단순, 실측 후 조정)
US_SIGNAL_CACHE_KEY = "us_ai_signal"
_FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"


async def _finnhub_quote(client: httpx.AsyncClient, ticker: str, api_key: str) -> Optional[dict]:
    """Finnhub /quote 단일 티커. dp=%change, pc=prev close, c=current. 실패 None
    (never-raise). provider 교체 경계."""
    try:
        resp = await client.get(_FINNHUB_QUOTE_URL, params={"symbol": ticker, "token": api_key})
        resp.raise_for_status()
        d = resp.json()
        if d.get("dp") is None and d.get("pc") is None:
            return None
        return {"chg_pct": float(d.get("dp") or 0.0), "prev_close": float(d.get("pc") or 0.0)}
    except Exception as e:
        logger.warning("finnhub_quote_failed", ticker=ticker, error=str(e))
        return None


async def fetch_us_ai_overnight(tickers: Optional[list[str]] = None) -> Optional[dict]:
    """티커별 간밤 %change fetch → {ticker: {chg_pct, prev_close}}. 키 미설정/전량
    실패 시 None. never-raise."""
    settings = get_settings()
    key_obj = settings.FINNHUB_API_KEY
    api_key = key_obj.get_secret_value() if key_obj else None
    if not api_key:
        logger.info("us_ai_fetch_skipped_no_api_key")
        return None
    tickers = tickers or list(US_AI_TICKERS.keys())
    out: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for t in tickers:
                q = await _finnhub_quote(client, t, api_key)
                if q is not None:
                    out[t] = q
    except Exception as e:
        logger.warning("us_ai_fetch_failed", error=str(e))
        return None
    return out or None


def compute_us_ai_signal(snapshot: Optional[dict]) -> Optional[dict]:
    """가중 오버나이트 %change → bounded signed [-1,1]. 결측 티커는 가중 재정규화.
    전량 결측/빈 → None."""
    if not snapshot:
        return None
    num = 0.0
    wsum = 0.0
    comps: dict[str, float] = {}
    for t, w in US_AI_TICKERS.items():
        q = snapshot.get(t)
        if q is None:
            continue
        chg = float(q.get("chg_pct") or 0.0)
        comps[t] = chg
        num += w * chg
        wsum += w
    if wsum == 0.0:
        return None
    signal_pct = num / wsum
    signal = max(-1.0, min(1.0, signal_pct / _SIGNAL_SCALE_PCT))
    return {
        "signal": signal,
        "signal_pct": signal_pct,
        "components": comps,
        "as_of": date.today().isoformat(),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


async def refresh_us_ai_signal_cache() -> Optional[dict]:
    """pre-open 배치: fetch → compute → app_settings 캐시. US_SIGNAL_ENABLED off면
    no-op. never-raise."""
    if not get_settings().US_SIGNAL_ENABLED:
        return None
    try:
        snapshot = await fetch_us_ai_overnight()
        signal = compute_us_ai_signal(snapshot)
        if signal is None:
            logger.warning("us_ai_signal_refresh_empty")
            return None
        storage = await get_storage_service()
        await storage.set_app_setting(US_SIGNAL_CACHE_KEY, json.dumps(signal, ensure_ascii=False))
        logger.info("us_ai_signal_cached", signal=signal["signal"],
                    signal_pct=signal["signal_pct"], as_of=signal["as_of"])
        return signal
    except Exception as e:
        logger.warning("us_ai_signal_refresh_failed", error=str(e))
        return None


def start_us_signal_scheduler():
    """pre-open 일일 cron(08:00 KST) — US 마감 후·KR 개장(09:00) 전 신호 갱신.
    US_SIGNAL_ENABLED off면 None(스케줄러 미기동). krx_holiday.start_scheduler 패턴."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    if not get_settings().US_SIGNAL_ENABLED:
        return None
    scheduler = AsyncIOScheduler()
    scheduler.add_job(refresh_us_ai_signal_cache, trigger="cron", hour=8, minute=0,
                       id="us_ai_signal_refresh", replace_existing=True)
    scheduler.start()
    logger.info("us_ai_signal_scheduler_started")
    return scheduler


async def get_cached_us_ai_signal() -> Optional[dict]:
    """캐시된 당일 US 신호. off/미존재/stale(오늘 아님)/파싱실패 → None. never-raise.
    소비처(sentiment/discovery) 단일 소스."""
    if not get_settings().US_SIGNAL_ENABLED:
        return None
    try:
        storage = await get_storage_service()
        raw = await storage.get_app_setting(US_SIGNAL_CACHE_KEY)
        if not raw:
            return None
        d = json.loads(raw)
        if d.get("as_of") != date.today().isoformat():
            return None
        return d
    except Exception as e:
        logger.warning("us_ai_signal_get_failed", error=str(e))
        return None
