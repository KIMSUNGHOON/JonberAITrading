import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.trading import eod_orchestrator


class _FakeStorage:
    def __init__(self):
        self.saved_regime = None
    async def save_regime_snapshot(self, rec): self.saved_regime = rec; return True
    async def save_eod_review(self, rec): return True
    async def backfill_regime_id(self, td, rid): pass
    async def backfill_market_context(self, td, sentiment_json, flow_json): pass
    async def get_eod_reviews(self, limit=40): return []


@pytest.mark.asyncio
async def test_enriches_regime_when_enabled_and_kiwoom_present(monkeypatch):
    storage = _FakeStorage()
    coord = MagicMock()
    coord._kiwoom = MagicMock()
    coord.get_portfolio_summary = MagicMock(return_value={})

    monkeypatch.setattr(eod_orchestrator, "compute_regime_snapshot",
                        lambda p, td: {"id": "b1", "trade_date": td, "breadth_ratio": 0.5,
                                       "regime_label": "risk_on", "source": "scanner"})
    async def _idx(c): return {"index_kospi": 2500.0, "index_kospi_chg_pct": 1.5,
                               "index_kosdaq": 850.0, "index_kosdaq_chg_pct": 1.0}
    async def _flow(c): return {"foreign_net_amount": 100.0, "institution_net_amount": 50.0}
    monkeypatch.setattr(eod_orchestrator, "fetch_index_snapshot", _idx)
    monkeypatch.setattr(eod_orchestrator, "fetch_market_flow", _flow)
    monkeypatch.setattr(eod_orchestrator, "label_and_calibrate", AsyncMock())
    monkeypatch.setattr(eod_orchestrator, "build_eod_review", AsyncMock(return_value={}))

    ok = await eod_orchestrator.run_eod_review(coord, storage, "2026-07-16")
    assert ok is True
    assert storage.saved_regime is not None
    assert storage.saved_regime["market_sentiment_label"] == "bullish"
    assert storage.saved_regime["index_kospi"] == 2500.0


@pytest.mark.asyncio
async def test_breadth_only_when_kiwoom_none(monkeypatch):
    storage = _FakeStorage()
    coord = MagicMock()
    coord._kiwoom = None
    coord.get_portfolio_summary = MagicMock(return_value={})
    monkeypatch.setattr(eod_orchestrator, "compute_regime_snapshot",
                        lambda p, td: {"id": "b1", "trade_date": td, "breadth_ratio": 0.0,
                                       "regime_label": "neutral", "source": "scanner"})
    monkeypatch.setattr(eod_orchestrator, "label_and_calibrate", AsyncMock())
    monkeypatch.setattr(eod_orchestrator, "build_eod_review", AsyncMock(return_value={}))

    ok = await eod_orchestrator.run_eod_review(coord, storage, "2026-07-16")
    assert ok is True
    # 페처 skip → 심화 없이 breadth 스냅샷 저장(신규 필드 None 또는 부재)
    assert storage.saved_regime is not None
    assert storage.saved_regime.get("index_kospi") is None


@pytest.mark.asyncio
async def test_never_raises_when_fetch_errors(monkeypatch):
    storage = _FakeStorage()
    coord = MagicMock()
    coord._kiwoom = MagicMock()
    coord.get_portfolio_summary = MagicMock(return_value={})
    monkeypatch.setattr(eod_orchestrator, "compute_regime_snapshot",
                        lambda p, td: {"id": "b1", "trade_date": td, "breadth_ratio": 0.5,
                                       "regime_label": "risk_on", "source": "scanner"})
    async def _boom(c): raise RuntimeError("1700")
    monkeypatch.setattr(eod_orchestrator, "fetch_index_snapshot", _boom)
    monkeypatch.setattr(eod_orchestrator, "fetch_market_flow", _boom)
    monkeypatch.setattr(eod_orchestrator, "label_and_calibrate", AsyncMock())
    monkeypatch.setattr(eod_orchestrator, "build_eod_review", AsyncMock(return_value={}))

    ok = await eod_orchestrator.run_eod_review(coord, storage, "2026-07-16")
    assert ok is True  # never-raise; enrich 실패해도 EOD 완주
