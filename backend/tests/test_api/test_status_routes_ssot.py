"""P1-3: KR·coin GET /analysis/status/{id} 가 SM 단독으로 읽는다.

SESSION_SSOT_READS=True(default)일 때 두 status 라우트는 legacy dict
(kr_stock_sessions/coin_sessions)를 전혀 스캔하지 않고 SessionManager
(SQLite 영속)만 읽는다. coin은 이전까지 `get_coin_session` 헬퍼로 legacy
dict 단독 조회였기 때문에(재시작 후 legacy dict가 비면 404), 이 태스크가
coin 라우트에 처음으로 재시작 내성을 부여한다. 응답 스키마 구성 코드와
404 시맨틱은 무변경.

DB 격리: SessionManager는 모듈 싱글턴(services.session_manager.
_session_manager) + 기본 DB_PATH="data/sessions.db"(라이브 파일)를 쓴다.
TestClient(app) 진입 시 app.main.lifespan이 get_session_manager()를 호출해
싱글턴을 초기화하므로, TestClient 생성 *이전*에 DB_PATH와 싱글턴을 테스트
전용 파일로 monkeypatch해야 실 DB 오염을 막을 수 있다
(tests/test_api/test_approval_pending_ssot.py의 `_isolated_sm_db` 픽스처와
동일 패턴).

킬스위치 회귀: SESSION_SSOT_READS=False는 P2가 legacy 쓰기를 제거하기
전까지 유일한 롤백 수단이므로, False 분기가 각 라우트의 기존(byte-preserved)
거동으로 완전히 복귀하는지도 고정한다. get_settings()는 @lru_cache이므로
env로 값을 바꿔치기할 수 없다 -- 대상 모듈이 import한 이름 `get_settings`를
직접 monkeypatch한다.
"""
import os
import types

import pytest
from fastapi.testclient import TestClient

import app.api.routes.coin.analysis as coin_analysis_module
import app.api.routes.kr_stocks.analysis as kr_analysis_module
import services.session_manager as sm_module

TEST_DB_PATH = "data/test_status_routes_ssot.db"


@pytest.fixture()
def _isolated_sm_db(monkeypatch):
    """SessionManager 싱글턴을 던지는 SQLite 파일로 격리한다.

    client 픽스처가 TestClient(app)을 열기 *전에* 먼저 셋업되어야 lifespan의
    get_session_manager() 초기화가 이 DB_PATH를 보고, 실 data/sessions.db는
    절대 건드리지 않는다.
    """
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    monkeypatch.setattr(sm_module, "DB_PATH", TEST_DB_PATH)
    monkeypatch.setattr(sm_module, "_session_manager", None)
    yield
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest.fixture()
def client(_isolated_sm_db):
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.mark.asyncio
async def test_coin_status_route_survives_restart(client):
    """legacy dict에 없는(=재시작 후) SM 세션이 coin status 라우트에서 200."""
    from services.session_manager import MarketType, SessionStatus, get_session_manager
    sm = await get_session_manager()
    s = await sm.create_session(
        "ssot-p13-coin", MarketType.COIN, "KRW-BTC", "비트코인",
        market="KRW-BTC", korean_name="비트코인",
        state={"reasoning_log": [], "current_stage": "done"},
    )
    s.status = SessionStatus.COMPLETED
    resp = client.get("/api/coin/analysis/status/ssot-p13-coin")
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "ssot-p13-coin"


@pytest.mark.asyncio
async def test_kr_status_route_sm_only(client):
    """legacy dict에 없는 SM 세션이 KR status 라우트에서 200 (기존에도 폴백은
    있었지만, True 분기에서는 legacy dict를 아예 스캔하지 않는다)."""
    from services.session_manager import MarketType, get_session_manager
    sm = await get_session_manager()
    await sm.create_session(
        "ssot-p13-kr", MarketType.KIWOOM, "005930", "삼성전자",
        stk_cd="005930", stk_nm="삼성전자",
        state={"reasoning_log": []},
    )
    resp = client.get("/api/kr_stocks/analysis/status/ssot-p13-kr")
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "ssot-p13-kr"


