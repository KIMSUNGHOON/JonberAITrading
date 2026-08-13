import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.trading.us_market_data as um


def test_compute_signal_weighted_clamped():
    snap = {"SMH": {"chg_pct": 4.52, "prev_close": 558.83},
            "MU": {"chg_pct": 12.17, "prev_close": 865.46},
            "NVDA": {"chg_pct": 1.97, "prev_close": 203.28}}
    sig = um.compute_us_ai_signal(snap)
    # weighted %: 0.5*4.52 + 0.25*12.17 + 0.25*1.97 = 5.795
    assert round(sig["signal_pct"], 2) == 5.79 or round(sig["signal_pct"], 2) == 5.80
    assert sig["signal"] == 1.0  # 5.79/3.0 클램프 → +1.0
    assert sig["as_of"] == date.today().isoformat()


def test_compute_signal_missing_ticker_renormalizes():
    snap = {"SMH": {"chg_pct": 2.0, "prev_close": 1.0}}  # MU/NVDA 결측
    sig = um.compute_us_ai_signal(snap)
    assert round(sig["signal_pct"], 4) == 2.0  # 가중 재정규화(SMH만)
    assert round(sig["signal"], 4) == round(2.0/3.0, 4)


def test_compute_signal_empty_none():
    assert um.compute_us_ai_signal(None) is None
    assert um.compute_us_ai_signal({}) is None


async def test_fetch_no_api_key_returns_none(monkeypatch):
    fake = MagicMock(); fake.FINNHUB_API_KEY = None; fake.US_SIGNAL_ENABLED = True
    monkeypatch.setattr(um, "get_settings", lambda: fake)
    assert await um.fetch_us_ai_overnight() is None


async def test_fetch_parses_and_skips_failed(monkeypatch):
    fake = MagicMock()
    fake.FINNHUB_API_KEY = MagicMock(); fake.FINNHUB_API_KEY.get_secret_value.return_value = "k"
    monkeypatch.setattr(um, "get_settings", lambda: fake)
    async def fake_quote(client, ticker, api_key):
        return {"chg_pct": 2.0, "prev_close": 1.0} if ticker == "SMH" else None
    monkeypatch.setattr(um, "_finnhub_quote", fake_quote)
    out = await um.fetch_us_ai_overnight(["SMH", "MU"])
    assert out == {"SMH": {"chg_pct": 2.0, "prev_close": 1.0}}


async def test_fetch_all_failed_returns_none(monkeypatch):
    fake = MagicMock()
    fake.FINNHUB_API_KEY = MagicMock(); fake.FINNHUB_API_KEY.get_secret_value.return_value = "k"
    monkeypatch.setattr(um, "get_settings", lambda: fake)
    async def fake_quote(client, ticker, api_key):
        return None
    monkeypatch.setattr(um, "_finnhub_quote", fake_quote)
    out = await um.fetch_us_ai_overnight(["SMH", "MU", "NVDA"])
    assert out is None  # {} → None (`out or None`), not an empty dict


async def test_refresh_disabled_is_noop(monkeypatch):
    fake = MagicMock(); fake.US_SIGNAL_ENABLED = False
    monkeypatch.setattr(um, "get_settings", lambda: fake)
    assert await um.refresh_us_ai_signal_cache() is None


async def test_refresh_success_writes_cache_once(monkeypatch):
    fake = MagicMock(); fake.US_SIGNAL_ENABLED = True
    monkeypatch.setattr(um, "get_settings", lambda: fake)
    snapshot = {"SMH": {"chg_pct": 2.0, "prev_close": 1.0}}
    monkeypatch.setattr(um, "fetch_us_ai_overnight", AsyncMock(return_value=snapshot))
    storage = MagicMock(); storage.set_app_setting = AsyncMock()
    monkeypatch.setattr(um, "get_storage_service", AsyncMock(return_value=storage))

    result = await um.refresh_us_ai_signal_cache()

    storage.set_app_setting.assert_awaited_once()
    key, raw = storage.set_app_setting.await_args.args
    assert key == um.US_SIGNAL_CACHE_KEY
    written = json.loads(raw)
    assert written["signal"] == result["signal"]
    assert round(written["signal_pct"], 4) == 2.0  # SMH만 → 재정규화 없이 그대로
    assert written["as_of"] == date.today().isoformat()


async def test_get_cached_returns_today_signal(monkeypatch):
    fake = MagicMock(); fake.US_SIGNAL_ENABLED = True
    monkeypatch.setattr(um, "get_settings", lambda: fake)
    payload = {"signal": 1.0, "signal_pct": 5.8, "as_of": date.today().isoformat()}
    storage = MagicMock(); storage.get_app_setting = AsyncMock(return_value=json.dumps(payload))
    monkeypatch.setattr(um, "get_storage_service", AsyncMock(return_value=storage))
    got = await um.get_cached_us_ai_signal()
    assert got["signal"] == 1.0


