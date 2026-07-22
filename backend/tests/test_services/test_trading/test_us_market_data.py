import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

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


async def test_refresh_disabled_is_noop(monkeypatch):
    fake = MagicMock(); fake.US_SIGNAL_ENABLED = False
    monkeypatch.setattr(um, "get_settings", lambda: fake)
    assert await um.refresh_us_ai_signal_cache() is None


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
