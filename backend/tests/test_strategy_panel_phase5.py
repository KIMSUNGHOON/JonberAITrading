# backend/tests/test_strategy_panel_phase5.py
import json
import pytest
from services.trading import strategy_panel


class _FakeStorage:
    def __init__(self, regimes, review_report):
        self._regimes = regimes
        self._report = review_report
    async def get_eod_reviews(self, limit=40):
        return [{"trade_date": "2026-07-16", "report_json": json.dumps(self._report)}]
    async def get_regime_snapshots(self, limit=60): return self._regimes
    async def get_daily_perf_snapshots(self, limit=30): return []
    async def get_agent_calibration(self, as_of_date=None): return []


@pytest.mark.asyncio
async def test_regime_history_carries_phase5_fields():
    regimes = [{
        "trade_date": "2026-07-16", "id": "r1", "regime_label": "risk_on",
        "breadth_ratio": 0.5, "market_sentiment_label": "bullish",
        "sentiment_score": 0.6, "index_kospi_chg_pct": 1.5,
        "index_kosdaq_chg_pct": 1.0, "foreign_net_amount": 500.0,
        "institution_net_amount": 300.0,
    }]
    storage = _FakeStorage(regimes, {"portfolio": {"net_pnl": 100}})
    ctx = await strategy_panel.build_strategy_context(storage, "2026-07-16", {"max_position_pct": 0.1})
    assert ctx is not None
    r0 = ctx["regime_history"][0]
    assert r0["market_sentiment_label"] == "bullish"
    assert r0["sentiment_score"] == 0.6
    assert r0["index_kospi_chg_pct"] == 1.5
    assert r0["foreign_net_amount"] == 500.0


def test_regime_strategist_prompt_mentions_index_and_flow():
    prompt = strategy_panel.PANELISTS["regime_strategist"]
    assert "지수" in prompt
    assert "수급" in prompt
