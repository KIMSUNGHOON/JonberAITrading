"""Phase3 T3: strategy panel — context assembly from Phase1/2 ledgers and
the 3-panelist structured-only LLM round.

LLM is stubbed at THIS module's import site
(services.trading.strategy_panel.get_llm_provider) — the provider facade is
captured per-call inside run_strategy_panel, so patching the module symbol
is sufficient (unlike base_agent, which captures at __init__).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.storage_service import StorageService
from services.trading import strategy_panel as strategy_panel_module
from services.trading.strategy_panel import (
    PANELISTS,
    build_strategy_context,
    run_strategy_panel,
)

pytestmark = pytest.mark.asyncio

_TRADE_DATE = "2026-07-15"
_KNOBS = {"risk_tolerance": "moderate", "max_position_pct": 0.10}


async def _seed_eod_review(storage, trade_date=_TRADE_DATE, report=None):
    report = report or {
        "trade_date": trade_date,
        "portfolio": {"equity": 500_000_000, "net_pnl": -120_000,
                      "win_trades": 1, "loss_trades": 2,
                      "realized_pnl": -100_000, "cumulative_return_pct": -0.02,
                      "exposure": 0.4, "concentration": 0.5},
        "per_stock": [{"stk_cd": "005930", "realized_amount": -80_000,
                       "entry_decision_id": "d1", "thesis_valid": False}],
        "agents": [{"agent_type": "sentiment", "accuracy": 0.33, "decisions_scored": 3}],
        "regime": {"regime_snapshot_id": "r1", "label": "risk_off", "breadth_ratio": -0.2},
    }
    await storage.save_eod_review(
        {"trade_date": trade_date, "report_json": json.dumps(report)}
    )


async def test_context_none_without_eod_review(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    assert await build_strategy_context(storage, _TRADE_DATE, _KNOBS) is None


async def test_context_none_when_review_is_error_only(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await storage.save_eod_review({
        "trade_date": _TRADE_DATE,
        "report_json": json.dumps({"trade_date": _TRADE_DATE, "error": "boom"}),
    })
    assert await build_strategy_context(storage, _TRADE_DATE, _KNOBS) is None


async def test_context_assembles_all_sections(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_eod_review(storage)
    # regime accrete 함정: 같은 날 2행 → 최신(나중 저장) 행만 남아야 함
    await storage.save_regime_snapshot({
        "id": "r-old", "trade_date": _TRADE_DATE, "breadth_buy": 1,
        "breadth_sell": 1, "breadth_hold": 1, "breadth_ratio": 0.0,
        "regime_label": "neutral",
    })
    await storage.save_regime_snapshot({
        "id": "r-new", "trade_date": _TRADE_DATE, "breadth_buy": 5,
        "breadth_sell": 20, "breadth_hold": 5, "breadth_ratio": -0.5,
        "regime_label": "risk_off",
    })
    await storage.save_daily_perf_snapshot({
        "trade_date": _TRADE_DATE, "equity": 500_000_000, "realized_pnl": -100_000,
        "commission": 0, "tax": 0, "net_pnl": -120_000,
        "win_trades": 1, "loss_trades": 2, "cumulative_return_pct": -0.02,
    })

    context = await build_strategy_context(storage, _TRADE_DATE, _KNOBS)
    assert context["trade_date"] == _TRADE_DATE
    assert context["eod_review"]["portfolio"]["net_pnl"] == -120_000
    assert context["current_strategy"] == _KNOBS
    regime_rows = [r for r in context["regime_history"] if r["trade_date"] == _TRADE_DATE]
    assert len(regime_rows) == 1 and regime_rows[0]["id"] == "r-new"
    assert context["perf_history"][0]["net_pnl"] == -120_000
    assert isinstance(context["calibration"], list)
    # DS-5 폐루프: 발굴 성과가 없을 때는 빈 요약({})이지 예외/None이 아니다
    # (get_discovery_performance 자체의 no-data 계약).
    assert context["discovery_performance"] == {}


async def test_context_includes_discovery_performance_summary(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_eod_review(storage)
    await storage.save_discovery_candidates([
        {
            "trade_date": _TRADE_DATE, "ticker": "005930", "name": "삼성전자",
            "composite_score": 0.8,
            "strategy_scores_json": {"momentum": 0.8, "pullback": 0.1, "flow": 0.1, "meanrev": 0.0},
            "regime_label": "neutral", "rank": 1,
            "llm_verdict_json": {"suitable": True}, "promoted": 1,
            "skip_reason": None, "close_price": 70000.0,
        }
    ])

    context = await build_strategy_context(storage, _TRADE_DATE, _KNOBS)

    assert "momentum" in context["discovery_performance"]
    assert context["discovery_performance"]["momentum"]["candidates"] == 1
    assert context["discovery_performance"]["momentum"]["promoted"] == 1


async def test_context_discovery_performance_failure_degrades_to_none(tmp_path, monkeypatch):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_eod_review(storage)

    async def _boom(*_a, **_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(strategy_panel_module, "get_discovery_performance", _boom)

    context = await build_strategy_context(storage, _TRADE_DATE, _KNOBS)

    assert context is not None
    assert context["discovery_performance"] is None
    # 패널의 나머지 기존 거동은 불변.
    assert context["eod_review"]["portfolio"]["net_pnl"] == -120_000


async def test_panel_returns_three_votes(tmp_path):
    vote = {"stance": "defensive", "confidence": 0.8, "reasoning": "손실 방어",
            "key_factors": ["risk_off"], "adjustments": {"stop_loss_pct": 0.05}}
    provider = MagicMock()
    provider.generate_structured = AsyncMock(return_value=dict(vote))
    with patch("services.trading.strategy_panel.get_llm_provider", return_value=provider):
        votes = await run_strategy_panel({"trade_date": _TRADE_DATE})
    assert len(votes) == len(PANELISTS) == 3
    assert {v["panelist"] for v in votes} == set(PANELISTS)
    assert all(v["stance"] == "defensive" for v in votes)
    assert provider.generate_structured.await_count == 3


async def test_panel_failure_becomes_error_entry_not_raise():
    ok = {"stance": "neutral", "confidence": 0.6, "reasoning": "유지"}
    provider = MagicMock()
    provider.generate_structured = AsyncMock(
        side_effect=[dict(ok), ValueError("bad json"), dict(ok)]
    )
    with patch("services.trading.strategy_panel.get_llm_provider", return_value=provider):
        votes = await run_strategy_panel({"trade_date": _TRADE_DATE})
    errors = [v for v in votes if v.get("error")]
    assert len(errors) == 1 and "bad json" in errors[0]["error"]
    assert len([v for v in votes if v.get("stance")]) == 2


async def test_panel_all_backends_down_yields_all_errors():
    provider = MagicMock()
    provider.generate_structured = AsyncMock(side_effect=RuntimeError("all backends failed"))
    with patch("services.trading.strategy_panel.get_llm_provider", return_value=provider):
        votes = await run_strategy_panel({"trade_date": _TRADE_DATE})
    assert len(votes) == 3 and all(v.get("error") for v in votes)
