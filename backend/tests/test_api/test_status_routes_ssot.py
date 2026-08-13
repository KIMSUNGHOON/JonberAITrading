"""P1-3: KR GET /analysis/status/{id} 가 SM 단독으로 읽는다.

status 라우트는 SessionManager(SQLite 영속)만 읽는다(legacy in-memory
dict는 P3-1에서 완전 삭제됨). 응답 스키마 구성 코드와 404 시맨틱은 무변경.

코인 스택 제거(2026-08-01) 이전에는 이 파일에 coin status 라우트용 대칭
테스트 2건(재시작 생존/부재 404)도 있었다 — coin 라우트 구현체 자체가
삭제돼 더는 테스트할 대상이 없어 제거했다.

DB 격리: SessionManager는 모듈 싱글턴(services.session_manager.
_session_manager) + 기본 DB_PATH="data/sessions.db"(라이브 파일)를 쓴다.
TestClient(app) 진입 시 app.main.lifespan이 get_session_manager()를 호출해
싱글턴을 초기화하므로, TestClient 생성 *이전*에 DB_PATH와 싱글턴을 테스트
전용 파일로 monkeypatch해야 실 DB 오염을 막을 수 있다
(tests/test_api/test_approval_pending_ssot.py의 `_isolated_sm_db` 픽스처와
동일 패턴).
"""
import os

import pytest
from fastapi.testclient import TestClient

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

