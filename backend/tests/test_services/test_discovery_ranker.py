"""
Discovery ranker tests (DS-4): regime-weighted composite ranking, LLM
structured review, and the conservative promotion gate chain.

Real DB schema via tmp-path StorageService (mirrors test_discovery_ledger.py)
plus a hand-seeded tmp scanner_results.db (scan_sessions/scan_results —
mirrors test_scanner_discovery_mode.py's factor_json shape, but seeded
directly via SQL rather than running a full BackgroundScanner scan, since
this module only ever *reads* those two tables). Coordinator is a REAL
`ExecutionCoordinator(kiwoom_client=None)` (no network — mirrors
test_watch_list_promotion.py/test_watch_list_persistence.py's convention;
"mock" here means no Kiwoom client, not a hand-rolled fake coordinator). LLM
is always a fake provider — real network/LLM calls are forbidden
(ds-global-constraints.md).
"""

import json
import uuid

import aiosqlite
import pytest

from services.agent_chat.coordinator import ChatCoordinator
from services.discovery import ranker
from services.discovery.factors import STRATEGIES
from services.discovery.ranker import (
    DEFAULT_REGIME_WEIGHTS,
    Candidate,
    _build_llm_messages,
    llm_review_top,
    promote_candidates,
    rank_candidates,
)
from services.storage_service import StorageService
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import ManagedPosition, RiskParameters
from services.trading.strategy import ExitConditions, TradingStrategy

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# tmp scanner_results.db seeding (scan_sessions + scan_results only — the two
# tables ranker.py reads via aiosqlite direct, per regime.py's cross-db
# precedent)
# ---------------------------------------------------------------------------

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


