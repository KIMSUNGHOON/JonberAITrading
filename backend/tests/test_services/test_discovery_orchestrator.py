"""Discovery EOD post-processing orchestrator tests (DS-5).

`run_discovery_pipeline` (services/discovery/orchestrator.py) is the single
function the market-close chain (coordinator.py::_check_queue_on_market_open,
behind the DISCOVERY_ENABLED kill switch) calls AFTER the existing 8-step
chain's steps 3-7 and BEFORE step 8 (_notify_eod_summary): build a same-day
price lookup -> DS-3 backfill_forward_returns -> (scan_ok only) DS-4
rank_candidates -> llm_review_top -> promote_candidates -> summary dict.

Real DB schema via tmp-path StorageService (mirrors test_discovery_ranker.py)
plus a hand-seeded tmp scanner_results.db for the scan_ok=True path. LLM is
always a fake provider — real network/LLM calls are forbidden
(ds-global-constraints.md). Coordinator is a REAL `ExecutionCoordinator(
kiwoom_client=None)` (no network), mirroring test_discovery_ranker.py's own
convention.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import aiosqlite
import pytest

from services.discovery import ledger as ledger_module
from services.discovery import orchestrator as orchestrator_module
from services.discovery import ranker as ranker_module
from services.discovery.orchestrator import _build_price_lookup, run_discovery_pipeline
from services.storage_service import StorageService
from services.trading.coordinator import ExecutionCoordinator

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(tmp_path):
    return StorageService(db_path=str(tmp_path / "storage.db"))


@pytest.fixture
def coordinator():
    return ExecutionCoordinator(kiwoom_client=None)


class _FakeScanner:
    """Minimal BackgroundScanner stand-in — only the public surface
    `_build_price_lookup` reads (`get_results()`)."""

    def __init__(self, results):
        self._results = results

    def get_results(self):
        return self._results


class _BoomScanner:
    def get_results(self):
        raise RuntimeError("scanner boom")


def _scan_result(stk_cd, current_price):
    return SimpleNamespace(stk_cd=stk_cd, current_price=current_price)


class _FakeLLMProvider:
    """Mirrors test_discovery_ranker.py's own fake — ticker looked up by
    substring match against the HumanMessage content."""

    def __init__(self, responses: dict[str, str] | None = None):
        self.responses = responses or {}
        self.calls: list[str | None] = []

    async def generate(self, messages, task=None, **kwargs):
        content = messages[-1].content
        ticker = next((t for t in self.responses if f"({t})" in content), None)
        self.calls.append(ticker)
        return self.responses.get(
            ticker, '{"suitable": false, "confidence": 0.1, "rationale": "", "risks": ""}'
        )


_SCAN_SESSIONS_SCHEMA = """
CREATE TABLE scan_sessions (
    id TEXT PRIMARY KEY,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    total_stocks INTEGER,
    completed INTEGER,
    failed INTEGER,
    buy_count INTEGER,
    sell_count INTEGER,
    hold_count INTEGER,
    watch_count INTEGER,
    avoid_count INTEGER,
    status TEXT,
    universe_fallback INTEGER,
    scan_mode TEXT
)
"""

_SCAN_RESULTS_SCHEMA = """
CREATE TABLE scan_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stk_cd TEXT NOT NULL,
    stk_nm TEXT NOT NULL,
    action TEXT NOT NULL,
    signal TEXT,
    confidence REAL,
    summary TEXT,
    key_factors TEXT,
    current_price INTEGER,
    market_type TEXT,
    scanned_at TIMESTAMP,
    scan_session_id TEXT,
    factor_json TEXT
)
"""


def _passing_factor(
    momentum: float = 0.9,
    pullback: float = 0.9,
    flow: float = 0.9,
    meanrev: float = 0.9,
    close_price: float = 70_000.0,
    market_cap: float = 100_000_000_000.0,
) -> dict:
    return {
        "quality_filter_passed": True,
        "skip_reason": None,
        "scores": {
            "momentum": momentum, "pullback": pullback,
            "flow": flow, "meanrev": meanrev,
        },
        "atoms": {},
        "close_price": close_price,
        "market_cap": market_cap,
    }


async def _seed_scanner_db(
    db_path,
    trade_date: str,
    results: list[dict],
    *,
    session_id: str = "sess-1",
    status: str = "completed",
    scan_mode: str = "discovery",
) -> str:
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(_SCAN_SESSIONS_SCHEMA)
        await db.execute(_SCAN_RESULTS_SCHEMA)
        await db.execute(
            """
            INSERT INTO scan_sessions
            (id, started_at, completed_at, total_stocks, completed, failed,
             buy_count, sell_count, hold_count, watch_count, avoid_count,
             status, universe_fallback, scan_mode)
            VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, ?, 0, ?, 0, ?)
            """,
            (
                session_id,
                f"{trade_date} 15:40:00",
                f"{trade_date} 16:10:00",
                len(results),
                len(results),
                len(results),
                status,
                scan_mode,
            ),
        )
        for r in results:
            fj = r["factor_json"]
            await db.execute(
                """
                INSERT INTO scan_results
                (stk_cd, stk_nm, action, signal, confidence, summary,
                 key_factors, current_price, market_type, scanned_at,
                 scan_session_id, factor_json)
                VALUES (?, ?, 'WATCH', 'discovery', 0.0, '', '', ?, '', ?, ?, ?)
                """,
                (
                    r["stk_cd"],
                    r["stk_nm"],
                    int(fj.get("close_price") or 0),
                    f"{trade_date} 15:41:00",
                    session_id,
                    json.dumps(fj, ensure_ascii=False),
                ),
            )
        await db.commit()
    return session_id


async def _seed_regime_snapshot(storage: StorageService, trade_date: str, label: str) -> None:
    import uuid

    await storage.save_regime_snapshot(
        {"id": str(uuid.uuid4()), "trade_date": trade_date, "market_sentiment_label": label}
    )


# ---------------------------------------------------------------------------
# ① _build_price_lookup — reads scanner.get_results(), excludes bad rows
# ---------------------------------------------------------------------------


def test_build_price_lookup_excludes_missing_ticker_and_nonpositive_price():
    scanner = _FakeScanner(
        [
            _scan_result("005930", 70_000),
            _scan_result("000660", 0),  # 실패 수집(가격 0) — 제외
            _scan_result(None, 50_000),  # 티커 없음 — 제외
            _scan_result("035420", 200_000),
        ]
    )

    lookup = _build_price_lookup(scanner)

    assert lookup == {"005930": 70_000.0, "035420": 200_000.0}


def test_build_price_lookup_scanner_exception_degrades_to_empty_dict():
    lookup = _build_price_lookup(_BoomScanner())
    assert lookup == {}


def test_build_price_lookup_empty_results_is_empty_dict():
    assert _build_price_lookup(_FakeScanner([])) == {}


# ---------------------------------------------------------------------------
# ② scan_ok=True: full chain (backfill -> rank -> LLM review -> promote)
# ---------------------------------------------------------------------------


async def test_pipeline_scan_ok_promotes_and_returns_summary(tmp_path, storage, coordinator, monkeypatch):
    trade_date = "2026-07-20"
    scanner_db = tmp_path / "scanner.db"
    monkeypatch.setattr(orchestrator_module, "SCANNER_DB_PATH", scanner_db)
    await _seed_regime_snapshot(storage, trade_date, "neutral")

    await _seed_scanner_db(
        scanner_db, trade_date,
        [{"stk_cd": "005930", "stk_nm": "삼성전자", "factor_json": _passing_factor()}],
    )

    fake_llm = _FakeLLMProvider(
        responses={"005930": '{"suitable": true, "confidence": 0.9, "rationale": "ok", "risks": "-"}'}
    )
    monkeypatch.setattr(ranker_module, "get_llm_provider", lambda: fake_llm)

    scanner = _FakeScanner([_scan_result("005930", 70_000)])

    summary = await run_discovery_pipeline(
        coordinator=coordinator, storage=storage, scanner=scanner,
        trade_date=trade_date, scan_ok=True,
    )

    assert summary is not None
    assert summary["trade_date"] == trade_date
    assert summary["scan_ok"] is True
    assert summary["promoted"] == ["005930"]
    assert summary["skipped"] == {}
    assert summary["total_candidates"] == 1
    assert isinstance(summary["backfilled"], int)

    ledger = await storage.get_discovery_candidates(trade_date=trade_date)
    assert len(ledger) == 1
    assert ledger[0]["promoted"] == 1
    assert "005930" in {w.ticker for w in coordinator.get_watch_list()}


async def test_pipeline_scan_ok_backfills_past_candidate_using_price_lookup(
    tmp_path, storage, coordinator, monkeypatch
):
    """Same-day price_lookup (from the scanner's in-memory results, NOT an
    extra API call) backfills a past candidate whose trading-day distance
    to today is exactly 1 (DS-3 exact-slot semantics). Exercises the REAL
    `backfill_forward_returns` (not a spy) end-to-end -- only the default
    (production/network-backed) holiday-service singleton is stubbed out,
    via ledger.py's own `_get_default_holiday_service` lazy-import seam."""
    trade_date = "2026-07-20"
    past_date = "2026-07-17"
    scanner_db = tmp_path / "scanner.db"
    monkeypatch.setattr(orchestrator_module, "SCANNER_DB_PATH", scanner_db)
    await _seed_regime_snapshot(storage, trade_date, "neutral")
    await _seed_scanner_db(scanner_db, trade_date, [])  # 오늘 세션은 완료됐지만 후보 0

    await storage.save_discovery_candidates(
        [
            {
                "trade_date": past_date, "ticker": "000660", "name": "SK하이닉스",
                "composite_score": 0.6,
                "strategy_scores_json": {"momentum": 0.6, "pullback": 0.1, "flow": 0.1, "meanrev": 0.1},
                "regime_label": "neutral", "rank": 1,
                "llm_verdict_json": None, "promoted": 0,
                "skip_reason": "below_threshold", "close_price": 100_000.0,
            }
        ]
    )

    scanner = _FakeScanner([_scan_result("000660", 110_000)])

    class _StubHolidayService:
        def get_trading_days_in_range(self, start, end):
            # past_date -> trade_date 사이 정확히 1거래일 경과로 취급.
            return [start, end]

    monkeypatch.setattr(
        ledger_module, "_get_default_holiday_service", lambda: _StubHolidayService()
    )

    summary = await run_discovery_pipeline(
        coordinator=coordinator, storage=storage, scanner=scanner,
        trade_date=trade_date, scan_ok=True,
    )

    assert summary is not None
    assert summary["backfilled"] == 1

    ledger = await storage.get_discovery_candidates(trade_date=past_date)
    assert ledger[0]["fwd_1d"] == pytest.approx((110_000 / 100_000.0) - 1.0)


