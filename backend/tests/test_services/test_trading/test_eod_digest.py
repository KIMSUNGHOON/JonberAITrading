"""Phase E3 Task 1: eod_digest 조립기 (aggregation, NO LLM).

`build_eod_digest(*, coordinator, storage, trade_date)` (keyword-only —
see module docstring's NOTE) joins the watch list,
account/holdings snapshot, latest strategy revision, and latest market
regime into ONE digest dict that downstream tasks depend on as a fixed
contract: E3-2 (LLM narrative) reads it as the source-of-truth for a
Korean briefing, E3-3 (Telegram template) and E3-5 (FE render) both render
its 5 sections verbatim. See docs/superpowers/specs/2026-07-17-three-
issues-design.md §3 (Task E3-1/T6) and docs/superpowers/plans/
2026-07-17-three-issues.md's Task E3-1 for the authoritative schema.

Failure-harmless by design, mirroring eod_review.build_eod_review: each
section is built by its own independently try/except-guarded helper, so
one broken/missing source degrades only that section (to None or []),
never the whole digest. The whole body is additionally wrapped so a truly
unexpected failure still returns a dict shaped exactly like the happy path
(all 5 keys present, degraded to None/[]) rather than raising or omitting
keys — every consumer can rely on the 5 keys always existing.
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.storage_service import StorageService
from services.trading import eod_digest as eod_digest_module
from services.trading.eod_digest import build_eod_digest, narrate_eod_digest
from services.trading.models import ManagedPosition, WatchedStock

pytestmark = pytest.mark.asyncio


# -------------------------------------------
# Stand-ins
# -------------------------------------------


class _StubCoordinator:
    """Minimal stand-in for ExecutionCoordinator — only the sync methods/
    property the digest reads: `.get_watch_list()`, `.get_portfolio_
    summary()`, `.state.positions` (best-effort stop_loss/take_profit
    enrichment for holdings; a bare stub without `.state` must still
    degrade cleanly, see test below)."""

    def __init__(self, watch_list=None, summary=None, state_positions=None):
        self._watch_list = watch_list if watch_list is not None else []
        self._summary = summary if summary is not None else {}
        self._state_positions = state_positions if state_positions is not None else []

    def get_watch_list(self):
        return self._watch_list

    def get_portfolio_summary(self) -> dict:
        return self._summary

    @property
    def state(self):
        return SimpleNamespace(positions=self._state_positions)


class _BareStubCoordinator:
    """Only implements the two required methods — no `.state` property at
    all, exercising the holdings stop_loss/take_profit enrichment's
    fallback-to-None path (getattr-style optional read)."""

    def __init__(self, watch_list, summary):
        self._watch_list = watch_list
        self._summary = summary

    def get_watch_list(self):
        return self._watch_list

    def get_portfolio_summary(self) -> dict:
        return self._summary


class _ExplodingMethodStorage:
    """Wraps a real StorageService, raising for exactly one named async
    method while delegating everything else — isolates "this one storage
    read failed" from "the whole storage is gone"."""

    def __init__(self, storage: StorageService, boom_method: str):
        self._storage = storage
        self._boom_method = boom_method

    def __getattr__(self, name):
        if name == self._boom_method:
            async def _raise(*_a, **_kw):
                raise RuntimeError(f"boom:{name}")
            return _raise
        return getattr(self._storage, name)


def _watch_item(ticker="005930", stock_name="삼성전자", current_price=68000, target=70000):
    return WatchedStock(
        session_id="s1",
        ticker=ticker,
        stock_name=stock_name,
        signal="hold",
        confidence=0.62,
        current_price=current_price,
        target_entry_price=target,
    )


def _portfolio_summary(positions=None):
    return {
        "total_equity": 500_000_000,
        "cash": 400_000_000,
        "cash_ratio": 80.0,
        "stock_value": 100_000_000,
        "stock_ratio": 20.0,
        "positions": positions if positions is not None else [
            {
                "ticker": "005930",
                "stock_name": "삼성전자",
                "quantity": 10,
                "avg_price": 68000,
                "current_price": 70000,
                "value": 700000,
                "weight_pct": 0.14,
                "unrealized_pnl": 20000,
                "unrealized_pnl_pct": 2.94,
                "risk_score": 4,
            }
        ],
        "total_unrealized_pnl": 20000,
        "total_unrealized_pnl_pct": 2.94,
        "daily_trades": 1,
        "max_daily_trades": 20,
    }