async def _seed_scanner_db(
    db_path,
    trade_date: str,
    results: list[dict],
    *,
    session_id: str = "sess-1",
    universe_fallback: bool = False,
    status: str = "completed",
    scan_mode: str = "discovery",
) -> str:
    """Seed a tmp scanner db with one scan_sessions row + its scan_results
    rows. Each item in `results`: {"stk_cd", "stk_nm", "factor_json": dict}.
    """
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(_SCAN_SESSIONS_SCHEMA)
        await db.execute(_SCAN_RESULTS_SCHEMA)
        await db.execute(
            """
            INSERT INTO scan_sessions
            (id, started_at, completed_at, total_stocks, completed, failed,
             buy_count, sell_count, hold_count, watch_count, avoid_count,
             status, universe_fallback, scan_mode)
            VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, ?, 0, ?, ?, ?)
            """,
            (
                session_id,
                f"{trade_date} 15:40:00",
                f"{trade_date} 16:10:00",
                len(results),
                len(results),
                len(results),
                status,
                1 if universe_fallback else 0,
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


def _passing_factor(
    momentum: float = 0.0,
    pullback: float = 0.0,
    flow: float = 0.0,
    meanrev: float = 0.0,
    close_price: float = 50_000.0,
    market_cap: float = 100_000_000_000.0,
    flow_present: bool | None = None,
) -> dict:
    """`flow_present=None`(default) omits the key entirely -- reproduces a
    pre-DQ-2 scan's factor_json shape, so `rank_candidates` must fall back to
    the raw-flow-zero proxy. Pass `True`/`False` explicitly to pin the DQ-2
    flag itself (round-trip / explicit-priority-over-proxy tests)."""
    factor = {
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
    if flow_present is not None:
        factor["flow_present"] = flow_present
    return factor


def _failing_factor(reason: str = "insufficient_history") -> dict:
    return {"quality_filter_passed": False, "skip_reason": reason}


async def _seed_regime_snapshot(storage: StorageService, trade_date: str, label: str) -> None:
    await storage.save_regime_snapshot(
        {"id": str(uuid.uuid4()), "trade_date": trade_date, "market_sentiment_label": label}
    )


def _candidate(
    ticker: str,
    *,
    trade_date: str = "2026-07-20",
    regime_label: str = "neutral",
    threshold: float = 0.55,
    daily_cap: int = 5,
    composite: float = 0.7,
    rank: int = 1,
    close_price: float = 50_000.0,
    universe_fallback: bool = False,
    quality_filter_passed: bool = True,
    llm_suitable: bool | None = True,
) -> Candidate:
    """Hand-built Candidate for gate-level unit tests that don't need the
    full rank_candidates() pipeline."""
    c = Candidate(
        ticker=ticker,
        name=f"종목{ticker}",
        trade_date=trade_date,
        regime_label=regime_label,
        threshold=threshold,
        daily_cap=daily_cap,
        weights={"momentum": 0.25, "pullback": 0.25, "flow": 0.25, "meanrev": 0.25},
        universe_fallback=universe_fallback,
        quality_filter_passed=quality_filter_passed,
        raw_scores=(
            {"momentum": 0.6, "pullback": 0.6, "flow": 0.6, "meanrev": 0.6}
            if quality_filter_passed else None
        ),
        composite=composite if quality_filter_passed else None,
        rank=rank if quality_filter_passed else None,
        close_price=close_price,
    )
    if llm_suitable is not None:
        c.llm_verdict = {
            "suitable": llm_suitable, "confidence": composite, "rationale": "r", "risks": "x",
        }
    return c


class _FakeLLMProvider:
    """Ticker is looked up by substring match against the HumanMessage
    content (`_build_llm_messages` always embeds `(ticker)`), so callers
    don't need to know call order."""

    def __init__(self, responses: dict[str, str] | None = None, raise_for: frozenset[str] = frozenset()):
        self.responses = responses or {}
        self.raise_for = raise_for
        self.calls: list[str | None] = []

    async def generate(self, messages, task=None, **kwargs):
        content = messages[-1].content
        candidates = set(self.responses) | set(self.raise_for)
        ticker = next((t for t in candidates if f"({t})" in content), None)
        self.calls.append(ticker)
        if ticker in self.raise_for:
            raise RuntimeError(f"llm boom for {ticker}")
        return self.responses.get(
            ticker, '{"suitable": false, "confidence": 0.1, "rationale": "", "risks": ""}'
        )


@pytest.fixture
def storage(tmp_path):
    return StorageService(db_path=str(tmp_path / "storage.db"))


@pytest.fixture
def coordinator():
    return ExecutionCoordinator(kiwoom_client=None)


# ---------------------------------------------------------------------------
# flow_present -- LLM 프롬프트 flow-missing 명시 (#1, Task 3)
# ---------------------------------------------------------------------------


def test_candidate_has_flow_present_field_default_false():
    c = _candidate("005930")
    assert c.flow_present is False


def test_build_llm_messages_flow_present_shows_number():
    c = _candidate("005930")
    c.flow_present = True
    c.raw_scores = {"momentum": 0.6, "pullback": 0.6, "flow": 0.5, "meanrev": 0.6}
    msgs = _build_llm_messages(c)
    prompt = msgs[-1].content
    assert "flow=0.500" in prompt
    assert "미가용" not in prompt


def test_build_llm_messages_flow_absent_shows_unavailable_not_zero():
    c = _candidate("005930")
    c.flow_present = False
    c.raw_scores = {"momentum": 0.6, "pullback": 0.6, "flow": 0.0, "meanrev": 0.6}
    msgs = _build_llm_messages(c)
    prompt = msgs[-1].content
    assert "미가용" in prompt
    assert "부정신호 아님" in prompt
    assert "flow=0.000" not in prompt


# ---------------------------------------------------------------------------
# ① 레짐별 composite 가중 정확 (수기 계산 대조)
# ---------------------------------------------------------------------------


async def test_rank_candidates_composite_matches_manual_calculation(tmp_path, storage):
    trade_date = "2026-07-20"
    scanner_db = tmp_path / "scanner.db"
    await _seed_regime_snapshot(storage, trade_date, "bullish")

    factor_a = _passing_factor(momentum=0.8, pullback=0.4, flow=0.2, meanrev=0.1, close_price=70_000.0)
    # Deliberately NOT a near-tie with factor_a under bullish weights (momentum
    # .40/pullback .25/flow .25/meanrev .10) -- factor_a's composite is 0.48;
    # this one computes to 0.60, so rank ordering is unambiguous.
    factor_b = _passing_factor(momentum=0.0, pullback=1.0, flow=1.0, meanrev=1.0, close_price=30_000.0)
    await _seed_scanner_db(
        scanner_db, trade_date,
        [
            {"stk_cd": "005930", "stk_nm": "A", "factor_json": factor_a},
            {"stk_cd": "000660", "stk_nm": "B", "factor_json": factor_b},
        ],
    )

    candidates = await rank_candidates(storage, str(scanner_db), trade_date)
    by_ticker = {c.ticker: c for c in candidates}

    w = DEFAULT_REGIME_WEIGHTS["bullish"]
    expected_a = 0.8 * w["momentum"] + 0.4 * w["pullback"] + 0.2 * w["flow"] + 0.1 * w["meanrev"]
    expected_b = 0.0 * w["momentum"] + 1.0 * w["pullback"] + 1.0 * w["flow"] + 1.0 * w["meanrev"]

    assert by_ticker["005930"].composite == pytest.approx(expected_a)
    assert by_ticker["000660"].composite == pytest.approx(expected_b)
    assert by_ticker["005930"].regime_label == "bullish"
    assert by_ticker["005930"].threshold == pytest.approx(w["threshold"])
    assert by_ticker["005930"].daily_cap == w["daily_cap"]

    # B's composite is higher -> rank 1.
    assert by_ticker["000660"].rank == 1
    assert by_ticker["005930"].rank == 2


async def test_rank_candidates_excludes_quality_filter_failures_from_ranking(tmp_path, storage):
    trade_date = "2026-07-20"
    scanner_db = tmp_path / "scanner.db"
    await _seed_regime_snapshot(storage, trade_date, "neutral")

    await _seed_scanner_db(
        scanner_db, trade_date,
        [
            {"stk_cd": "005930", "stk_nm": "Good", "factor_json": _passing_factor(momentum=0.5)},
            {"stk_cd": "000660", "stk_nm": "Bad", "factor_json": _failing_factor("market_cap_low")},
        ],
    )

    candidates = await rank_candidates(storage, str(scanner_db), trade_date)
    by_ticker = {c.ticker: c for c in candidates}

    assert by_ticker["005930"].rank == 1
    assert by_ticker["005930"].composite is not None

    assert by_ticker["000660"].composite is None
    assert by_ticker["000660"].rank is None
    assert by_ticker["000660"].skip_reason == "market_cap_low"
    assert by_ticker["000660"].quality_filter_passed is False


async def test_rank_candidates_returns_empty_when_no_session_for_date(tmp_path, storage):
    scanner_db = tmp_path / "scanner.db"
    # No session seeded at all -> DB file doesn't even exist with the tables.
    async with aiosqlite.connect(str(scanner_db)) as db:
        await db.execute(_SCAN_SESSIONS_SCHEMA)
        await db.execute(_SCAN_RESULTS_SCHEMA)
        await db.commit()

    candidates = await rank_candidates(storage, str(scanner_db), "2026-07-20")
    assert candidates == []


# ---------------------------------------------------------------------------
# DQ-2: flow 결측 재정규화 -- _effective_weights 순수 함수 단위 테스트
# ---------------------------------------------------------------------------


class TestEffectiveWeights:
    # _effective_weights 자체는 순수 동기 함수지만, 모듈 전역
    # pytestmark(asyncio)는 클래스 속성 재선언으로 무효화되지 않는다(module
    # -> class 마크는 누적이지 override가 아님) -- 그래서 이 테스트들도 다른
    # 테스트와 동일하게 async def로 선언해 pytest-asyncio 경고 없이 자연스럽게
    # 수렴시킨다(본문은 동기 호출만 있고 await은 없음).
    async def test_flow_missing_redistributes_bearish_weights_manual(self):
        """수기 대조: bearish {momentum .10 pullback .20 flow .35 meanrev .35}
        에서 flow 결측 -> {momentum .154 pullback .308 flow 0 meanrev .538},
        합은 여전히 1.0으로 보존."""
        base = {k: DEFAULT_REGIME_WEIGHTS["bearish"][k] for k in STRATEGIES}
        eff = ranker._effective_weights(base, flow_present=False)

        assert eff["momentum"] == pytest.approx(0.153846, abs=1e-5)
        assert eff["pullback"] == pytest.approx(0.307692, abs=1e-5)
        assert eff["meanrev"] == pytest.approx(0.538462, abs=1e-5)
        assert eff["flow"] == 0.0
        assert sum(eff.values()) == pytest.approx(1.0)

    async def test_flow_present_returns_base_unchanged(self):
        """flow_present=True는 재분배 없이 base 가중을 그대로(방어적 복사로)
        반환해야 한다 -- DQ-D 원칙: 재정규화는 결측 종목만."""
        base = {"momentum": 0.10, "pullback": 0.20, "flow": 0.35, "meanrev": 0.35}
        eff = ranker._effective_weights(base, flow_present=True)

        assert eff == base
        assert eff is not base

    async def test_non_strategy_keys_pass_through_untouched(self):
        """base_weights에 threshold/daily_cap 같은 비-팩터 키가 섞여 있어도
        (레짐 설정 dict 원형) STRATEGIES 4키만 재분배 대상이고 나머지는
        그대로 통과해야 한다."""
        base = {
            "momentum": 0.10, "pullback": 0.20, "flow": 0.35, "meanrev": 0.35,
            "threshold": 0.65, "daily_cap": 2,
        }
        eff = ranker._effective_weights(base, flow_present=False)

        assert eff["threshold"] == 0.65
        assert eff["daily_cap"] == 2
        assert sum(eff[k] for k in STRATEGIES) == pytest.approx(1.0)

    async def test_degenerate_all_zero_weights_never_raises(self):
        """나머지 3키 합이 0인 손상된 가중 설정도 예외 없이 flow만 0으로
        두고 반환해야 한다(fail-closed, 랭킹 전체를 죽이면 안 됨)."""
        base = {"momentum": 0.0, "pullback": 0.0, "flow": 1.0, "meanrev": 0.0}
        eff = ranker._effective_weights(base, flow_present=False)
        assert eff["flow"] == 0.0
        assert eff["momentum"] == 0.0
        assert eff["pullback"] == 0.0
        assert eff["meanrev"] == 0.0


# ---------------------------------------------------------------------------
# DQ-2: rank_candidates 배선 -- 재정규화된 composite + 원장 _weights
# ---------------------------------------------------------------------------


async def test_rank_candidates_renormalizes_composite_when_flow_missing(tmp_path, storage):
    """크레오에스지 실측 검산(spec §0): momentum=0.32/pullback=0.54/
    meanrev=0.67, flow 결측(flow_present=False, bearish 레짐) -> 재정규화
    composite=0.576. base(비재정규화) 가중 계산은 RED 값 0.373(구조상
    3745 반올림)과 일치해야 한다 -- 재정규화가 실제로 더 높은 composite를
    낸다는 것을 함께 확인."""
    trade_date = "2026-07-20"
    scanner_db = tmp_path / "scanner.db"
    await _seed_regime_snapshot(storage, trade_date, "bearish")

    factor = _passing_factor(
        momentum=0.32, pullback=0.54, flow=0.0, meanrev=0.67, flow_present=False,
    )
    await _seed_scanner_db(
        scanner_db, trade_date,
        [{"stk_cd": "066970", "stk_nm": "크레오에스지", "factor_json": factor}],
    )

    candidates = await rank_candidates(storage, str(scanner_db), trade_date)
    c = candidates[0]

    w = DEFAULT_REGIME_WEIGHTS["bearish"]
    base_composite = 0.32 * w["momentum"] + 0.54 * w["pullback"] + 0.67 * w["meanrev"]
    assert base_composite == pytest.approx(0.3745, abs=1e-4)  # RED 대조값(구현 전 수치)

    assert c.composite == pytest.approx(0.576, abs=1e-3)
    assert c.composite > base_composite
    assert c.weights["flow"] == 0.0
    assert c.weights["meanrev"] == pytest.approx(0.538462, abs=1e-5)
    assert c.weights["momentum"] == pytest.approx(0.153846, abs=1e-5)
    assert c.weights["pullback"] == pytest.approx(0.307692, abs=1e-5)


async def test_rank_candidates_flow_present_flag_roundtrips_from_factor_json(tmp_path, storage):
    """factor_json에 명시적으로 저장된 flow_present=True 플래그가 raw flow
    프록시보다 우선해야 한다 -- flow raw 스코어가 우연히 0.0이어도(예: 랭킹
    최하위권 존재) 플래그가 True면 재정규화가 적용되지 않아야 한다(플래그
    우선순위 왕복 확인)."""
    trade_date = "2026-07-20"
    scanner_db = tmp_path / "scanner.db"
    await _seed_regime_snapshot(storage, trade_date, "bearish")

    factor = _passing_factor(
        momentum=0.32, pullback=0.54, flow=0.0, meanrev=0.67, flow_present=True,
    )
    await _seed_scanner_db(
        scanner_db, trade_date,
        [{"stk_cd": "005930", "stk_nm": "삼성전자", "factor_json": factor}],
    )

    candidates = await rank_candidates(storage, str(scanner_db), trade_date)
    c = candidates[0]

    w = DEFAULT_REGIME_WEIGHTS["bearish"]
    expected = 0.32 * w["momentum"] + 0.54 * w["pullback"] + 0.0 * w["flow"] + 0.67 * w["meanrev"]
    assert c.composite == pytest.approx(expected)
    for k in STRATEGIES:
        assert c.weights[k] == pytest.approx(w[k])


async def test_rank_candidates_falls_back_to_raw_flow_zero_proxy_when_flag_absent(tmp_path, storage):
    """구 스캔(factor_json에 flow_present 키 자체가 없음) 하위호환: raw
    flow==0.0을 결측 프록시로 삼아 재정규화가 여전히 적용돼야 한다(웹젠
    실측 케이스와 동일한 배선 경로, spec §0)."""
    trade_date = "2026-07-20"
    scanner_db = tmp_path / "scanner.db"
    await _seed_regime_snapshot(storage, trade_date, "bearish")

    factor = _passing_factor(momentum=0.32, pullback=0.54, flow=0.0, meanrev=0.67)
    assert "flow_present" not in factor  # 사전조건: 구 스캔 형태(플래그 없음)

    await _seed_scanner_db(
        scanner_db, trade_date,
        [{"stk_cd": "063080", "stk_nm": "웹젠", "factor_json": factor}],
    )

    candidates = await rank_candidates(storage, str(scanner_db), trade_date)
    c = candidates[0]
    assert c.composite == pytest.approx(0.576, abs=1e-3)
    assert c.weights["flow"] == 0.0


async def test_rank_candidates_composite_unchanged_when_flow_present(tmp_path, storage):
    """flow가 실제로 존재하는 종목(raw flow!=0.0 프록시로 flow_present=True
    판정)은 재정규화가 적용되지 않고 base 가중 그대로 composite가 계산돼야
    한다 -- DQ-D 원칙 회귀 핀: 결측 종목만 재정규화, 존재 종목은 무접촉."""
    trade_date = "2026-07-20"
    scanner_db = tmp_path / "scanner.db"
    await _seed_regime_snapshot(storage, trade_date, "bearish")

    factor = _passing_factor(momentum=0.32, pullback=0.54, flow=0.40, meanrev=0.67)
    await _seed_scanner_db(
        scanner_db, trade_date,
        [{"stk_cd": "005930", "stk_nm": "삼성전자", "factor_json": factor}],
    )

    candidates = await rank_candidates(storage, str(scanner_db), trade_date)
    c = candidates[0]

    w = DEFAULT_REGIME_WEIGHTS["bearish"]
    expected = 0.32 * w["momentum"] + 0.54 * w["pullback"] + 0.40 * w["flow"] + 0.67 * w["meanrev"]
    assert c.composite == pytest.approx(expected)
    for k in STRATEGIES:
        assert c.weights[k] == pytest.approx(w[k])


# ---------------------------------------------------------------------------
# SC-1: status='partial'(스캔 도중 stop_scan으로 종결) 세션도 랭킹 소비
# 대상이어야 한다 -- 실측 고아 버그(scanner.py stop_scan이 세션을
# 'running'으로 영구 고아화)의 근본 수정: regime.py와 동일한 게이트 확장.
# ---------------------------------------------------------------------------


async def test_rank_candidates_consumes_partial_session(tmp_path, storage):
    """status='partial' 세션도 'completed'와 동일하게 랭킹 대상이어야 한다
    (수정 전 RED=[] -- _load_discovery_session이 'completed'만 찾았음)."""
    trade_date = "2026-07-20"
    scanner_db = tmp_path / "scanner.db"
    await _seed_regime_snapshot(storage, trade_date, "neutral")

    await _seed_scanner_db(
        scanner_db, trade_date,
        [{"stk_cd": "005930", "stk_nm": "Good", "factor_json": _passing_factor(momentum=0.5)}],
        status="partial",
    )

    candidates = await rank_candidates(storage, str(scanner_db), trade_date)
    by_ticker = {c.ticker: c for c in candidates}

    assert "005930" in by_ticker
    assert by_ticker["005930"].composite is not None
    assert by_ticker["005930"].rank == 1


async def test_rank_candidates_still_excludes_running_session(tmp_path, storage):
    """status='running'(아직 진행 중, 아직 종결되지 않은 세션)은 여전히
    랭킹 대상이 아니어야 한다(게이트 확장이 과잉 확장되지 않았음을 확인)."""
    trade_date = "2026-07-20"
    scanner_db = tmp_path / "scanner.db"
    await _seed_regime_snapshot(storage, trade_date, "neutral")

    await _seed_scanner_db(
        scanner_db, trade_date,
        [{"stk_cd": "005930", "stk_nm": "Good", "factor_json": _passing_factor(momentum=0.5)}],
        status="running",
    )

    candidates = await rank_candidates(storage, str(scanner_db), trade_date)
    assert candidates == []


async def test_rank_candidates_prefers_latest_over_status(tmp_path, storage):
    """같은 날 completed(이른 세션)와 partial(늦은 세션)이 공존하면 최신
    started_at(partial)이 우선해야 한다(스펙: '최신 started_at 우선
    유지'). `_seed_scanner_db`는 고정 시각을 쓰므로, 두 세션을 서로 다른
    session_id로 각각 시딩하고 두 번째 호출의 started_at이 더 늦도록
    trade_date는 같게 두되 두 번째 세션만 이후에 삽입해 직접 UPDATE로
    시각을 벌린다."""
    trade_date = "2026-07-20"
    scanner_db = tmp_path / "scanner.db"
    await _seed_regime_snapshot(storage, trade_date, "neutral")

    await _seed_scanner_db(
        scanner_db, trade_date,
        [{"stk_cd": "000660", "stk_nm": "Early", "factor_json": _passing_factor(momentum=0.1)}],
        session_id="sess-early",
        status="completed",
    )
    async with aiosqlite.connect(str(scanner_db)) as db:
        await db.execute(
            "INSERT INTO scan_sessions "
            "(id, started_at, completed_at, total_stocks, completed, failed, "
            " buy_count, sell_count, hold_count, watch_count, avoid_count, "
            " status, universe_fallback, scan_mode) "
            "VALUES ('sess-late', ?, ?, 1, 1, 0, 0, 0, 0, 1, 0, 'partial', 0, 'discovery')",
            (f"{trade_date} 20:00:00", f"{trade_date} 20:05:00"),
        )
        await db.execute(
            "INSERT INTO scan_results "
            "(stk_cd, stk_nm, action, signal, confidence, summary, key_factors, "
            " current_price, market_type, scanned_at, scan_session_id, factor_json) "
            "VALUES ('005930', 'Late', 'WATCH', 'discovery', 0.0, '', '', 0, '', ?, "
            " 'sess-late', ?)",
            (
                f"{trade_date} 20:01:00",
                json.dumps(_passing_factor(momentum=0.9), ensure_ascii=False),
            ),
        )
        await db.commit()

    candidates = await rank_candidates(storage, str(scanner_db), trade_date)
    tickers = {c.ticker for c in candidates}

    assert tickers == {"005930"}, "가장 늦게 시작된 partial 세션(sess-late)만 소비돼야 한다"


# ---------------------------------------------------------------------------
# ② 가중치 app_settings 왕복 + 미존재 시 시드
# ---------------------------------------------------------------------------


async def test_regime_weights_seed_on_first_read(storage):
    weights = await ranker._load_regime_weights(storage)
    assert weights == DEFAULT_REGIME_WEIGHTS

    stored_raw = await storage.get_app_setting(ranker.REGIME_WEIGHTS_SETTING_KEY)
    assert stored_raw is not None
    assert json.loads(stored_raw) == DEFAULT_REGIME_WEIGHTS


async def test_regime_weights_roundtrip_uses_stored_value_not_reseed(storage):
    await ranker._load_regime_weights(storage)  # seeds

    custom = json.loads(await storage.get_app_setting(ranker.REGIME_WEIGHTS_SETTING_KEY))
    custom["bullish"]["threshold"] = 0.99
    await storage.set_app_setting(ranker.REGIME_WEIGHTS_SETTING_KEY, json.dumps(custom))

    weights2 = await ranker._load_regime_weights(storage)
    assert weights2["bullish"]["threshold"] == 0.99
    # Untouched regimes still round-trip intact.
    assert weights2["bearish"] == DEFAULT_REGIME_WEIGHTS["bearish"]


async def test_regime_weights_corrupt_value_falls_back_to_default(storage):
    await storage.set_app_setting(ranker.REGIME_WEIGHTS_SETTING_KEY, "not valid json{{{")
    weights = await ranker._load_regime_weights(storage)
    assert weights == DEFAULT_REGIME_WEIGHTS


# ---------------------------------------------------------------------------
# ②b DQ-3: 문턱 재산출 핀 + 재시드 마이그레이션
# ---------------------------------------------------------------------------


async def test_default_regime_weights_bearish_threshold_recalibrated():
    """DQ-3 실측 핀(2026-07-20): DQ-1 ETN 제외 + DQ-2 재정규화 적용 후
    순수 실주식 composite 분포 재측정 결과 bearish threshold만 0.65 -> 0.52로
    갱신(상위 크레오에스지 0.574 · 웹젠 0.536, >=0.52 3개, daily_cap 2로 상위
    2 승격). neutral/bullish threshold와 일 캡(bearish 2 · neutral/bullish 5)은
    전부 불변."""
    assert DEFAULT_REGIME_WEIGHTS["bearish"]["threshold"] == pytest.approx(0.52)
    assert DEFAULT_REGIME_WEIGHTS["bearish"]["daily_cap"] == 2
    assert DEFAULT_REGIME_WEIGHTS["neutral"]["threshold"] == pytest.approx(0.55)
    assert DEFAULT_REGIME_WEIGHTS["neutral"]["daily_cap"] == 5
    assert DEFAULT_REGIME_WEIGHTS["bullish"]["threshold"] == pytest.approx(0.55)
    assert DEFAULT_REGIME_WEIGHTS["bullish"]["daily_cap"] == 5


async def test_migrate_reseed_overwrites_when_stored_matches_old_default(storage):
    """① 저장값이 정확히 구 DEFAULT(bearish threshold 0.65)와 일치하면
    새 DEFAULT(bearish threshold 0.52)로 덮어써야 한다."""
    await storage.set_app_setting(
        ranker.REGIME_WEIGHTS_SETTING_KEY,
        json.dumps(ranker._OLD_DEFAULT_REGIME_WEIGHTS, ensure_ascii=False),
    )

    migrated = await ranker.migrate_regime_weights_reseed(storage)

    assert migrated is True
    stored_raw = await storage.get_app_setting(ranker.REGIME_WEIGHTS_SETTING_KEY)
    assert json.loads(stored_raw) == DEFAULT_REGIME_WEIGHTS


async def test_migrate_reseed_preserves_user_adjusted_value(storage):
    """② 저장값이 구 DEFAULT와 조금이라도 다르면(사용자/EOD 조정) 절대
    덮어쓰지 않고 그대로 보존해야 한다."""
    custom = json.loads(json.dumps(ranker._OLD_DEFAULT_REGIME_WEIGHTS))
    custom["bullish"]["threshold"] = 0.42
    await storage.set_app_setting(
        ranker.REGIME_WEIGHTS_SETTING_KEY, json.dumps(custom, ensure_ascii=False)
    )

    migrated = await ranker.migrate_regime_weights_reseed(storage)

    assert migrated is False
    stored_raw = await storage.get_app_setting(ranker.REGIME_WEIGHTS_SETTING_KEY)
    assert json.loads(stored_raw) == custom


async def test_migrate_reseed_noop_when_no_stored_value(storage):
    """③ 저장값 자체가 없으면(신규 배포) 아무것도 쓰지 않는다 -- 기존
    _load_regime_weights 시드 경로가 다음 읽기에서 새 DEFAULT로 정상 시딩한다."""
    migrated = await ranker.migrate_regime_weights_reseed(storage)

    assert migrated is False
    assert await storage.get_app_setting(ranker.REGIME_WEIGHTS_SETTING_KEY) is None

    weights = await ranker._load_regime_weights(storage)
    assert weights == DEFAULT_REGIME_WEIGHTS


async def test_migrate_reseed_never_raises_on_storage_error(monkeypatch, storage):
    """④ storage 예외(손상된 접근 등)는 절대 전파되지 않고 False로
    수렴해야 한다 -- 마이그레이션 실패가 기동을 막으면 안 된다."""
    async def boom(*args, **kwargs):
        raise RuntimeError("storage boom")

    monkeypatch.setattr(storage, "get_app_setting", boom)

    migrated = await ranker.migrate_regime_weights_reseed(storage)

    assert migrated is False


async def test_migrate_reseed_never_raises_on_corrupt_stored_json(storage):
    """손상된(비-JSON) 저장값도 예외 없이 False로 수렴해야 한다(구 DEFAULT와
    일치 여부를 판정할 수 없으므로 보존 취급)."""
    await storage.set_app_setting(ranker.REGIME_WEIGHTS_SETTING_KEY, "not valid json{{{")

    migrated = await ranker.migrate_regime_weights_reseed(storage)

    assert migrated is False
    stored_raw = await storage.get_app_setting(ranker.REGIME_WEIGHTS_SETTING_KEY)
    assert stored_raw == "not valid json{{{"


# ---------------------------------------------------------------------------
# #3 regime_snapshot 개장 전 전일 폴백 (Task 4)
# ---------------------------------------------------------------------------


async def test_regime_snapshot_exact_match_preferred(storage):
    from services.discovery.ranker import _get_regime_snapshot_for_date

    await _seed_regime_snapshot(storage, "2026-07-20", "bearish")
    await _seed_regime_snapshot(storage, "2026-07-21", "neutral")

    snap = await _get_regime_snapshot_for_date(storage, "2026-07-21")

    assert snap is not None and snap["trade_date"] == "2026-07-21"


async def test_regime_snapshot_falls_back_to_prev_day(storage):
    from services.discovery.ranker import _get_regime_snapshot_for_date

    await _seed_regime_snapshot(storage, "2026-07-20", "bearish")  # D-1

    snap = await _get_regime_snapshot_for_date(storage, "2026-07-21")

    assert snap is not None and snap["trade_date"] == "2026-07-20"
    assert snap.get("market_sentiment_label") == "bearish"


async def test_regime_snapshot_fallback_rejects_too_old(storage):
    from services.discovery.ranker import _get_regime_snapshot_for_date

    await _seed_regime_snapshot(storage, "2026-07-10", "bearish")  # 11일 전 > 7일

    snap = await _get_regime_snapshot_for_date(storage, "2026-07-21")

    assert snap is None


# ---------------------------------------------------------------------------
# ③ LLM JSON 성공/파싱 실패 = 보류 (+top_n 밖 후보는 절대 호출 안 됨)
# ---------------------------------------------------------------------------


async def test_llm_review_top_parses_success_and_marks_parse_failure(monkeypatch):
    good = _candidate("005930", composite=0.6, rank=1, llm_suitable=None)
    bad = _candidate("000660", composite=0.5, rank=2, llm_suitable=None)

    fake = _FakeLLMProvider(
        responses={
            "005930": '{"suitable": true, "confidence": 0.8, "rationale": "돌파", "risks": "변동성"}',
            "000660": "이건 JSON이 아닙니다 — 그냥 자유서술입니다.",
        }
    )
    monkeypatch.setattr(ranker, "get_llm_provider", lambda: fake)

    await llm_review_top([good, bad], top_n=25)

    assert good.llm_verdict == {
        "suitable": True, "confidence": 0.8, "rationale": "돌파", "risks": "변동성",
    }
    assert good.skip_reason is None

    assert bad.llm_verdict is None
    assert bad.skip_reason == "llm_parse_failed"


async def test_llm_review_top_tolerates_markdown_fence(monkeypatch):
    c = _candidate("005930", composite=0.6, rank=1, llm_suitable=None)
    fenced = '```json\n{"suitable": true, "confidence": 0.7, "rationale": "ok", "risks": "-"}\n```'
    fake = _FakeLLMProvider(responses={"005930": fenced})
    monkeypatch.setattr(ranker, "get_llm_provider", lambda: fake)

    await llm_review_top([c], top_n=25)

    assert c.llm_verdict is not None
    assert c.llm_verdict["suitable"] is True


async def test_llm_review_top_exception_never_raises(monkeypatch):
    c = _candidate("005930", composite=0.6, rank=1, llm_suitable=None)

    class _BoomProvider:
        async def generate(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(ranker, "get_llm_provider", lambda: _BoomProvider())

    await llm_review_top([c], top_n=25)  # must not raise

    assert c.llm_verdict is None
    assert c.skip_reason == "llm_parse_failed"


async def test_llm_review_top_never_calls_beyond_top_n(monkeypatch):
    reviewed = _candidate("005930", composite=0.9, rank=1, llm_suitable=None)
    unreviewed = _candidate("000660", composite=0.8, rank=2, llm_suitable=None)

    fake = _FakeLLMProvider(
        responses={"005930": '{"suitable": true, "confidence": 0.9, "rationale": "r", "risks": "x"}'}
    )
    monkeypatch.setattr(ranker, "get_llm_provider", lambda: fake)

    await llm_review_top([reviewed, unreviewed], top_n=1)

    assert reviewed.llm_verdict is not None
    assert unreviewed.llm_verdict is None
    assert unreviewed.skip_reason is None  # never touched, not marked parse-failed
    assert fake.calls == ["005930"]


async def test_llm_review_top_skips_quality_filter_excluded_candidates(monkeypatch):
    excluded = _candidate("005930", quality_filter_passed=False, llm_suitable=None)
    fake = _FakeLLMProvider()
    monkeypatch.setattr(ranker, "get_llm_provider", lambda: fake)

    await llm_review_top([excluded], top_n=25)

    assert fake.calls == []
    assert excluded.llm_verdict is None


# ---------------------------------------------------------------------------
# ④ 게이트 각각: 문턱 · 일 캡(bearish 2) · 쿨다운 · 기보유 제외 · 폴백 전면 스킵
# ---------------------------------------------------------------------------


async def test_promote_below_regime_threshold_is_skipped(storage, coordinator):
    c = _candidate("005930", composite=0.40, threshold=0.55)

    summary = await promote_candidates(coordinator, storage, [c])

    assert summary.promoted == []
    assert c.skip_reason == "below_threshold"
    assert coordinator.get_watch_list() == []

    ledger = await storage.get_discovery_candidates(trade_date=c.trade_date)
    assert len(ledger) == 1
    assert ledger[0]["skip_reason"] == "below_threshold"
    assert ledger[0]["promoted"] == 0


async def test_promote_llm_not_suitable_is_skipped(storage, coordinator):
    c = _candidate("005930", composite=0.9, threshold=0.55, llm_suitable=False)

    summary = await promote_candidates(coordinator, storage, [c])

    assert summary.promoted == []
    assert c.skip_reason == "llm_not_suitable"


async def test_promote_never_reviewed_candidate_is_not_reviewed_not_llm_not_suitable(
    storage, coordinator
):
    """DS-4 리뷰 이월(DS-5): top_n 밖이라 llm_review_top이 손대지 않은 후보
    (llm_verdict=None, skip_reason=None -- test_llm_review_top_never_calls_
    beyond_top_n의 계약)는 'llm_not_suitable'(LLM이 부적합 판정)이 아니라
    'not_reviewed'(애초에 검토 자체가 없었음)로 구분 기록돼야 한다."""
    c = _candidate("005930", composite=0.9, threshold=0.55, llm_suitable=None)
    assert c.llm_verdict is None
    assert c.skip_reason is None

    summary = await promote_candidates(coordinator, storage, [c])

    assert summary.promoted == []
    assert c.skip_reason == "not_reviewed"
    assert summary.skipped["005930"] == "not_reviewed"

    ledger = await storage.get_discovery_candidates(trade_date=c.trade_date)
    assert ledger[0]["skip_reason"] == "not_reviewed"


async def test_promote_daily_cap_bearish_limits_to_two(storage, coordinator):
    candidates = [
        _candidate(
            f"00000{i}", composite=0.90 - i * 0.01, rank=i + 1,
            threshold=0.65, daily_cap=2, regime_label="bearish",
        )
        for i in range(3)
    ]

    summary = await promote_candidates(coordinator, storage, candidates)

    assert len(summary.promoted) == 2
    assert candidates[0].skip_reason is None
    assert candidates[1].skip_reason is None
    assert candidates[2].skip_reason == "daily_cap"


async def test_promote_daily_cap_counts_prior_same_date_promotions(storage, coordinator):
    """Important 봉합: 같은 trade_date에 이미 승격된 후보가 원장에 있으면 그
    수만큼 일일 캡이 미리 차감된다 — 수동 POST /trading/discovery/run(개장 전)과
    스케줄러 마감 엣지(15:30)가 같은 날 각각 파이프라인을 돌려도 일일 캡이 2배로
    늘지 않도록. per-call 카운터라면 신규 티커 2건이 또 승격됐겠지만, 원장 시드
    (2) 덕에 bearish 캡(2)에 이미 도달해 전부 skip된다."""
    trade_date = "2026-07-20"
    # 오전 수동 실행이 이미 승격해 원장에 남긴 2건(같은 trade_date, promoted=1).
    await storage.save_discovery_candidates(
        [
            {
                "trade_date": trade_date, "ticker": t, "name": t,
                "composite_score": 0.9,
                "strategy_scores_json": {"momentum": 0.9, "pullback": 0.1, "flow": 0.1, "meanrev": 0.0},
                "regime_label": "bearish", "rank": i + 1,
                "llm_verdict_json": {"suitable": True}, "promoted": 1,
                "skip_reason": None, "close_price": 50000.0,
            }
            for i, t in enumerate(["100001", "100002"])
        ]
    )

    # 두 번째 실행: 완전히 다른 신규 티커들. 캡이 per-call로 리셋되면 2건 승격됐겠지만
    # 원장 시드(2)로 daily_cap(2)에 이미 도달 → 전부 daily_cap skip.
    fresh = [
        _candidate(
            f"20000{i}", trade_date=trade_date, composite=0.90 - i * 0.01,
            rank=i + 1, threshold=0.65, daily_cap=2, regime_label="bearish",
        )
        for i in range(2)
    ]
    summary = await promote_candidates(coordinator, storage, fresh)

    assert summary.promoted == []
    assert all(c.skip_reason == "daily_cap" for c in fresh)


async def test_promote_cooldown_blocks_repromotion_within_7_days(storage, coordinator):
    trade_date = "2026-07-20"
    past_date = "2026-07-17"  # 3 calendar days before trade_date -> within cooldown
    await storage.save_discovery_candidates(
        [
            {
                "trade_date": past_date, "ticker": "005930", "name": "삼성전자",
                "composite_score": 0.8,
                "strategy_scores_json": {"momentum": 0.8, "pullback": 0.1, "flow": 0.1, "meanrev": 0.0},
                "regime_label": "neutral", "rank": 1,
                "llm_verdict_json": {"suitable": True}, "promoted": 1,
                "skip_reason": None, "close_price": 70000.0,
            }
        ]
    )

    c = _candidate("005930", trade_date=trade_date, composite=0.9, threshold=0.55)
    summary = await promote_candidates(coordinator, storage, [c])

    assert summary.promoted == []
    assert c.skip_reason == "cooldown"


async def test_promote_allows_repromotion_after_cooldown_elapsed(storage, coordinator):
    trade_date = "2026-07-20"
    past_date = "2026-07-10"  # 10 calendar days before -> cooldown elapsed
    await storage.save_discovery_candidates(
        [
            {
                "trade_date": past_date, "ticker": "005930", "name": "삼성전자",
                "composite_score": 0.8,
                "strategy_scores_json": {"momentum": 0.8, "pullback": 0.1, "flow": 0.1, "meanrev": 0.0},
                "regime_label": "neutral", "rank": 1,
                "llm_verdict_json": {"suitable": True}, "promoted": 1,
                "skip_reason": None, "close_price": 70000.0,
            }
        ]
    )

    c = _candidate("005930", trade_date=trade_date, composite=0.9, threshold=0.55)
    summary = await promote_candidates(coordinator, storage, [c])

    assert summary.promoted == ["005930"]
    assert c.skip_reason is None


async def test_promote_skips_already_held_position(storage, coordinator):
    coordinator.state.positions.append(
        ManagedPosition(ticker="005930", stock_name="삼성전자", quantity=10, avg_price=70_000.0)
    )
    c = _candidate("005930", composite=0.9, threshold=0.55)

    summary = await promote_candidates(coordinator, storage, [c])

    assert summary.promoted == []
    assert c.skip_reason == "already_held_or_watched"


async def test_promote_skips_already_watched_ticker(storage, coordinator):
    coordinator.add_to_watch_list(
        session_id="manual-s", ticker="005930", stock_name="삼성전자",
        signal="hold", confidence=0.5, current_price=70_000, source="manual",
    )
    c = _candidate("005930", composite=0.9, threshold=0.55)

    summary = await promote_candidates(coordinator, storage, [c])

    assert summary.promoted == []
    assert c.skip_reason == "already_held_or_watched"


async def test_promote_universe_fallback_skips_all_candidates(storage, coordinator):
    c1 = _candidate("005930", composite=0.9, threshold=0.1, universe_fallback=True)
    c2 = _candidate("000660", composite=0.9, threshold=0.1, universe_fallback=True)

    summary = await promote_candidates(coordinator, storage, [c1, c2])

    assert summary.promoted == []
    assert c1.skip_reason == "universe_fallback"
    assert c2.skip_reason == "universe_fallback"
    assert coordinator.get_watch_list() == []

    ledger = await storage.get_discovery_candidates(trade_date=c1.trade_date)
    assert {r["skip_reason"] for r in ledger} == {"universe_fallback"}


async def test_promote_no_candidates_is_a_noop(storage, coordinator):
    summary = await promote_candidates(coordinator, storage, [])
    assert summary.promoted == []
    assert summary.skipped == {}
    assert summary.total_candidates == 0


# ---------------------------------------------------------------------------
# ⑧ E-1 (P2-D1): 승격 시 target/stop/tp 전달 -- discovery→토론 연결 완결
# ---------------------------------------------------------------------------


async def test_promotion_fills_target_stop_take_and_confidence_from_active_strategy(
    storage, coordinator,
):
    """수기 계산 대조: close=10,000 · 활성 전략 stop_loss_pct=4.5% ->
    stop_loss=9,550. take_profit_pct=12% -> take_profit=11,200.
    confidence는 여전히 cand.composite(문턱/게이트와 무관하게 유지)."""
    coordinator.set_strategy(
        TradingStrategy(
            exit_conditions=ExitConditions(stop_loss_pct=0.045, take_profit_pct=0.12)
        )
    )
    c = _candidate("005930", composite=0.62, threshold=0.1, close_price=10_000.0)

    summary = await promote_candidates(coordinator, storage, [c])
    assert summary.promoted == ["005930"]

    watched = coordinator.get_watch_list()[0]
    assert watched.target_entry_price == pytest.approx(10_000.0)
    assert watched.stop_loss == pytest.approx(9_550.0)
    assert watched.take_profit == pytest.approx(11_200.0)
    assert watched.confidence == pytest.approx(0.62)


async def test_promoted_candidate_triggers_detect_opportunity_end_to_end(storage, coordinator):
    """종단 핀: promote_candidates가 채운 target_entry_price가 실제로
    _detect_opportunity(services/agent_chat/coordinator.py)의 가격근접
    분기를 발화시켜야 한다. confidence=0.62는 고정 문턱 0.75(무접촉) 미달이라
    confidence 단독으로는 결코 True가 될 수 없다 -- 가격근접 분기가 유일한
    발화 경로.

    RED(배선 전) 재현: target_entry_price=None이면 이 분기는 항상 스킵되고
    confidence도 문턱 미달이라 동일 current_price에서도 False였다."""
    c = _candidate("005930", composite=0.62, threshold=0.1, close_price=10_000.0)
    summary = await promote_candidates(coordinator, storage, [c])
    assert summary.promoted == ["005930"]

    watched = coordinator.get_watch_list()[0]
    assert watched.target_entry_price == pytest.approx(10_000.0)

    stock = {
        "ticker": watched.ticker,
        "current_price": 10_150.0,  # target(10,000)의 1.5% 이내 -- 문턱 0.03 이내
        "target_entry_price": watched.target_entry_price,
        "confidence": watched.confidence,
    }

    chat_coordinator = ChatCoordinator()
    assert await chat_coordinator._detect_opportunity(stock) is True

    # RED 회귀 핀: 배선 전 동작(target_entry_price=None)은 동일 가격/신뢰도에서도
    # 결코 True를 반환하지 않았다.
    stale_stock = dict(stock, target_entry_price=None)
    assert await chat_coordinator._detect_opportunity(stale_stock) is False


async def test_promotion_falls_back_to_risk_params_when_no_active_strategy(storage):
    """전략 조회 실패(활성 전략 없음, get_strategy()->None) 시
    coordinator.risk_params의 default_stop_loss_pct/default_take_profit_pct로
    폴백한다. RiskParameters는 퍼센트 포인트(예: 4.0 == 4%)로 저장되므로
    100으로 나눈 값이 stop/tp 계산에 쓰여야 한다."""
    coordinator = ExecutionCoordinator(
        kiwoom_client=None,
        risk_params=RiskParameters(default_stop_loss_pct=4.0, default_take_profit_pct=20.0),
    )
    assert coordinator.get_strategy() is None  # 활성 전략 없음 = 조회 실패와 동치

    c = _candidate("005930", composite=0.62, threshold=0.1, close_price=10_000.0)
    summary = await promote_candidates(coordinator, storage, [c])
    assert summary.promoted == ["005930"]

    watched = coordinator.get_watch_list()[0]
    assert watched.target_entry_price == pytest.approx(10_000.0)
    assert watched.stop_loss == pytest.approx(9_600.0)  # 10,000 * (1 - 0.04)
    assert watched.take_profit == pytest.approx(12_000.0)  # 10,000 * (1 + 0.20)


async def test_promotion_leaves_existing_manual_watch_entries_untouched(storage, coordinator):
    """기존 manual 워치 항목은 discovery 승격 배선 확장과 무관하게 그대로
    유지돼야 한다 (target/stop/tp가 새로 채워지거나 덮어써지지 않음)."""
    manual = coordinator.add_to_watch_list(
        session_id="manual-s", ticker="000660", stock_name="수동종목",
        signal="hold", confidence=0.5, current_price=50_000.0, source="manual",
    )
    assert manual.target_entry_price is None
    assert manual.stop_loss is None
    assert manual.take_profit is None

    c = _candidate("005930", composite=0.62, threshold=0.1, close_price=10_000.0)
    summary = await promote_candidates(coordinator, storage, [c])
    assert summary.promoted == ["005930"]

    by_ticker = {w.ticker: w for w in coordinator.get_watch_list()}
    manual_after = by_ticker["000660"]
    assert manual_after.target_entry_price is None
    assert manual_after.stop_loss is None
    assert manual_after.take_profit is None
    assert manual_after.source == "manual"

    # discovery 항목은 여전히 정상 배선됨.
    discovered = by_ticker["005930"]
    assert discovered.target_entry_price == pytest.approx(10_000.0)


# ---------------------------------------------------------------------------
# ⑤ 워치 총량 캡 30: 31번째 승격 시 열위 discovery 제거 + manual 보호
# ---------------------------------------------------------------------------


async def test_watch_cap_evicts_worst_scoring_discovery_entry_when_full(storage, coordinator):
    for i in range(29):
        coordinator.add_to_watch_list(
            session_id="s", ticker=f"D{i:03d}", stock_name=f"D{i}",
            signal="discovery", confidence=0.50 + i * 0.001, current_price=10_000,
            source="discovery",
        )
    coordinator.add_to_watch_list(
        session_id="s", ticker="MANUAL1", stock_name="Manual",
        signal="hold", confidence=0.99, current_price=10_000, source="manual",
    )
    assert len(coordinator.get_watch_list()) == 30

    new_candidate = _candidate("NEW001", composite=0.95, threshold=0.1)
    summary = await promote_candidates(coordinator, storage, [new_candidate])

    assert summary.promoted == ["NEW001"]
    watch = coordinator.get_watch_list()
    assert len(watch) == 30
    tickers = {w.ticker for w in watch}
    assert "D000" not in tickers, "가장 낮은 confidence(0.50)의 discovery 항목이 제거돼야 한다"
    assert "MANUAL1" in tickers, "manual 항목은 절대 자동 제거되면 안 된다"
    assert "NEW001" in tickers
    assert "D001" in tickers  # 두 번째로 낮은 항목은 유지


async def test_watch_cap_skips_promotion_when_all_entries_manual(storage, coordinator):
    for i in range(30):
        coordinator.add_to_watch_list(
            session_id="s", ticker=f"M{i:03d}", stock_name=f"M{i}",
            signal="hold", confidence=0.5, current_price=10_000, source="manual",
        )
    assert len(coordinator.get_watch_list()) == 30

    new_candidate = _candidate("NEW002", composite=0.95, threshold=0.1)
    summary = await promote_candidates(coordinator, storage, [new_candidate])

    assert summary.promoted == []
    assert new_candidate.skip_reason == "watch_cap"
    assert len(coordinator.get_watch_list()) == 30


# ---------------------------------------------------------------------------
# ⑥ 원장에 전 후보 기록 (승격/스킵/품질필터 탈락 전부, skip_reason 포함)
# ---------------------------------------------------------------------------


async def test_full_pipeline_ledger_records_every_candidate(tmp_path, storage, coordinator, monkeypatch):
    trade_date = "2026-07-20"
    scanner_db = tmp_path / "scanner.db"
    await _seed_regime_snapshot(storage, trade_date, "neutral")

    good = _passing_factor(momentum=0.9, pullback=0.9, flow=0.9, meanrev=0.9, close_price=70_000.0)
    bad_quality = _failing_factor("market_cap_low")
    low_score = _passing_factor(momentum=0.05, pullback=0.05, flow=0.05, meanrev=0.05, close_price=5_000.0)

    await _seed_scanner_db(
        scanner_db, trade_date,
        [
            {"stk_cd": "005930", "stk_nm": "Good", "factor_json": good},
            {"stk_cd": "000660", "stk_nm": "Bad", "factor_json": bad_quality},
            {"stk_cd": "035420", "stk_nm": "Low", "factor_json": low_score},
        ],
    )

    candidates = await rank_candidates(storage, str(scanner_db), trade_date)
    assert len(candidates) == 3

    fake = _FakeLLMProvider(
        responses={"005930": '{"suitable": true, "confidence": 0.9, "rationale": "ok", "risks": "-"}'}
    )
    monkeypatch.setattr(ranker, "get_llm_provider", lambda: fake)
    await llm_review_top(candidates, top_n=25)

    summary = await promote_candidates(coordinator, storage, candidates)
    assert summary.promoted == ["005930"]

    ledger = await storage.get_discovery_candidates(trade_date=trade_date)
    assert len(ledger) == 3
    by_ticker = {r["ticker"]: r for r in ledger}

    assert by_ticker["005930"]["promoted"] == 1
    assert by_ticker["005930"]["skip_reason"] is None
    assert by_ticker["005930"]["rank"] == 1
    scores_json = json.loads(by_ticker["005930"]["strategy_scores_json"])
    assert scores_json["momentum"] == pytest.approx(0.9)
    assert "_weights" in scores_json
    assert scores_json["_weights"]["flow"] == pytest.approx(DEFAULT_REGIME_WEIGHTS["neutral"]["flow"])

    assert by_ticker["000660"]["promoted"] == 0
    assert by_ticker["000660"]["skip_reason"] == "market_cap_low"
    assert by_ticker["000660"]["rank"] is None

    assert by_ticker["035420"]["promoted"] == 0
    assert by_ticker["035420"]["skip_reason"] == "below_threshold"


# ---------------------------------------------------------------------------
# ⑦ WatchedStock.source 하위호환 복원 (pre-DS-4 blob에는 source 키 자체가 없음)
# ---------------------------------------------------------------------------


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    """Isolated SQLite storage wired into the get_storage_service() singleton
    (mirrors test_watch_list_persistence.py's fixture — _persist_state /
    _restore_state go through the module-level singleton, not the injected
    `storage` param)."""
    import services.storage_service as ss

    st = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await st.initialize()
    monkeypatch.setattr(ss, "_storage_service", st)
    yield st
    monkeypatch.setattr(ss, "_storage_service", None)


async def test_watched_stock_source_backward_compat_restore(temp_storage):
    coord1 = ExecutionCoordinator(kiwoom_client=None)
    coord1.add_to_watch_list(
        session_id="s", ticker="005930", stock_name="A", signal="discovery",
        confidence=0.7, current_price=70_000, source="discovery",
    )
    await coord1._persist_state()

    # Splice in a pre-DS-4 persisted watch entry that has NO "source" key at
    # all (the literal shape written before this field existed).
    blob = json.loads(await temp_storage.get_app_setting(coord1._STATE_KEY))
    blob["watch_list"].append(
        {
            "id": "watch_legacy1", "session_id": "s", "ticker": "000660",
            "stock_name": "Legacy", "action": "WATCH", "signal": "hold",
            "confidence": 0.5, "current_price": 50_000,
            "analysis_summary": "", "key_factors": [], "status": "active",
            "added_at": "2026-07-01T00:00:00", "risk_score": 5,
        }
    )
    await temp_storage.set_app_setting(coord1._STATE_KEY, json.dumps(blob))

    coord2 = ExecutionCoordinator(kiwoom_client=None)
    await coord2._restore_state()

    restored = {w.ticker: w for w in coord2.get_watch_list()}
    assert restored["005930"].source == "discovery"
    assert restored["000660"].source == "manual"