# ---------------------------------------------------------------------------
# ③ scan_ok=False: rank/llm/promote never invoked, backfill still attempted
# ---------------------------------------------------------------------------


async def test_pipeline_scan_not_ok_skips_ranking_but_still_backfills(
    tmp_path, storage, coordinator, monkeypatch
):
    trade_date = "2026-07-20"

    async def _boom_rank(*a, **kw):
        raise AssertionError("rank_candidates must not be called when scan_ok=False")

    async def _boom_llm(*a, **kw):
        raise AssertionError("llm_review_top must not be called when scan_ok=False")

    async def _boom_promote(*a, **kw):
        raise AssertionError("promote_candidates must not be called when scan_ok=False")

    monkeypatch.setattr(orchestrator_module, "rank_candidates", _boom_rank)
    monkeypatch.setattr(orchestrator_module, "llm_review_top", _boom_llm)
    monkeypatch.setattr(orchestrator_module, "promote_candidates", _boom_promote)

    scanner = _FakeScanner([_scan_result("005930", 70_000)])

    summary = await run_discovery_pipeline(
        coordinator=coordinator, storage=storage, scanner=scanner,
        trade_date=trade_date, scan_ok=False,
    )

    assert summary is not None
    assert summary["scan_ok"] is False
    assert summary["total_candidates"] == 0
    assert summary["promoted"] == []
    assert summary["skipped"] == {}
    assert isinstance(summary["backfilled"], int)  # backfill_forward_returns 정상 시도됨