def _managed_position(ticker="005930", stop_loss=63240, take_profit=78200):
    return ManagedPosition(
        ticker=ticker,
        stock_name="삼성전자",
        quantity=10,
        avg_price=68000,
        current_price=70000,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


async def _seed_strategy_revision(storage, trade_date, rationale="야간 선물 강세, 공격적 진입 유지.", changed=True):
    strategy_json = json.dumps(
        {
            "exit_conditions": {"stop_loss_pct": 0.07, "take_profit_pct": 0.15},
            "position_sizing": {"max_position_pct": 0.10, "max_trade_notional_pct": 15.0},
        }
    )
    await storage.save_strategy_revision(
        {
            "id": str(uuid.uuid4()),
            "trade_date": trade_date,
            "source": "eod_consensus",
            "stance": "cautious_bullish",
            "consensus_level": 0.8,
            "changed": changed,
            "strategy_json": strategy_json,
            "rationale": rationale,
        }
    )


async def _seed_regime_snapshot(storage, trade_date):
    await storage.save_regime_snapshot(
        {
            "id": str(uuid.uuid4()),
            "trade_date": trade_date,
            "breadth_buy": 300,
            "breadth_sell": 100,
            "breadth_hold": 100,
            "breadth_ratio": 0.4,
            "regime_label": "risk_on",
            "market_sentiment_label": "risk_on",
            "index_kospi_chg_pct": 0.8,
            "index_kosdaq_chg_pct": 1.2,
        }
    )


# -------------------------------------------
# Tests
# -------------------------------------------


async def test_build_eod_digest_assembles_all_sections(tmp_path):
    trade_date = "2026-07-17"
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    await storage.save_daily_perf_snapshot(
        {
            "trade_date": trade_date,
            "equity": 500_000_000,
            "realized_pnl": 120_000,
            "commission": 500,
            "tax": 284,
            "net_pnl": 119_216,
            "win_trades": 2,
            "loss_trades": 1,
            "cumulative_return_pct": 0.021,
        }
    )
    await _seed_strategy_revision(storage, trade_date)
    await _seed_regime_snapshot(storage, trade_date)

    coordinator = _StubCoordinator(
        watch_list=[_watch_item(current_price=68000, target=70000)],
        summary=_portfolio_summary(),
        state_positions=[_managed_position()],
    )

    digest = await build_eod_digest(coordinator=coordinator, storage=storage, trade_date=trade_date)

    assert digest["trade_date"] == trade_date

    watch = digest["watch"]
    assert len(watch) == 1
    w = watch[0]
    assert w["ticker"] == "005930"
    assert w["stock_name"] == "삼성전자"
    assert w["signal"] == "hold"
    assert w["confidence"] == 0.62
    assert w["current_price"] == 68000
    assert w["target_entry_price"] == 70000
    # (68000 - 70000) / 70000 * 100
    assert w["gap_pct"] == pytest.approx(-2.857142857142857)

    account = digest["account"]
    assert account["deposit"] == 400_000_000
    assert account["total_equity"] == 500_000_000
    assert account["daily_realized_pnl"] == 120_000
    assert account["cumulative_return_pct"] == 0.021

    holdings = digest["holdings"]
    assert len(holdings) == 1
    h = holdings[0]
    assert h["ticker"] == "005930"
    assert h["stock_name"] == "삼성전자"
    assert h["quantity"] == 10
    assert h["avg_price"] == 68000
    assert h["current_price"] == 70000
    assert h["unrealized_pnl"] == 20000
    assert h["unrealized_pnl_pct"] == 2.94
    assert h["stop_loss"] == 63240
    assert h["take_profit"] == 78200

    strategy = digest["strategy"]
    assert strategy["stance"] == "cautious_bullish"
    assert strategy["rationale_excerpt"] == "야간 선물 강세, 공격적 진입 유지."
    assert strategy["key_knobs"] == {
        "stop_loss_pct": 0.07,
        "take_profit_pct": 0.15,
        "max_position_pct": 0.10,
        "max_trade_notional_pct": 15.0,
    }
    assert strategy["changed"] is True

    regime = digest["regime"]
    assert regime["label"] == "risk_on"
    assert regime["index_kospi_chg_pct"] == 0.8
    assert regime["index_kosdaq_chg_pct"] == 1.2


async def test_build_eod_digest_holdings_degrade_when_state_unavailable(tmp_path):
    """A coordinator that only implements the two required methods (no
    `.state`) must still assemble holdings — stop_loss/take_profit simply
    degrade to None rather than raising."""
    trade_date = "2026-07-17"
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    coordinator = _BareStubCoordinator(
        watch_list=[],
        summary=_portfolio_summary(),
    )

    digest = await build_eod_digest(coordinator=coordinator, storage=storage, trade_date=trade_date)

    holdings = digest["holdings"]
    assert len(holdings) == 1
    assert holdings[0]["ticker"] == "005930"
    assert holdings[0]["stop_loss"] is None
    assert holdings[0]["take_profit"] is None


async def test_build_eod_digest_watch_list_failure_degrades_to_empty(tmp_path):
    trade_date = "2026-07-17"
    storage = StorageService(db_path=str(tmp_path / "t.db"))

    class _ExplodingWatchCoordinator(_StubCoordinator):
        def get_watch_list(self):
            raise RuntimeError("boom")

    coordinator = _ExplodingWatchCoordinator(summary=_portfolio_summary())

    digest = await build_eod_digest(coordinator=coordinator, storage=storage, trade_date=trade_date)

    assert "error" not in digest
    assert digest["watch"] == []
    # Rest of the digest is unaffected.
    assert digest["holdings"][0]["ticker"] == "005930"


async def test_build_eod_digest_portfolio_summary_failure_degrades_holdings_and_account(tmp_path):
    trade_date = "2026-07-17"
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    await storage.save_daily_perf_snapshot(
        {
            "trade_date": trade_date,
            "equity": 500_000_000,
            "realized_pnl": 120_000,
            "commission": 500,
            "tax": 284,
            "net_pnl": 119_216,
            "win_trades": 2,
            "loss_trades": 1,
            "cumulative_return_pct": 0.021,
        }
    )

    class _ExplodingSummaryCoordinator(_StubCoordinator):
        def get_portfolio_summary(self):
            raise RuntimeError("boom")

    coordinator = _ExplodingSummaryCoordinator(watch_list=[_watch_item()])

    digest = await build_eod_digest(coordinator=coordinator, storage=storage, trade_date=trade_date)

    assert "error" not in digest
    assert digest["holdings"] == []
    # account's deposit/total_equity come from get_portfolio_summary; they
    # degrade to None, but daily_realized_pnl/cumulative_return_pct (from
    # storage, an unrelated source) stay populated.
    assert digest["account"]["deposit"] is None
    assert digest["account"]["total_equity"] is None
    assert digest["account"]["daily_realized_pnl"] == 120_000
    assert digest["account"]["cumulative_return_pct"] == 0.021
    # watch is sourced independently and must be unaffected.
    assert len(digest["watch"]) == 1


async def test_build_eod_digest_daily_perf_snapshot_failure_degrades_account_only(tmp_path):
    trade_date = "2026-07-17"
    real_storage = StorageService(db_path=str(tmp_path / "t.db"))
    await _seed_strategy_revision(real_storage, trade_date)
    storage = _ExplodingMethodStorage(real_storage, "get_daily_perf_snapshots")
    coordinator = _StubCoordinator(summary=_portfolio_summary())

    digest = await build_eod_digest(coordinator=coordinator, storage=storage, trade_date=trade_date)

    assert "error" not in digest
    assert digest["account"]["daily_realized_pnl"] is None
    assert digest["account"]["cumulative_return_pct"] is None
    # deposit/total_equity are sourced independently and must be unaffected.
    assert digest["account"]["deposit"] == 400_000_000
    assert digest["account"]["total_equity"] == 500_000_000
    # strategy is an unrelated section and must be unaffected.
    assert digest["strategy"]["stance"] == "cautious_bullish"


async def test_build_eod_digest_strategy_revisions_failure_degrades_to_none(tmp_path):
    trade_date = "2026-07-17"
    real_storage = StorageService(db_path=str(tmp_path / "t.db"))
    await _seed_regime_snapshot(real_storage, trade_date)
    storage = _ExplodingMethodStorage(real_storage, "get_strategy_revisions")
    coordinator = _StubCoordinator(summary=_portfolio_summary())

    digest = await build_eod_digest(coordinator=coordinator, storage=storage, trade_date=trade_date)

    assert "error" not in digest
    assert digest["strategy"] is None
    # regime is an unrelated section and must be unaffected.
    assert digest["regime"]["label"] == "risk_on"


async def test_build_eod_digest_regime_snapshot_failure_degrades_to_none(tmp_path):
    trade_date = "2026-07-17"
    real_storage = StorageService(db_path=str(tmp_path / "t.db"))
    await _seed_strategy_revision(real_storage, trade_date)
    storage = _ExplodingMethodStorage(real_storage, "get_regime_snapshots")
    coordinator = _StubCoordinator(summary=_portfolio_summary())

    digest = await build_eod_digest(coordinator=coordinator, storage=storage, trade_date=trade_date)

    assert "error" not in digest
    assert digest["regime"] is None
    assert digest["strategy"]["stance"] == "cautious_bullish"


async def test_build_eod_digest_empty_watch_and_missing_regime_degrade(tmp_path):
    """No watch items, no regime_snapshot row at all (never saved, not a
    raise) — watch degrades to [] and regime to None, per spec."""
    trade_date = "2026-07-17"
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    coordinator = _StubCoordinator(watch_list=[], summary={})

    digest = await build_eod_digest(coordinator=coordinator, storage=storage, trade_date=trade_date)

    assert digest["watch"] == []
    assert digest["regime"] is None
    assert digest["strategy"] is None
    assert digest["holdings"] == []


async def test_build_eod_digest_rationale_excerpt_truncated_to_300_chars(tmp_path):
    trade_date = "2026-07-17"
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    long_rationale = "가" * 400
    await _seed_strategy_revision(storage, trade_date, rationale=long_rationale, changed=False)
    coordinator = _StubCoordinator(summary={})

    digest = await build_eod_digest(coordinator=coordinator, storage=storage, trade_date=trade_date)

    excerpt = digest["strategy"]["rationale_excerpt"]
    assert len(excerpt) == 300
    assert excerpt == long_rationale[:300]
    assert digest["strategy"]["changed"] is False


async def test_build_eod_digest_gap_pct_is_none_when_target_missing(tmp_path):
    trade_date = "2026-07-17"
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    watch = WatchedStock(
        session_id="s1",
        ticker="000660",
        stock_name="SK하이닉스",
        signal="sell",
        confidence=0.4,
        current_price=100000,
        target_entry_price=None,
    )
    coordinator = _StubCoordinator(watch_list=[watch], summary={})

    digest = await build_eod_digest(coordinator=coordinator, storage=storage, trade_date=trade_date)

    assert digest["watch"][0]["gap_pct"] is None


async def test_build_eod_digest_never_raises_when_everything_explodes(tmp_path):
    trade_date = "2026-07-17"

    class _ExplodingStorage:
        async def get_daily_perf_snapshots(self, *a, **kw):
            raise RuntimeError("boom")

        async def get_strategy_revisions(self, *a, **kw):
            raise RuntimeError("boom")

        async def get_regime_snapshots(self, *a, **kw):
            raise RuntimeError("boom")

    class _ExplodingCoordinator:
        def get_watch_list(self):
            raise RuntimeError("boom")

        def get_portfolio_summary(self):
            raise RuntimeError("boom")

    digest = await build_eod_digest(
        coordinator=_ExplodingCoordinator(), storage=_ExplodingStorage(), trade_date=trade_date
    )

    assert digest["trade_date"] == trade_date
    assert digest["watch"] == []
    assert digest["holdings"] == []
    assert digest["strategy"] is None
    assert digest["regime"] is None
    assert digest["account"] == {
        "deposit": None,
        "total_equity": None,
        "daily_realized_pnl": None,
        "cumulative_return_pct": None,
    }


async def test_build_eod_digest_rejects_positional_arguments(tmp_path):
    """리뷰 Important 픽스: coordinator/storage are duck-typed `Any`, so a
    transposed positional call (e.g. `build_eod_digest(storage,
    coordinator, trade_date)`) would previously degrade every section to
    empty/None without ever raising — a caller bug masquerading as a
    structurally valid, silently-corrupted digest. The signature is now
    keyword-only specifically to turn that mistake into an immediate
    TypeError at the call site instead of quiet data corruption.
    """
    trade_date = "2026-07-17"
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    coordinator = _StubCoordinator(summary=_portfolio_summary())

    with pytest.raises(TypeError):
        await build_eod_digest(coordinator, storage, trade_date)


# -------------------------------------------
# narrate_eod_digest (E3-2: LLM 내러티브, LLM 라우터 재사용)
# -------------------------------------------


def _sample_digest(trade_date="2026-07-17"):
    return {
        "trade_date": trade_date,
        "watch": [
            {
                "ticker": "005930",
                "stock_name": "삼성전자",
                "signal": "hold",
                "confidence": 0.62,
                "current_price": 68000,
                "target_entry_price": 70000,
                "gap_pct": -2.857142857142857,
            }
        ],
        "account": {
            "deposit": 400_000_000,
            "total_equity": 500_000_000,
            "daily_realized_pnl": 120_000,
            "cumulative_return_pct": 0.021,
        },
        "holdings": [
            {
                "ticker": "005930",
                "stock_name": "삼성전자",
                "quantity": 10,
                "avg_price": 68000,
                "current_price": 70000,
                "unrealized_pnl": 20000,
                "unrealized_pnl_pct": 2.94,
                "stop_loss": 63240,
                "take_profit": 78200,
            }
        ],
        "strategy": {
            "stance": "cautious_bullish",
            "rationale_excerpt": "야간 선물 강세, 공격적 진입 유지.",
            "key_knobs": {
                "stop_loss_pct": 0.07,
                "take_profit_pct": 0.15,
                "max_position_pct": 0.10,
                "max_trade_notional_pct": 15.0,
            },
            "changed": True,
        },
        "regime": {
            "label": "risk_on",
            "index_kospi_chg_pct": 0.8,
            "index_kosdaq_chg_pct": 1.2,
        },
    }


async def test_narrate_eod_digest_success_returns_stripped_text():
    digest = _sample_digest()
    provider = MagicMock()
    provider.generate = AsyncMock(
        return_value="  오늘 삼성전자 보유 종목은 2.94% 평가익을 기록했습니다.  "
    )

    with patch.object(eod_digest_module, "get_llm_provider", return_value=provider):
        narrative = await narrate_eod_digest(digest)

    assert narrative == "오늘 삼성전자 보유 종목은 2.94% 평가익을 기록했습니다."
    assert provider.generate.await_count == 1
    _, kwargs = provider.generate.await_args
    # digest content must actually reach the prompt (source-of-truth per
    # module docstring — the model must not hallucinate numbers).
    messages = provider.generate.await_args.args[0]
    joined = " ".join(m.content for m in messages)
    assert "005930" in joined
    assert "cautious_bullish" in joined
    # E3-1 review Important #2: strategy section must be framed as
    # "익일 적용 전략(EOD 합의)", never asserted as *today's* strategy,
    # since digest["strategy"] is the latest revision regardless of date.
    assert "익일 적용 전략" in joined


async def test_narrate_eod_digest_timeout_returns_none(monkeypatch):
    digest = _sample_digest()
    monkeypatch.setattr(eod_digest_module, "_NARRATE_TIMEOUT_SECONDS", 0.05)

    async def _slow_generate(*_a, **_kw):
        await asyncio.sleep(1.0)
        return "too late"

    provider = MagicMock()
    provider.generate = AsyncMock(side_effect=_slow_generate)

    with patch.object(eod_digest_module, "get_llm_provider", return_value=provider):
        narrative = await narrate_eod_digest(digest)

    assert narrative is None


async def test_narrate_eod_digest_exception_returns_none():
    digest = _sample_digest()
    provider = MagicMock()
    provider.generate = AsyncMock(side_effect=RuntimeError("all backends failed"))

    with patch.object(eod_digest_module, "get_llm_provider", return_value=provider):
        narrative = await narrate_eod_digest(digest)

    assert narrative is None


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
async def test_narrate_eod_digest_blank_response_returns_none(blank):
    digest = _sample_digest()
    provider = MagicMock()
    provider.generate = AsyncMock(return_value=blank)

    with patch.object(eod_digest_module, "get_llm_provider", return_value=provider):
        narrative = await narrate_eod_digest(digest)

    assert narrative is None


async def test_narrate_eod_digest_never_raises_on_none_generate_result():
    """A backend that returns None outright (not just blank string) must
    also degrade to None rather than raising in .strip()."""
    digest = _sample_digest()
    provider = MagicMock()
    provider.generate = AsyncMock(return_value=None)

    with patch.object(eod_digest_module, "get_llm_provider", return_value=provider):
        narrative = await narrate_eod_digest(digest)

    assert narrative is None