@pytest.mark.asyncio
async def test_kr_status_route_404_when_absent(client):
    """SM에도 legacy dict에도 없는 세션은 여전히 404 (시맨틱 보존)."""
    resp = client.get("/api/kr_stocks/analysis/status/ssot-p13-kr-missing")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_coin_status_route_404_when_absent(client):
    """SM에도 legacy dict에도 없는 세션은 여전히 404 (시맨틱 보존)."""
    resp = client.get("/api/coin/analysis/status/ssot-p13-coin-missing")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_kr_status_kill_switch_reads_legacy_when_false(client, monkeypatch):
    """SESSION_SSOT_READS=False: legacy-first(+SM 폴백) 거동으로 완전 복귀.

    SM-only 세션(legacy dict에 전혀 없음)도 기존 코드가 이미 SM 폴백을
    갖고 있었으므로 여전히 200이어야 한다 -- byte-preserved 회귀 확인.
    """
    from app.api.routes.kr_stocks import get_kr_stock_sessions
    from services.session_manager import MarketType, get_session_manager

    monkeypatch.setattr(
        kr_analysis_module, "get_settings",
        lambda: types.SimpleNamespace(SESSION_SSOT_READS=False),
    )

    kr_sessions = get_kr_stock_sessions()
    kr_sessions["ssot-p13-ks-legacy"] = {
        "session_id": "ssot-p13-ks-legacy",
        "stk_cd": "000660",
        "stk_nm": "SK하이닉스",
        "status": "running",
        "state": {"reasoning_log": []},
    }

    sm = await get_session_manager()
    await sm.create_session(
        "ssot-p13-ks-sm-only", MarketType.KIWOOM, "005930", "삼성전자",
        stk_cd="005930", stk_nm="삼성전자",
        state={"reasoning_log": []},
    )
    try:
        legacy_resp = client.get("/api/kr_stocks/analysis/status/ssot-p13-ks-legacy")
        assert legacy_resp.status_code == 200
        assert legacy_resp.json()["session_id"] == "ssot-p13-ks-legacy"

        # existing code already SM-falls-back when legacy misses, so this
        # stays 200 under False too (byte-preserved, not a new behavior).
        sm_only_resp = client.get("/api/kr_stocks/analysis/status/ssot-p13-ks-sm-only")
        assert sm_only_resp.status_code == 200
    finally:
        kr_sessions.pop("ssot-p13-ks-legacy", None)
        await sm.remove_session("ssot-p13-ks-sm-only")


@pytest.mark.asyncio
async def test_coin_status_kill_switch_reads_legacy_only_when_false(client, monkeypatch):
    """SESSION_SSOT_READS=False: coin은 legacy dict 단독(SM 폴백 없음)으로
    완전 복귀 -- 이것이 P1-3 이전의 기존 거동(재시작 후 404)이다."""
    from app.api.routes.coin import get_coin_sessions
    from services.session_manager import MarketType, get_session_manager

    monkeypatch.setattr(
        coin_analysis_module, "get_settings",
        lambda: types.SimpleNamespace(SESSION_SSOT_READS=False),
    )

    coin_sessions = get_coin_sessions()
    coin_sessions["ssot-p13-cs-legacy"] = {
        "session_id": "ssot-p13-cs-legacy",
        "market": "KRW-ETH",
        "korean_name": "이더리움",
        "status": "running",
        "state": {"reasoning_log": []},
    }

    sm = await get_session_manager()
    await sm.create_session(
        "ssot-p13-cs-sm-only", MarketType.COIN, "KRW-BTC", "비트코인",
        market="KRW-BTC", korean_name="비트코인",
        state={"reasoning_log": []},
    )
    try:
        legacy_resp = client.get("/api/coin/analysis/status/ssot-p13-cs-legacy")
        assert legacy_resp.status_code == 200
        assert legacy_resp.json()["session_id"] == "ssot-p13-cs-legacy"

        # legacy-only helper: SM-only session is NOT visible under False
        # (this is the pre-existing behavior this task is changing under True).
        sm_only_resp = client.get("/api/coin/analysis/status/ssot-p13-cs-sm-only")
        assert sm_only_resp.status_code == 404
    finally:
        coin_sessions.pop("ssot-p13-cs-legacy", None)
        await sm.remove_session("ssot-p13-cs-sm-only")