async def test_pipeline_scan_not_ok_still_attempts_backfill_with_partial_prices(
    storage, coordinator, monkeypatch
):
    """price_lookup 구성은 scan_ok와 무관하게 항상 시도된다 — 스캐너가
    타임아웃되기 전 이미 모은 부분 결과만으로 backfill을 시도한다."""
    trade_date = "2026-07-20"
    calls = {}

    async def _spy_backfill(storage, price_lookup, td):
        calls["price_lookup"] = price_lookup
        calls["trade_date"] = td
        return 0

    monkeypatch.setattr(orchestrator_module, "backfill_forward_returns", _spy_backfill)

    scanner = _FakeScanner([_scan_result("005930", 70_000), _scan_result("000660", 0)])

    summary = await run_discovery_pipeline(
        coordinator=coordinator, storage=storage, scanner=scanner,
        trade_date=trade_date, scan_ok=False,
    )

    assert summary is not None
    assert calls["price_lookup"] == {"005930": 70_000.0}
    assert calls["trade_date"] == trade_date


# ---------------------------------------------------------------------------
# ④ 예외 무해 — 어느 단계에서 터져도 None 반환, raise 안 함
# ---------------------------------------------------------------------------


async def test_pipeline_backfill_exception_returns_none_never_raises(storage, coordinator, monkeypatch):
    async def _boom(*a, **kw):
        raise RuntimeError("ledger backfill boom")

    monkeypatch.setattr(orchestrator_module, "backfill_forward_returns", _boom)
    scanner = _FakeScanner([_scan_result("005930", 70_000)])

    result = await run_discovery_pipeline(
        coordinator=coordinator, storage=storage, scanner=scanner,
        trade_date="2026-07-20", scan_ok=True,
    )

    assert result is None


