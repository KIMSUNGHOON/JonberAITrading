"""
DS-2: BackgroundScanner discovery 수집 모드 테스트.

기존 quick/llm 스캔 모드는 여전히 죽은 시그널 타입 매칭 위에서 동작하는
레거시 경로라 손대지 않는다 — 이 파일은 신설 `start_scan(mode='discovery')`
경로만 겨냥한다. DS-1(services/discovery/factors.py)이 이미 순수 함수로
검증됐으므로 여기서는 "스캐너가 그 인터페이스를 올바르게 소비하는가"만 본다.

실 네트워크·실 Kiwoom·실 DB 절대 금지 — Kiwoom 클라이언트는 전부 목, DB는
tmp_path 픽스처로 scanner.py의 모듈 전역 DB_PATH를 monkeypatch한다(실
scanner_results.db 오염 금지, ds-global-constraints.md 준수).
"""

import asyncio
import contextlib
import json
from datetime import datetime
from typing import Optional

import aiosqlite
import pandas as pd
import pytest
from unittest.mock import AsyncMock

from services.background_scanner import scanner as scanner_module
from services.background_scanner.scanner import BackgroundScanner
from services.kiwoom.models import StockBasicInfo
from services.trading.coordinator import ExecutionCoordinator

# Note: no module-level `pytestmark` marker — pytest.ini sets asyncio_mode =
# auto, so `async def test_*` is picked up automatically (mirrors
# test_watch_list_promotion.py's convention).


# ---------------------------------------------------------------------------
# 결정적 합성 OHLCV + 목 Kiwoom 클라이언트
# ---------------------------------------------------------------------------