async def test_get_cached_stale_returns_none(monkeypatch):
    fake = MagicMock(); fake.US_SIGNAL_ENABLED = True
    monkeypatch.setattr(um, "get_settings", lambda: fake)
    payload = {"signal": 1.0, "as_of": "2020-01-01"}
    storage = MagicMock(); storage.get_app_setting = AsyncMock(return_value=json.dumps(payload))
    monkeypatch.setattr(um, "get_storage_service", AsyncMock(return_value=storage))
    assert await um.get_cached_us_ai_signal() is None


async def test_get_cached_disabled_none(monkeypatch):
    fake = MagicMock(); fake.US_SIGNAL_ENABLED = False
    monkeypatch.setattr(um, "get_settings", lambda: fake)
    assert await um.get_cached_us_ai_signal() is None


def test_scheduler_disabled_returns_none(monkeypatch):
    fake = MagicMock(); fake.US_SIGNAL_ENABLED = False
    monkeypatch.setattr(um, "get_settings", lambda: fake)
    assert um.start_us_signal_scheduler() is None


async def test_scheduler_enabled_registers_cron_job(monkeypatch):
    # AsyncIOScheduler.start() requires a running event loop (matches real
    # usage: start_us_signal_scheduler() is called from the async lifespan).
    fake = MagicMock(); fake.US_SIGNAL_ENABLED = True
    monkeypatch.setattr(um, "get_settings", lambda: fake)
    sched = um.start_us_signal_scheduler()
    assert sched is not None
    assert len(sched.get_jobs()) == 1  # 일일 cron 1개
    sched.shutdown(wait=False)


# --- v2 T1: memory/accel/demand 서브신호 (additive, 최상위 스키마 불변) ---

def _snap(**pct):  # {"MU": 12.0, ...} → fetch 스냅샷 형태
    return {t: {"chg_pct": v, "prev_close": 100.0} for t, v in pct.items()}


def test_compute_includes_sub_signals_additive():
    snap = _snap(SMH=4.0, MU=12.0, NVDA=2.0, AVGO=3.0, MSFT=1.0, GOOGL=1.0, AMZN=1.0, META=1.0)
    out = um.compute_us_ai_signal(snap)
    # 최상위 하위호환 유지
    assert set(["signal", "signal_pct", "components", "as_of", "computed_at"]) <= set(out)
    # 서브신호 3종
    assert set(out["sub_signals"]) == {"memory", "accel", "demand"}
    # memory = MU·SMH 균등 → (12+4)/2 = 8.0%
    assert abs(out["sub_signals"]["memory"]["signal_pct"] - 8.0) < 1e-6
    # accel = NVDA0.6·AVGO0.4 → 2*0.6+3*0.4 = 2.4%
    assert abs(out["sub_signals"]["accel"]["signal_pct"] - 2.4) < 1e-6
    # demand = 4종 균등 1.0% → 1.0
    assert abs(out["sub_signals"]["demand"]["signal_pct"] - 1.0) < 1e-6


def test_all_signal_tickers_is_union_dedup():
    ts = um._all_signal_tickers()
    assert set(ts) >= {"SMH", "MU", "NVDA", "AVGO", "MSFT", "GOOGL", "AMZN", "META"}
    assert len(ts) == len(set(ts))  # dedup (SMH/MU/NVDA는 overall과 memory/accel에 중복)


def test_get_subsignal_fallback_to_overall():
    cached = {"signal": 0.5, "signal_pct": 1.5, "components": {"SMH": 1.5},
              "sub_signals": {"memory": {"signal": 0.9, "signal_pct": 2.7, "components": {"MU": 2.7}}}}
    assert um.get_subsignal(cached, "memory")["signal"] == 0.9
    # 없는 타입 → overall 폴백
    assert um.get_subsignal(cached, "accel")["signal"] == 0.5
    assert um.get_subsignal(None, "memory") is None


def test_missing_ticker_renormalizes_subsignal():
    snap = _snap(MU=10.0)  # SMH 없음
    out = um.compute_us_ai_signal(snap)
    # memory는 MU만으로 재정규화 → 10.0
    assert abs(out["sub_signals"]["memory"]["signal_pct"] - 10.0) < 1e-6
    # accel/demand 티커 전무 → 서브신호에서 생략
    assert "accel" not in out["sub_signals"]


async def test_refresh_fetches_union_of_all_tickers(monkeypatch):
    fake = MagicMock(); fake.US_SIGNAL_ENABLED = True
    monkeypatch.setattr(um, "get_settings", lambda: fake)
    snapshot = {"SMH": {"chg_pct": 2.0, "prev_close": 1.0}}
    fetch_mock = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(um, "fetch_us_ai_overnight", fetch_mock)
    storage = MagicMock(); storage.set_app_setting = AsyncMock()
    monkeypatch.setattr(um, "get_storage_service", AsyncMock(return_value=storage))

    await um.refresh_us_ai_signal_cache()

    fetch_mock.assert_awaited_once_with(um._all_signal_tickers())