async def test_pipeline_rank_candidates_exception_returns_none_never_raises(
    storage, coordinator, monkeypatch
):
    async def _boom(*a, **kw):
        raise RuntimeError("rank boom")

    monkeypatch.setattr(orchestrator_module, "rank_candidates", _boom)
    scanner = _FakeScanner([_scan_result("005930", 70_000)])

    result = await run_discovery_pipeline(
        coordinator=coordinator, storage=storage, scanner=scanner,
        trade_date="2026-07-20", scan_ok=True,
    )

    assert result is None


async def test_pipeline_promote_candidates_exception_returns_none_never_raises(
    tmp_path, storage, coordinator, monkeypatch
):
    trade_date = "2026-07-20"
    scanner_db = tmp_path / "scanner.db"
    monkeypatch.setattr(orchestrator_module, "SCANNER_DB_PATH", scanner_db)
    await _seed_regime_snapshot(storage, trade_date, "neutral")
    await _seed_scanner_db(
        scanner_db, trade_date,
        [{"stk_cd": "005930", "stk_nm": "삼성전자", "factor_json": _passing_factor()}],
    )
    monkeypatch.setattr(ranker_module, "get_llm_provider", lambda: _FakeLLMProvider())

    async def _boom(*a, **kw):
        raise RuntimeError("promote boom")

    monkeypatch.setattr(orchestrator_module, "promote_candidates", _boom)
    scanner = _FakeScanner([_scan_result("005930", 70_000)])

    result = await run_discovery_pipeline(
        coordinator=coordinator, storage=storage, scanner=scanner,
        trade_date=trade_date, scan_ok=True,
    )

    assert result is None


# ---------------------------------------------------------------------------
# ⑤ 마감 체인 편입 (coordinator.py::_check_queue_on_market_open) — spec §3
#    삽입 순서: ①poll_fills ②expire → [DISCOVERY_ENABLED만: 스캔 트리거+대기]
#    → ③write_daily_snapshot ④run_eod_review ⑤run_strategy_consensus
#    ⑥wait_for_pending_trade_fill_writes ⑦reconcile_trade_ledger →
#    [DISCOVERY_ENABLED만: run_discovery_pipeline] → ⑧_notify_eod_summary.
#    off(기본)면 대괄호 블록 둘 다 미진입 — 기존 8단계 호출 시퀀스 byte-동일.
# ---------------------------------------------------------------------------

import inspect
from unittest.mock import AsyncMock

import services.storage_service as ss
from app.config import get_settings
from services.trading import coordinator as coordinator_module
from services.trading.coordinator import ExecutionCoordinator, ScanStatus


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    """Isolated SQLite storage wired into the get_storage_service() singleton
    (mirrors test_f3_fill_tracking.py/test_discovery_ranker.py's own fixture)
    -- every existing chain step below is monkeypatched to a tracker so none
    of them actually touch it, but `_check_queue_on_market_open` itself calls
    `get_storage_service()` directly several times regardless."""
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


def _stub_market_closed_edge(coord):
    """Force the open->closed edge on the NEXT `_check_queue_on_market_open`
    tick (mirrors test_f3_fill_tracking.py's `_stub_market` + `_market_was_
    open=True` combo)."""
    coord._market_was_open = True
    coord._market_hours.get_market_session = lambda market: SimpleNamespace(
        is_open=False, message=""
    )


def _tracker(name, calls, return_value=None):
    async def _fn(*args, **kwargs):
        calls.append((name, kwargs))
        return return_value
    return _fn


def _wire_existing_chain(monkeypatch, coord, calls):
    """Patch every one of the PRE-EXISTING 8 close-edge steps (2 bound
    methods + 6 module-level functions) as an order-recording stub, so a
    dynamic run of `_check_queue_on_market_open` can assert the ACTUAL call
    sequence (not just source text order)."""
    coord._poll_tracked_fills = _tracker("poll_tracked_fills", calls)
    coord._expire_tracked_orders_on_market_close = _tracker("expire_tracked_orders", calls)
    coord._notify_eod_summary = _tracker("notify_eod_summary", calls)
    monkeypatch.setattr(coordinator_module, "write_daily_snapshot", _tracker("write_daily_snapshot", calls))
    monkeypatch.setattr(coordinator_module, "run_eod_review", _tracker("run_eod_review", calls, True))
    monkeypatch.setattr(coordinator_module, "run_strategy_consensus", _tracker("run_strategy_consensus", calls, {}))
    monkeypatch.setattr(coordinator_module, "wait_for_pending_trade_fill_writes", _tracker("wait_for_pending_trade_fill_writes", calls))
    monkeypatch.setattr(coordinator_module, "reconcile_trade_ledger", _tracker("reconcile_trade_ledger", calls))