def _make_chart_df(n: int, start: float = 50_000.0) -> pd.DataFrame:
    """get_daily_chart_df와 동일 스키마(date/open/high/low/close/volume,
    오름차순)의 완만한 상승 합성 OHLCV. 결정적(랜덤 없음)."""
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    closes = [start * (1 + 0.001) ** i for i in range(n)]
    opens = [closes[0]] + closes[:-1]
    highs = [c * 1.004 for c in closes]
    lows = [c * 0.996 for c in closes]
    volumes = [500_000 + i * 100 for i in range(n)]
    return pd.DataFrame(
        {
            "date": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def _chart_df_with_last_move(direction: str, n: int = 65, start: float = 50_000.0) -> pd.DataFrame:
    """`_make_chart_df` 기반이되 마지막 종가만 원하는 등락 방향으로
    오버라이드한다 — breadth 판정(마지막 2개 종가 비교)의 advance/decline/
    flat 픽스처. `_make_chart_df`는 기본적으로 계속 상승(advance)하므로
    decline/flat만 실제로 값을 바꾼다."""
    df = _make_chart_df(n, start=start)
    prev_close = df["close"].iloc[-2]
    if direction == "advance":
        pass  # 기본 상승 계열 그대로 사용
    elif direction == "decline":
        df.loc[df.index[-1], "close"] = prev_close * 0.99
    elif direction == "flat":
        df.loc[df.index[-1], "close"] = prev_close
    else:
        raise ValueError(f"unknown direction: {direction}")
    return df


def _stock_info(
    stk_cd: str,
    stk_nm: str = "테스트종목",
    cur_prc: int = 70_000,
    mrkt_tot_amt: Optional[int] = 1_000,  # ka10001 단위=억원 → 1,000억 — 500억 하한 통과
    per: Optional[float] = 10.0,
    pbr: Optional[float] = 1.2,
    acml_vol: int = 500_000,
) -> StockBasicInfo:
    return StockBasicInfo(
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        cur_prc=cur_prc,
        mrkt_tot_amt=mrkt_tot_amt,
        per=per,
        pbr=pbr,
        acml_vol=acml_vol,
    )


class _FakeStockInfoUnparsablePrice:
    """StockBasicInfo가 아닌 duck-typed 페이크 — cur_prc가 숫자로 파싱 불가한
    경우(가격 파싱 실패 드롭 경로)를 재현하려면 pydantic 검증을 우회해야
    한다(진짜 StockBasicInfo는 cur_prc: int라 애초에 생성이 막힘)."""

    def __init__(self, stk_cd: str):
        self.stk_cd = stk_cd
        self.stk_nm = "파싱불가"
        self.cur_prc = "N/A"  # float() 캐스팅이 ValueError를 던짐
        self.mrkt_tot_amt = 1_000  # 억원 단위
        self.per = 10.0
        self.pbr = 1.0
        self.acml_vol = 100_000


class FakeKiwoomClient:
    """discovery 스캔이 소비하는 4개 메서드만 구현한 목 클라이언트.

    stock_infos/chart_dfs 값이 Exception 인스턴스면 그 메서드가 그 예외를
    던진다(수집 실패 시뮬레이션). 기본값(딕셔너리에 없는 종목코드)은
    RuntimeError를 던진다 — 폴백 유니버스 테스트처럼 전종목을 굳이 목킹하지
    않고도 "수집 실패=드롭"이 세션 메타데이터 기록을 막지 않음을 확인할 수
    있게 한다.
    """

    def __init__(self, stock_infos=None, chart_dfs=None, flow_responses=None, all_stocks_error=None):
        self._stock_infos = stock_infos or {}
        self._chart_dfs = chart_dfs or {}
        self._flow_responses = flow_responses or {}
        self._all_stocks_error = all_stocks_error
        self.flow_calls: list[str] = []
        self.stock_info_calls: list[str] = []
        self.chart_df_calls: list[str] = []

    async def get_stock_info(self, stk_cd: str, ttl=None):
        self.stock_info_calls.append(stk_cd)
        val = self._stock_infos.get(stk_cd)
        if isinstance(val, Exception):
            raise val
        if val is None:
            raise RuntimeError(f"no stub for {stk_cd}")
        return val

    async def get_daily_chart_df(self, stk_cd: str, base_dt=None, upd_stkpc_tp="1"):
        self.chart_df_calls.append(stk_cd)
        val = self._chart_dfs.get(stk_cd)
        if isinstance(val, Exception):
            raise val
        if val is None:
            raise RuntimeError(f"no chart stub for {stk_cd}")
        return val

    async def get_inst_foreign_flow(self, mrkt_tp: str = "001"):
        self.flow_calls.append(mrkt_tp)
        return self._flow_responses.get(mrkt_tp)

    async def get_all_stocks(self, include_kospi=True, include_kosdaq=True, exclude_warnings=True):
        if self._all_stocks_error is not None:
            raise self._all_stocks_error
        return []


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "scanner_discovery_test.db"


@pytest.fixture(autouse=True)
def patched_db(monkeypatch, db_path):
    """실 scanner_results.db를 절대 건드리지 않도록 모듈 전역 DB_PATH를
    tmp 경로로 교체(ds-global-constraints.md: 실 DB 금지)."""
    monkeypatch.setattr(scanner_module, "DB_PATH", db_path)


def _patch_client(monkeypatch, client: FakeKiwoomClient):
    """scanner.py는 각 메서드 안에서 `from app.core.kiwoom_singleton import
    get_shared_kiwoom_client_async`를 지역 import하므로, patch 대상은 그
    지역 import가 attribute lookup 시점에 참조하는 소스 모듈이어야 한다."""
    monkeypatch.setattr(
        "app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    )


async def _run_scan(scanner: BackgroundScanner, **kwargs):
    kwargs.setdefault("notify_progress", False)
    await scanner.start_scan(**kwargs)
    await scanner._task


async def _fetch_rows(db_path, session_id: Optional[str] = None):
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        if session_id:
            cursor = await db.execute(
                "SELECT * FROM scan_results WHERE scan_session_id = ?", (session_id,)
            )
        else:
            cursor = await db.execute("SELECT * FROM scan_results")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# ① discovery 스캔 → factor_json(스코어 4종+atoms) 저장 + 필터→스코어 순서
# ---------------------------------------------------------------------------


async def test_discovery_scan_saves_factor_json_with_scores_and_atoms(monkeypatch):
    """품질 필터를 통과한 종목은 4전략 스코어+_atoms+종가+시총을 factor_json에
    저장한다. 필터 탈락 종목(사유=insufficient_history)은 스코어 없이
    skip_reason만 저장돼야 한다 — DS-1 리뷰 이월: 필터가 스코어 계산보다
    먼저 실행돼야 한다(len<60 ma_alignment 가변 분모 함정 방어선)."""
    passing_df = _make_chart_df(65)
    failing_df = _make_chart_df(10)  # len<60 → insufficient_history

    client = FakeKiwoomClient(
        stock_infos={
            "005930": _stock_info("005930", "삼성전자"),
            "000660": _stock_info("000660", "SK하이닉스"),
        },
        chart_dfs={
            "005930": passing_df,
            "000660": failing_df,
        },
    )
    _patch_client(monkeypatch, client)

    scanner = BackgroundScanner()
    await _run_scan(
        scanner,
        stock_list=[("005930", "삼성전자", "코스피"), ("000660", "SK하이닉스", "코스피")],
        mode="discovery",
    )

    sessions = await scanner.get_scan_sessions(limit=1)
    session_id = sessions[0]["id"]
    rows = await _fetch_rows(scanner_module.DB_PATH, session_id)
    by_ticker = {r["stk_cd"]: r for r in rows}

    assert set(by_ticker) == {"005930", "000660"}

    passed_row = by_ticker["005930"]
    assert passed_row["action"] == "WATCH"
    fj_passed = json.loads(passed_row["factor_json"])
    assert fj_passed["quality_filter_passed"] is True
    assert set(fj_passed["scores"]) == {"momentum", "pullback", "flow", "meanrev"}
    for v in fj_passed["scores"].values():
        assert 0.0 <= v <= 1.0
    assert "atoms" in fj_passed and isinstance(fj_passed["atoms"], dict)
    # snap.price는 일봉의 마지막 종가가 아니라 ka10001(get_stock_info)의
    # 현재가(cur_prc)에서 온다 - 실시간 현재가가 일봉의 전일 종가보다 우선.
    assert fj_passed["close_price"] == pytest.approx(70_000.0)
    assert fj_passed["market_cap"] == pytest.approx(100_000_000_000.0)

    failed_row = by_ticker["000660"]
    assert failed_row["action"] == "WATCH"
    fj_failed = json.loads(failed_row["factor_json"])
    assert fj_failed["quality_filter_passed"] is False
    assert fj_failed["skip_reason"] == "insufficient_history"
    # 필터 탈락 종목은 스코어를 계산하지 않는다(스코어 없음).
    assert "scores" not in fj_failed
    assert "atoms" not in fj_failed


# ---------------------------------------------------------------------------
# ② 수집 실패 종목 = 행 미저장(드롭), 가짜 HOLD 절대 금지
# ---------------------------------------------------------------------------


async def test_discovery_scan_drops_collection_failures_no_fake_hold(monkeypatch):
    """예외로 실패한 종목(ka10001/ka10081 둘 중 하나)과 가격 파싱 불가 종목은
    scan_results에 행 자체가 남지 않아야 한다 — quick 모드의 action=HOLD/
    confidence=0.5/price=0 폴백을 discovery 모드에 재현하면 안 된다."""
    client = FakeKiwoomClient(
        stock_infos={
            "005930": Exception("kiwoom timeout (ka10001)"),  # 예외
            "000660": _FakeStockInfoUnparsablePrice("000660"),  # 가격 파싱 불가
            "035420": _stock_info("035420", "NAVER"),
        },
        chart_dfs={
            "005930": _make_chart_df(65),
            "000660": _make_chart_df(65),
            "035420": Exception("kiwoom timeout (ka10081)"),  # 예외
        },
    )
    _patch_client(monkeypatch, client)

    scanner = BackgroundScanner()
    await _run_scan(
        scanner,
        stock_list=[
            ("005930", "삼성전자", "코스피"),
            ("000660", "SK하이닉스", "코스피"),
            ("035420", "NAVER", "코스피"),
        ],
        mode="discovery",
    )

    rows = await _fetch_rows(scanner_module.DB_PATH)
    assert rows == [], "수집 실패 종목은 행 자체가 저장되면 안 된다(가짜 HOLD 금지)"

    # 메모리상 결과에도 남지 않아야 하고, 실패로 집계돼야 한다.
    assert scanner.get_results() == []
    progress = scanner.get_progress()
    assert progress.failed == 3
    assert progress.completed == 0


# ---------------------------------------------------------------------------
# ③ 유니버스 폴백 시 universe_fallback=1 + scan_mode 기록
# ---------------------------------------------------------------------------


async def test_discovery_scan_records_universe_fallback_and_scan_mode(monkeypatch):
    """get_all_stocks 실패 → _get_fallback_stock_list 사용 → scan_sessions에
    universe_fallback=1과 scan_mode='discovery'가 기록돼야 한다. 폴백
    유니버스 종목들의 개별 수집 성패는 이 테스트의 관심사가 아니다(전부
    실패해도 세션 메타데이터는 기록되어야 함)."""
    client = FakeKiwoomClient(all_stocks_error=RuntimeError("kiwoom list unavailable"))
    _patch_client(monkeypatch, client)

    scanner = BackgroundScanner()
    await _run_scan(scanner, stock_list=None, mode="discovery")

    sessions = await scanner.get_scan_sessions(limit=1)
    assert len(sessions) == 1
    session = sessions[0]
    assert session["universe_fallback"] == 1
    assert session["scan_mode"] == "discovery"
    # 폴백 유니버스(_get_fallback_stock_list)의 고정 15종목이 그대로 총량.
    assert session["total_stocks"] == 15


async def test_non_discovery_scan_records_no_universe_fallback(monkeypatch):
    """폴백이 발생하지 않은 정상 세션은 universe_fallback=0으로 기록돼야
    한다(양성 대조)."""
    client = FakeKiwoomClient(
        stock_infos={"005930": _stock_info("005930", "삼성전자")},
        chart_dfs={"005930": _make_chart_df(65)},
    )
    _patch_client(monkeypatch, client)

    scanner = BackgroundScanner()
    await _run_scan(
        scanner,
        stock_list=[("005930", "삼성전자", "코스피")],
        mode="discovery",
    )

    sessions = await scanner.get_scan_sessions(limit=1)
    assert sessions[0]["universe_fallback"] == 0
    assert sessions[0]["scan_mode"] == "discovery"


# ---------------------------------------------------------------------------
# ④ quick 모드 기존 거동 불변(동일 목으로 병행 대조)
# ---------------------------------------------------------------------------


async def test_quick_mode_unchanged_with_same_failing_mock(monkeypatch, tmp_path):
    """discovery 모드가 드롭하는 바로 그 실패 종목이라도, quick 모드는 기존
    그대로 action=HOLD/confidence=0.5/current_price=0의 폴백 ScanResult를
    저장해야 한다(byte-무변경 불변식 회귀 고정) — factor_json은 NULL.

    두 서브 스캔은 별도 tmp DB를 쓴다 — session_id가 초 단위 타임스탬프라
    같은 DB에 몰아넣으면 같은 초 안에 시작된 두 세션이 PK 충돌을 일으킬 수
    있다(스캐너 자체의 기존 한계이지 이 테스트가 검증할 대상이 아님)."""
    failing_client = FakeKiwoomClient(
        stock_infos={"005930": Exception("kiwoom timeout (ka10001)")},
        chart_dfs={"005930": _make_chart_df(65)},
    )
    _patch_client(monkeypatch, failing_client)

    # -- quick 모드 (mode 인자 생략 = 레거시 기본) --
    quick_db = tmp_path / "quick.db"
    monkeypatch.setattr(scanner_module, "DB_PATH", quick_db)
    quick_scanner = BackgroundScanner()
    await _run_scan(
        quick_scanner,
        stock_list=[("005930", "삼성전자", "코스피")],
    )

    quick_results = quick_scanner.get_results()
    assert len(quick_results) == 1
    r = quick_results[0]
    assert r.action == "HOLD"
    assert r.confidence == 0.5
    assert r.current_price == 0
    assert r.summary.startswith("분석 실패:")

    rows = await _fetch_rows(quick_db)
    assert len(rows) == 1
    assert rows[0]["action"] == "HOLD"
    assert rows[0]["factor_json"] is None

    # -- 같은 목으로 discovery 모드를 병행 실행 → 대조적으로 드롭돼야 함 --
    discovery_db = tmp_path / "discovery.db"
    monkeypatch.setattr(scanner_module, "DB_PATH", discovery_db)
    discovery_scanner = BackgroundScanner()
    await _run_scan(
        discovery_scanner,
        stock_list=[("005930", "삼성전자", "코스피")],
        mode="discovery",
    )
    assert discovery_scanner.get_results() == []


# ---------------------------------------------------------------------------
# ⑤ ka10131은 스캔당 시장별(KOSPI/KOSDAQ) 정확히 1콜 — 종목별 재호출 금지
# ---------------------------------------------------------------------------


async def test_flow_fetched_exactly_once_per_market(monkeypatch):
    client = FakeKiwoomClient(
        stock_infos={
            "005930": _stock_info("005930", "삼성전자"),
            "000660": _stock_info("000660", "SK하이닉스"),
            "035420": _stock_info("035420", "NAVER"),
        },
        chart_dfs={
            "005930": _make_chart_df(65),
            "000660": _make_chart_df(65),
            "035420": _make_chart_df(65),
        },
        flow_responses={
            "001": [{"stk_cd": "005930", "orgn_net_amt": 1e9, "frgnr_net_amt": 2e9,
                      "orgn_cont_days": 3, "frgnr_cont_days": 4}],
            "101": [{"stk_cd": "035420", "orgn_net_amt": 5e8, "frgnr_net_amt": 1e8,
                      "orgn_cont_days": 1, "frgnr_cont_days": 0}],
        },
    )
    _patch_client(monkeypatch, client)

    scanner = BackgroundScanner()
    await _run_scan(
        scanner,
        stock_list=[
            ("005930", "삼성전자", "코스피"),
            ("000660", "SK하이닉스", "코스피"),
            ("035420", "NAVER", "코스닥"),
        ],
        mode="discovery",
    )

    # 종목 수(3)와 무관하게 시장별 정확히 1콜(KOSPI+KOSDAQ)=총 2콜.
    assert client.flow_calls == ["001", "101"]

    # 랭킹에 존재하는 005930의 factor_json에 flow 성분이 반영됐는지도 확인
    # (재사용이 실제로 스코어 계산에 도달했다는 방증).
    sessions = await scanner.get_scan_sessions(limit=1)
    rows = await _fetch_rows(scanner_module.DB_PATH, sessions[0]["id"])
    by_ticker = {r["stk_cd"]: json.loads(r["factor_json"]) for r in rows}
    assert by_ticker["005930"]["atoms"]["flow_rank"] == 1
    assert by_ticker["000660"]["scores"]["flow"] == 0.0  # 랭킹 밖


# ---------------------------------------------------------------------------
# ⑥ discovery 모드에서 기존 자동 승격 비발화(auto_promote_enabled와 무관)
# ---------------------------------------------------------------------------


async def test_discovery_mode_never_auto_promotes(monkeypatch):
    """auto_promote_enabled=True + confidence 임계 0.0(그냥 통과 조건)로
    일부러 레거시 프로모션 조건을 만족시켜도, discovery 모드에서는 절대
    watch-list에 아무 것도 승격되면 안 된다(랭킹·판정은 DS-4 전용)."""
    import app.dependencies as deps

    coordinator = ExecutionCoordinator(kiwoom_client=None)
    monkeypatch.setattr(deps, "get_trading_coordinator", AsyncMock(return_value=coordinator))

    client = FakeKiwoomClient(
        stock_infos={"005930": _stock_info("005930", "삼성전자")},
        chart_dfs={"005930": _make_chart_df(65)},
    )
    _patch_client(monkeypatch, client)

    scanner = BackgroundScanner()
    await _run_scan(
        scanner,
        stock_list=[("005930", "삼성전자", "코스피")],
        mode="discovery",
        auto_promote_enabled=True,
        promote_confidence_threshold=0.0,
        promote_max_count=10,
    )

    # discovery 결과는 action='WATCH' 고정이라, 가드가 없다면 confidence 0.0
    # >= 임계 0.0 조건에 걸려 레거시 프로모션이 발화했을 것이다.
    result = scanner.get_results()[0]
    assert result.action == "WATCH"
    assert coordinator.get_watch_list() == [], "discovery 모드는 승격을 절대 발화시키면 안 된다"


# ---------------------------------------------------------------------------
# ⑦ discovery 세션 buy/sell/hold_count = advance/decline/flat breadth
#    (DS-2 리뷰픽스: action='WATCH' 고정이라 세션 카운트가 전부 watch_count로
#    몰려 regime.py의 breadth가 항상 0.0/neutral로 오염되던 결함 봉합)
# ---------------------------------------------------------------------------


async def test_discovery_session_counts_reflect_advance_decline_flat_breadth(monkeypatch):
    """세션 buy/sell/hold_count는 discovery 종목의 등락 방향(advance/decline/
    flat, chart_df 마지막 2개 종가 비교)을 반영해야 한다 — 종전처럼
    action='WATCH' 고정 매핑(watch_count에만 집계)이면 buy/sell/hold가 전부
    0이 돼 regime.py의 breadth가 오염된다. 행 수준 action='WATCH'는
    유지되어야 한다(행 수준 의미 무변경 — 세션 집계만 유의미화)."""
    advancing_1 = _make_chart_df(65)
    advancing_2 = _make_chart_df(65, start=30_000.0)
    declining = _chart_df_with_last_move("decline")
    flat = _chart_df_with_last_move("flat")

    client = FakeKiwoomClient(
        stock_infos={
            "005930": _stock_info("005930", "AdvA"),
            "000660": _stock_info("000660", "AdvB"),
            "035420": _stock_info("035420", "Decl"),
            "005380": _stock_info("005380", "Flat"),
        },
        chart_dfs={
            "005930": advancing_1,
            "000660": advancing_2,
            "035420": declining,
            "005380": flat,
        },
    )
    _patch_client(monkeypatch, client)

    scanner = BackgroundScanner()
    await _run_scan(
        scanner,
        stock_list=[
            ("005930", "AdvA", "코스피"),
            ("000660", "AdvB", "코스피"),
            ("035420", "Decl", "코스피"),
            ("005380", "Flat", "코스피"),
        ],
        mode="discovery",
    )

    sessions = await scanner.get_scan_sessions(limit=1)
    session = sessions[0]
    assert session["buy_count"] == 2
    assert session["sell_count"] == 1
    assert session["hold_count"] == 1

    # 행 수준 action은 여전히 WATCH 고정(회귀 고정 — 세션 집계만 유의미화).
    rows = await _fetch_rows(scanner_module.DB_PATH, session["id"])
    assert len(rows) == 4
    assert all(r["action"] == "WATCH" for r in rows)


async def test_discovery_session_counts_include_quality_filter_rejects(monkeypatch):
    """품질 필터에서 탈락(예: 시총 미달)해도 차트 수집에 성공했다면 breadth
    카운트에는 포함돼야 한다 — breadth는 시장 전체 내부 지표이지 필터 통과
    종목만의 지표가 아니다."""
    client = FakeKiwoomClient(
        stock_infos={
            # 시총 10억 — DEFAULT_MIN_MARKET_CAP(500억) 미달 -> 품질 필터 탈락
            "005930": _stock_info("005930", "SmallCap", mrkt_tot_amt=100),
        },
        chart_dfs={"005930": _make_chart_df(65)},  # 상승 계열
    )
    _patch_client(monkeypatch, client)

    scanner = BackgroundScanner()
    await _run_scan(
        scanner,
        stock_list=[("005930", "SmallCap", "코스피")],
        mode="discovery",
    )

    # 사전조건: 실제로 품질 필터에서 탈락했는지 확인.
    rows = await _fetch_rows(scanner_module.DB_PATH)
    assert len(rows) == 1
    fj = json.loads(rows[0]["factor_json"])
    assert fj["quality_filter_passed"] is False

    sessions = await scanner.get_scan_sessions(limit=1)
    # 상승(advance) 종목이므로 필터 탈락과 무관하게 buy_count에 집계된다.
    assert sessions[0]["buy_count"] == 1
    assert sessions[0]["sell_count"] == 0
    assert sessions[0]["hold_count"] == 0


async def test_discovery_session_counts_exclude_collection_failures(monkeypatch):
    """수집 자체가 실패(예외/가격 파싱 불가)한 종목은 breadth 카운트에도
    포함되면 안 된다 — 성공 2종목(상승1·하락1) + 실패 1종목 혼합 시
    buy=1, sell=1, hold=0이어야 하고 실패 종목의 흔적이 카운트에 없어야
    한다."""
    declining = _chart_df_with_last_move("decline")
    client = FakeKiwoomClient(
        stock_infos={
            "005930": _stock_info("005930", "Adv"),
            "035420": _stock_info("035420", "Decl"),
            "000660": Exception("kiwoom timeout (ka10001)"),  # 수집 실패
        },
        chart_dfs={
            "005930": _make_chart_df(65),
            "035420": declining,
            "000660": _make_chart_df(65),
        },
    )
    _patch_client(monkeypatch, client)

    scanner = BackgroundScanner()
    await _run_scan(
        scanner,
        stock_list=[
            ("005930", "Adv", "코스피"),
            ("035420", "Decl", "코스피"),
            ("000660", "Fail", "코스피"),
        ],
        mode="discovery",
    )

    sessions = await scanner.get_scan_sessions(limit=1)
    session = sessions[0]
    assert session["buy_count"] == 1
    assert session["sell_count"] == 1
    assert session["hold_count"] == 0
    assert session["failed"] == 1

    rows = await _fetch_rows(scanner_module.DB_PATH, session["id"])
    assert len(rows) == 2  # 실패 종목 행 없음(가짜 HOLD 금지, 기존 불변식)


async def test_regime_snapshot_consumes_discovery_breadth_end_to_end(monkeypatch):
    """통합-lite: discovery 세션이 tmp scanner DB에 저장된 뒤
    regime.compute_regime_snapshot이 그 buy/sell/hold_count를 읽어
    breadth_ratio를 유의미하게 산출해야 한다 — 수정 전에는 discovery
    세션의 action이 전부 'WATCH'라 buy/sell/hold=0 고정 -> breadth_ratio는
    항상 0.0/regime_label은 항상 'neutral'로 강제됐다."""
    from services.trading.regime import compute_regime_snapshot

    advancing_1 = _make_chart_df(65)
    advancing_2 = _make_chart_df(65, start=30_000.0)
    declining = _chart_df_with_last_move("decline")
    flat = _chart_df_with_last_move("flat")

    client = FakeKiwoomClient(
        stock_infos={
            "005930": _stock_info("005930", "AdvA"),
            "000660": _stock_info("000660", "AdvB"),
            "035420": _stock_info("035420", "Decl"),
            "005380": _stock_info("005380", "Flat"),
        },
        chart_dfs={
            "005930": advancing_1,
            "000660": advancing_2,
            "035420": declining,
            "005380": flat,
        },
    )
    _patch_client(monkeypatch, client)

    scanner = BackgroundScanner()
    await _run_scan(
        scanner,
        stock_list=[
            ("005930", "AdvA", "코스피"),
            ("000660", "AdvB", "코스피"),
            ("035420", "Decl", "코스피"),
            ("005380", "Flat", "코스피"),
        ],
        mode="discovery",
    )

    today = datetime.now().strftime("%Y-%m-%d")
    record = compute_regime_snapshot(str(scanner_module.DB_PATH), today)

    assert record is not None
    assert record["breadth_buy"] == 2
    assert record["breadth_sell"] == 1
    assert record["breadth_hold"] == 1
    # (buy - sell) / (buy + sell + hold) = (2 - 1) / 4 = 0.25
    assert record["breadth_ratio"] == pytest.approx(0.25)

    # 실코드 임계값(EOD_REGIME_BREADTH_THRESHOLD, 기본 0.15)을 직접 읽어
    # 레이블 경계를 하드코딩하지 않고 단언한다.
    from app.config import get_settings

    threshold = get_settings().EOD_REGIME_BREADTH_THRESHOLD
    assert record["breadth_ratio"] > threshold, (
        "테스트 픽스처(0.25)가 임계값보다 커야 non-neutral 레이블을 검증할 수 있다"
    )
    assert record["regime_label"] == "risk_on"


# ---------------------------------------------------------------------------
# SC-1: stop_scan orphan-fix — status='partial' 종결 + 부분 breadth 반영
#
# 실측 사고: discovery EOD 스캔이 90분 타임아웃으로 stop_scan 호출 시
# scan_sessions row가 status='running'인 채 영구 고아로 남아, regime.py·
# ranker.py의 `WHERE status = 'completed'` 게이트가 0건을 반환 → 84%
# 스캔(3700/4276)이 breadth·랭킹에 통째로 미반영됐다.
# ---------------------------------------------------------------------------


async def test_stop_scan_marks_running_session_partial_with_saved_count(monkeypatch):
    """타임아웃/수동 stop처럼 스캔 도중 stop_scan()이 호출되면, 세션 row는
    status='partial'로 명시 종결되어야 하고(수정 전 RED=영구 'running' 고아),
    completed는 그 시점까지 실제로 scan_results에 저장된 행 수와 일치해야
    한다. 배치 2(10종목)는 release Event로 블록해 배치 1(50종목=discovery
    QUICK_BATCH_SIZE)만 저장된 상태에서 stop_scan을 호출하도록 결정적으로
    구성한다."""
    batch1 = [(f"{100000 + i:06d}", f"S1-{i}", "코스피") for i in range(50)]
    batch2 = [(f"{200000 + i:06d}", f"S2-{i}", "코스피") for i in range(10)]
    stock_list = batch1 + batch2

    stock_infos = {code: _stock_info(code, name) for code, name, _ in stock_list}
    chart_dfs = {code: _make_chart_df(65) for code, _, _ in stock_list}

    blocked_codes = {code for code, _, _ in batch2}
    release = asyncio.Event()

    class _SlowClient(FakeKiwoomClient):
        async def get_daily_chart_df(self, stk_cd: str, base_dt=None, upd_stkpc_tp="1"):
            if stk_cd in blocked_codes:
                await release.wait()
            return await super().get_daily_chart_df(
                stk_cd, base_dt=base_dt, upd_stkpc_tp=upd_stkpc_tp
            )

    client = _SlowClient(stock_infos=stock_infos, chart_dfs=chart_dfs)
    _patch_client(monkeypatch, client)

    scanner = BackgroundScanner()

    # 배치 1 저장 완료를 결정적으로 대기하기 위한 훅 — 배치 2(블록됨)가
    # 저장되기 전에 정확히 stop_scan()을 호출할 수 있게 한다.
    batch1_saved = asyncio.Event()
    original_save = BackgroundScanner._save_discovery_results_batch

    async def _tracking_save(self, pairs, session_id):
        await original_save(self, pairs, session_id)
        batch1_saved.set()

    monkeypatch.setattr(
        BackgroundScanner, "_save_discovery_results_batch", _tracking_save
    )

    await scanner.start_scan(
        stock_list=stock_list, mode="discovery", notify_progress=False
    )

    await asyncio.wait_for(batch1_saved.wait(), timeout=5)

    # 사전조건: 배치 1만 저장된 상태(배치 2는 아직 release 대기 중).
    rows_before_stop = await _fetch_rows(scanner_module.DB_PATH)
    assert len(rows_before_stop) == 50

    await scanner.stop_scan()

    # stop_scan이 취소한 태스크가 실제로 풀릴 때까지 대기(CancelledError는
    # 정상 종료 신호 — 여기서 흡수).
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(scanner._task, timeout=5)

    release.set()  # 방어적 정리(배치 2가 취소로 이미 풀렸어야 함)

    rows = await _fetch_rows(scanner_module.DB_PATH)
    assert len(rows) == 50, "배치 2는 취소돼 저장되면 안 된다"

    sessions = await scanner.get_scan_sessions(limit=1)
    session = sessions[0]
    assert session["status"] == "partial", (
        "수정 전에는 stop_scan이 세션을 'running'으로 영구 고아 상태로 "
        "남겼다(RED)"
    )
    assert session["completed"] == 50, "completed는 실제 저장된 행 수와 일치해야 한다"


async def test_stop_scan_noop_when_no_scan_running():
    """스캔이 실행 중이 아닐 때 stop_scan()은 아무 것도 하지 않아야 한다
    (세션도 없고 예외도 없어야 함)."""
    scanner = BackgroundScanner()
    await scanner.stop_scan()  # 예외 없이 조용히 반환

    sessions = await scanner.get_scan_sessions(limit=10)
    assert sessions == []


async def test_normal_completion_session_status_still_completed(monkeypatch):
    """정상 완주 세션은 여전히 status='completed'여야 한다(SC-1의
    `_save_session_complete` 무변경 불변식 회귀 고정)."""
    client = FakeKiwoomClient(
        stock_infos={"005930": _stock_info("005930", "삼성전자")},
        chart_dfs={"005930": _make_chart_df(65)},
    )
    _patch_client(monkeypatch, client)

    scanner = BackgroundScanner()
    await _run_scan(
        scanner,
        stock_list=[("005930", "삼성전자", "코스피")],
        mode="discovery",
    )

    sessions = await scanner.get_scan_sessions(limit=1)
    assert sessions[0]["status"] == "completed"
    assert sessions[0]["completed"] == 1