class _InstantCompleteScanner:
    """get_progress() reports RUNNING exactly once (the post-start_scan
    'did it actually start' guard) then COMPLETED forever after -- the poll
    loop's very first check exits immediately, no real sleeping needed.

    `is_running` starts False (nothing running yet -- the coordinator's own
    pre-start busy check, DS-5 review fix, must pass through to start_scan)
    and flips True once `start_scan` is actually called, mirroring the real
    scanner's own `_running` flag."""

    def __init__(self, calls):
        self._calls = calls
        self._get_progress_calls = 0
        self.is_running = False

    async def start_scan(self, **kwargs):
        self._calls.append(("scanner.start_scan", kwargs))
        self.is_running = True

    def get_progress(self):
        self._get_progress_calls += 1
        status = ScanStatus.RUNNING if self._get_progress_calls == 1 else ScanStatus.COMPLETED
        return SimpleNamespace(status=status)

    async def stop_scan(self):
        self._calls.append(("scanner.stop_scan", {}))

    def get_results(self):
        return []


class _AlwaysRunningScanner:
    """Never transitions off RUNNING -- exercises the timeout branch.

    `is_running` starts False (nothing running yet, same convention as
    `_InstantCompleteScanner`) and flips True once `start_scan` is called."""

    def __init__(self, calls):
        self._calls = calls
        self.is_running = False

    async def start_scan(self, **kwargs):
        self._calls.append(("scanner.start_scan", kwargs))
        self.is_running = True

    def get_progress(self):
        return SimpleNamespace(status=ScanStatus.RUNNING)

    async def stop_scan(self):
        self._calls.append(("scanner.stop_scan", {}))

    def get_results(self):
        return []


class _BusyScanner:
    """Important review fix: a scan (manual or otherwise) is ALREADY
    running when the coordinator's own discovery trigger fires.
    `start_scan()` on the real scanner is a silent no-op in this state
    (scanner.py:371-373 -- `if self._running: logger.warning(...); return`)
    and `get_progress().status` still reports RUNNING throughout (it's
    someone else's scan, not "not started") -- exactly the state that used
    to fool the old post-start_scan guard into polling a scan the
    coordinator never triggered and reporting scan_ok=True. `is_running`
    is True from construction and NEVER flips (unlike
    `_InstantCompleteScanner`/`_AlwaysRunningScanner`, whose `is_running`
    starts False and flips True on their own `start_scan`) -- this fake
    intentionally never lets `start_scan` change it, so a test can assert
    the busy guard alone (checked BEFORE calling `start_scan`) is what
    produced the skip, not a side effect of `start_scan` having run."""

    def __init__(self, calls):
        self._calls = calls
        self.is_running = True

    async def start_scan(self, **kwargs):
        self._calls.append(("scanner.start_scan", kwargs))

    def get_progress(self):
        return SimpleNamespace(status=ScanStatus.RUNNING)

    async def stop_scan(self):
        self._calls.append(("scanner.stop_scan", {}))

    def get_results(self):
        return []


def test_coordinator_close_edge_source_brackets_discovery_around_existing_chain():
    """Static pin (mirrors test_ledger_reconcile.py/test_strategy_orchestrator.py's
    own inspect.getsource ordering pins): the discovery scan-trigger sits
    strictly BEFORE write_daily_snapshot, and run_discovery_pipeline sits
    strictly AFTER reconcile_trade_ledger and BEFORE _notify_eod_summary --
    with every pre-existing step's relative order among itself unchanged."""
    source = inspect.getsource(ExecutionCoordinator._check_queue_on_market_open)

    idx = {
        name: source.index(needle)
        for name, needle in [
            ("expire", "await self._expire_tracked_orders_on_market_close()"),
            ("discovery_scan", "self._run_discovery_scan()"),
            ("write_daily_snapshot", "await write_daily_snapshot("),
            ("run_eod_review", "await run_eod_review("),
            ("run_strategy_consensus", "await run_strategy_consensus("),
            ("wait_for_pending_trade_fill_writes", "await wait_for_pending_trade_fill_writes()"),
            ("reconcile_trade_ledger", "await reconcile_trade_ledger("),
            ("discovery_pipeline", "await run_discovery_pipeline("),
            ("notify_eod_summary", "await self._notify_eod_summary("),
        ]
    }

    assert idx["expire"] < idx["discovery_scan"] < idx["write_daily_snapshot"]
    assert (
        idx["write_daily_snapshot"] < idx["run_eod_review"]
        < idx["run_strategy_consensus"] < idx["wait_for_pending_trade_fill_writes"]
        < idx["reconcile_trade_ledger"]
    )
    assert idx["reconcile_trade_ledger"] < idx["discovery_pipeline"] < idx["notify_eod_summary"]
    assert "settings.DISCOVERY_ENABLED" in source or "get_settings().DISCOVERY_ENABLED" in source


async def test_close_edge_discovery_off_chain_is_call_order_identical(temp_storage, monkeypatch):
    """DISCOVERY_ENABLED=False (default) -- the existing 8-step call
    sequence must be byte-identical to before this feature existed, and
    NEITHER the scanner NOR run_discovery_pipeline may be touched at all."""
    assert get_settings().DISCOVERY_ENABLED is False  # 기본값 확인(명시 monkeypatch 없음)

    coord = ExecutionCoordinator(kiwoom_client=None)
    _stub_market_closed_edge(coord)
    calls: list[tuple[str, dict]] = []
    _wire_existing_chain(monkeypatch, coord, calls)

    scanner_calls: list = []
    monkeypatch.setattr(
        coordinator_module, "get_background_scanner",
        AsyncMock(side_effect=AssertionError("get_background_scanner must not be called when off")),
    )
    monkeypatch.setattr(
        coordinator_module, "run_discovery_pipeline",
        AsyncMock(side_effect=AssertionError("run_discovery_pipeline must not be called when off")),
    )

    await coord._check_queue_on_market_open()

    assert [name for name, _ in calls] == [
        "poll_tracked_fills",
        "expire_tracked_orders",
        "write_daily_snapshot",
        "run_eod_review",
        "run_strategy_consensus",
        "wait_for_pending_trade_fill_writes",
        "reconcile_trade_ledger",
        "notify_eod_summary",
    ]


async def test_close_edge_discovery_on_inserts_scan_and_pipeline_in_order(temp_storage, monkeypatch):
    monkeypatch.setattr(get_settings(), "DISCOVERY_ENABLED", True)

    coord = ExecutionCoordinator(kiwoom_client=None)
    _stub_market_closed_edge(coord)
    calls: list[tuple[str, dict]] = []
    _wire_existing_chain(monkeypatch, coord, calls)

    scanner = _InstantCompleteScanner(calls)

    async def _fake_get_background_scanner():
        return scanner

    monkeypatch.setattr(coordinator_module, "get_background_scanner", _fake_get_background_scanner)

    pipeline_calls = []

    async def _fake_pipeline(**kwargs):
        pipeline_calls.append(kwargs)
        calls.append(("discovery_pipeline", kwargs))
        return {"promoted": []}

    monkeypatch.setattr(coordinator_module, "run_discovery_pipeline", _fake_pipeline)

    await coord._check_queue_on_market_open()

    assert [name for name, _ in calls] == [
        "poll_tracked_fills",
        "expire_tracked_orders",
        "scanner.start_scan",
        "write_daily_snapshot",
        "run_eod_review",
        "run_strategy_consensus",
        "wait_for_pending_trade_fill_writes",
        "reconcile_trade_ledger",
        "discovery_pipeline",
        "notify_eod_summary",
    ]
    assert len(pipeline_calls) == 1
    assert pipeline_calls[0]["scan_ok"] is True
    assert pipeline_calls[0]["coordinator"] is coord
    assert pipeline_calls[0]["scanner"] is scanner


async def test_close_edge_discovery_scan_timeout_chain_completes_promotion_skipped(
    temp_storage, monkeypatch
):
    """A scan that never finishes must not stall the market-close tick --
    the timeout fires, stop_scan() is called, and the REST of the chain
    (including run_discovery_pipeline, with scan_ok=False) still runs to
    completion in the same tick."""
    monkeypatch.setattr(get_settings(), "DISCOVERY_ENABLED", True)
    monkeypatch.setattr(coordinator_module, "_DISCOVERY_SCAN_TIMEOUT_SECONDS", 0.03)
    monkeypatch.setattr(coordinator_module, "_DISCOVERY_SCAN_POLL_INTERVAL_SECONDS", 0.01)

    coord = ExecutionCoordinator(kiwoom_client=None)
    _stub_market_closed_edge(coord)
    calls: list[tuple[str, dict]] = []
    _wire_existing_chain(monkeypatch, coord, calls)

    scanner = _AlwaysRunningScanner(calls)

    async def _fake_get_background_scanner():
        return scanner

    monkeypatch.setattr(coordinator_module, "get_background_scanner", _fake_get_background_scanner)

    pipeline_calls = []

    async def _fake_pipeline(**kwargs):
        pipeline_calls.append(kwargs)
        calls.append(("discovery_pipeline", kwargs))
        return {"promoted": []}

    monkeypatch.setattr(coordinator_module, "run_discovery_pipeline", _fake_pipeline)

    await coord._check_queue_on_market_open()  # must not raise / must not hang

    call_names = [name for name, _ in calls]
    assert call_names == [
        "poll_tracked_fills",
        "expire_tracked_orders",
        "scanner.start_scan",
        "scanner.stop_scan",
        "write_daily_snapshot",
        "run_eod_review",
        "run_strategy_consensus",
        "wait_for_pending_trade_fill_writes",
        "reconcile_trade_ledger",
        "discovery_pipeline",
        "notify_eod_summary",
    ]
    assert pipeline_calls[0]["scan_ok"] is False


async def test_close_edge_discovery_pipeline_exception_is_harmless_chain_still_notifies(
    temp_storage, monkeypatch
):
    """run_discovery_pipeline itself is already never-raise, but the
    coordinator's own call site ALSO wraps it in try/except per spec
    ("전체 discovery 블록 try/except") -- verify a raise there still lets
    _notify_eod_summary (the chain's last step) run."""
    monkeypatch.setattr(get_settings(), "DISCOVERY_ENABLED", True)

    coord = ExecutionCoordinator(kiwoom_client=None)
    _stub_market_closed_edge(coord)
    calls: list[tuple[str, dict]] = []
    _wire_existing_chain(monkeypatch, coord, calls)

    scanner = _InstantCompleteScanner(calls)

    async def _fake_get_background_scanner():
        return scanner

    monkeypatch.setattr(coordinator_module, "get_background_scanner", _fake_get_background_scanner)

    async def _boom_pipeline(**kwargs):
        raise RuntimeError("pipeline boom despite its own never-raise contract")

    monkeypatch.setattr(coordinator_module, "run_discovery_pipeline", _boom_pipeline)

    await coord._check_queue_on_market_open()  # must not raise

    call_names = [name for name, _ in calls]
    assert call_names == [
        "poll_tracked_fills",
        "expire_tracked_orders",
        "scanner.start_scan",
        "write_daily_snapshot",
        "run_eod_review",
        "run_strategy_consensus",
        "wait_for_pending_trade_fill_writes",
        "reconcile_trade_ledger",
        "notify_eod_summary",
    ]
    assert coord._market_was_open is False


# ---------------------------------------------------------------------------
# ⑥ Important 리뷰픽스: 수동 스캔 충돌 오판 — _run_discovery_scan은 이미
#    RUNNING인 스캐너(수동 스캔 등)를 자신이 막 시작한 스캔으로 착각해서는 안
#    된다. 옛 가드는 start_scan() 호출 *이후* get_progress().status로만
#    판단했는데, start_scan()은 이미 실행 중이면 조용히 no-op(예외도, 시그널
#    도 없음)이라 "내 스캔이 시작됨"과 "남의 스캔이 이미 돌고 있어서 내
#    start_scan이 no-op됨"을 구분하지 못했다 -- 둘 다 status==RUNNING으로
#    보였고, 결과적으로 수동 스캔을 끝까지 폴링한 뒤 scan_ok=True로
#    오판했다. 수정: start_scan 호출 *전에* scanner.is_running을 확인한다.
# ---------------------------------------------------------------------------


async def test_run_discovery_scan_busy_scanner_returns_false_without_starting(monkeypatch, caplog):
    """직접 단위 테스트: 이미 실행 중인 스캐너 목 -> start_scan은 아예
    호출되지 않고(단순 no-op 확인이 아니라 호출 자체가 없음을 핀), False를
    반환하며, discovery_scan_skipped_scanner_busy 경고 로그를 남긴다."""
    import logging

    coord = ExecutionCoordinator(kiwoom_client=None)
    calls: list = []
    scanner = _BusyScanner(calls)

    async def _fake_get_background_scanner():
        return scanner

    monkeypatch.setattr(coordinator_module, "get_background_scanner", _fake_get_background_scanner)

    with caplog.at_level(logging.WARNING):
        result = await coord._run_discovery_scan()

    assert result is False
    assert calls == []  # start_scan (and stop_scan) never called
    assert any("discovery_scan_skipped_scanner_busy" in rec.message for rec in caplog.records)


async def test_close_edge_discovery_scan_skips_when_scanner_already_busy_chain_completes(
    temp_storage, monkeypatch
):
    """통합 테스트: 마감 엣지 전체(_check_queue_on_market_open)를 실행해도
    바쁜 스캐너 앞에서 start_scan이 호출되지 않고, scan_ok=False가
    run_discovery_pipeline에 전달되며, 나머지 체인(백필 포함)은 끝까지
    완주한다."""
    monkeypatch.setattr(get_settings(), "DISCOVERY_ENABLED", True)

    coord = ExecutionCoordinator(kiwoom_client=None)
    _stub_market_closed_edge(coord)
    calls: list[tuple[str, dict]] = []
    _wire_existing_chain(monkeypatch, coord, calls)

    scanner = _BusyScanner(calls)

    async def _fake_get_background_scanner():
        return scanner

    monkeypatch.setattr(coordinator_module, "get_background_scanner", _fake_get_background_scanner)

    pipeline_calls = []

    async def _fake_pipeline(**kwargs):
        pipeline_calls.append(kwargs)
        calls.append(("discovery_pipeline", kwargs))
        return {"promoted": []}

    monkeypatch.setattr(coordinator_module, "run_discovery_pipeline", _fake_pipeline)

    await coord._check_queue_on_market_open()  # must not raise / must not hang

    call_names = [name for name, _ in calls]
    assert "scanner.start_scan" not in call_names  # busy guard skipped it entirely
    assert call_names == [
        "poll_tracked_fills",
        "expire_tracked_orders",
        "write_daily_snapshot",
        "run_eod_review",
        "run_strategy_consensus",
        "wait_for_pending_trade_fill_writes",
        "reconcile_trade_ledger",
        "discovery_pipeline",
        "notify_eod_summary",
    ]
    assert len(pipeline_calls) == 1
    assert pipeline_calls[0]["scan_ok"] is False  # promotion skipped, backfill still proceeds


# ---------------------------------------------------------------------------
# ⑦ Critical 리뷰픽스: _notify_eod_summary 내부의 discovery 섹션 freshness
#    미러 블록이 DISCOVERY_ENABLED 게이트 없이 매일 실행되고 있었다 -- off
#    일 때 신규 코드(≒ _build_discovery_section 호출)가 전혀 진입하지 않아야
#    한다는 계약 위반. 지금까지 빈 테이블 불변식 덕에 우연히 무해했을 뿐이다.
#
#    이 두 테스트는 `_notify_eod_summary`를 **실호출**한다 -- 위 섹션의
#    `_wire_existing_chain`처럼 `_notify_eod_summary` 자체를 스텁으로 갈아
#    끼우면 이 메서드 내부의 버그를 절대 잡을 수 없다는 것이 바로 리뷰가
#    지적한 테스트 갭이므로, 이 두 테스트에서는 그 방식을 쓰지 않는다.
# ---------------------------------------------------------------------------


async def _seed_minimal_eod_review(storage, trade_date: str) -> None:
    import json as _json

    await storage.save_eod_review({
        "trade_date": trade_date,
        "report_json": _json.dumps(
            {"digest": {"trade_date": trade_date}, "narrative": "오늘 요약"}
        ),
    })


def _stub_notify_transports(monkeypatch):
    """Telegram/WS transports stubbed to no-network fakes -- mirrors
    test_f3_fill_tracking.py's own direct _notify_eod_summary tests. Real
    network/DB calls are forbidden; this keeps the test hermetic while still
    exercising the REAL _notify_eod_summary method body."""
    import app.api.routes.websocket as ws_module
    import services.telegram as telegram_module

    class _NotReadyNotifier:
        is_ready = False

    async def _fake_get_telegram_notifier():
        return _NotReadyNotifier()

    async def _fake_broadcast(digest, narrative=None):
        pass

    monkeypatch.setattr(telegram_module, "get_telegram_notifier", _fake_get_telegram_notifier)
    monkeypatch.setattr(ws_module, "broadcast_eod_summary", _fake_broadcast)


async def test_notify_eod_summary_discovery_refresh_off_never_calls_build_section(
    temp_storage, monkeypatch
):
    """DISCOVERY_ENABLED=False(기본값) -- _notify_eod_summary를 실호출해도
    _build_discovery_section은 단 한 번도 호출되지 않아야 한다."""
    assert get_settings().DISCOVERY_ENABLED is False  # 기본값 확인(명시 monkeypatch 없음)

    today = "2026-07-18"
    await _seed_minimal_eod_review(temp_storage, today)
    _stub_notify_transports(monkeypatch)

    build_calls: list = []

    async def _spy_build_discovery_section(*args, **kwargs):
        build_calls.append((args, kwargs))
        return None

    monkeypatch.setattr(
        coordinator_module, "_build_discovery_section", _spy_build_discovery_section
    )

    coord = ExecutionCoordinator(kiwoom_client=None)
    result = await coord._notify_eod_summary(today)  # REAL call -- no stub replacement

    assert result is True
    assert build_calls == []


async def test_notify_eod_summary_discovery_refresh_on_calls_build_section(
    temp_storage, monkeypatch
):
    """DISCOVERY_ENABLED=True -- _notify_eod_summary를 실호출하면
    _build_discovery_section이 정확히 한 번, (storage, trade_date)로
    호출된다."""
    monkeypatch.setattr(get_settings(), "DISCOVERY_ENABLED", True)

    today = "2026-07-18"
    await _seed_minimal_eod_review(temp_storage, today)
    _stub_notify_transports(monkeypatch)

    build_calls: list = []

    async def _spy_build_discovery_section(storage, trade_date):
        build_calls.append((storage, trade_date))
        return None

    monkeypatch.setattr(
        coordinator_module, "_build_discovery_section", _spy_build_discovery_section
    )

    coord = ExecutionCoordinator(kiwoom_client=None)
    result = await coord._notify_eod_summary(today)  # REAL call -- no stub replacement

    assert result is True
    assert len(build_calls) == 1
    assert build_calls[0][1] == today
