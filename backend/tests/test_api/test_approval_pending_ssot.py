"""P1-1: /approval/pending 이 SessionManager 를 단독 소스로 읽는다.

list_pending_approvals / get_pending_approval 은 SessionManager(SQLite
영속) 만 읽는다(legacy in-memory dict 는 P3-1 에서 완전 삭제됨). 판정
술어는 현행과 byte-동일하게 보존: state["awaiting_approval"] truthy &&
state["trade_proposal"] 존재. status 는 검사하지 않는다(action-blind,
status-blind 그대로).

DB 격리: SessionManager 는 모듈 싱글턴(services.session_manager.
_session_manager) + 기본 DB_PATH="data/sessions.db"(612MB 라이브 파일) 를
쓴다. TestClient(app) 진입 시 app.main.lifespan 이 get_session_manager()
를 호출해 싱글턴을 초기화하므로, TestClient 생성 *이전*에 DB_PATH 와
싱글턴을 테스트 전용 파일로 monkeypatch 해야 실 DB 오염을 막을 수 있다
(tests/test_api/test_kr_analysis_sm_migration.py 의 `sm` 픽스처와 동일
패턴).
"""
import os

import pytest
from fastapi.testclient import TestClient

import app.api.routes.approval as approval_module
import services.session_manager as sm_module

TEST_DB_PATH = "data/test_approval_pending_ssot.db"


@pytest.fixture()
def _isolated_sm_db(monkeypatch):
    """SessionManager 싱글턴을 던지는 SQLite 파일로 격리한다.

    client 픽스처가 TestClient(app) 을 열기 *전에* 먼저 셋업되어야
    lifespan 의 get_session_manager() 초기화가 이 DB_PATH 를 보고,
    실 data/sessions.db 는 절대 건드리지 않는다.
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
async def test_pending_reads_sm_only(client, monkeypatch):
    """legacy dict 에 없는 SM-only awaiting 세션이 /pending 에 나타난다."""
    from services.session_manager import (
        MarketType, SessionStatus, get_session_manager,
    )
    sm = await get_session_manager()
    session = await sm.create_session(
        "ssot-p11-kr", MarketType.KIWOOM, "005930", "삼성전자",
        stk_cd="005930", stk_nm="삼성전자",
        state={
            "awaiting_approval": True,
            "trade_proposal": {"action": "BUY", "quantity": 1,
                               "risk_score": 0.3, "rationale": "t",
                               "created_at": "2026-07-16T00:00:00+00:00"},
            "reasoning_log": [],
        },
    )
    session.status = SessionStatus.AWAITING_APPROVAL

    resp = client.get("/api/approval/pending")
    assert resp.status_code == 200
    ids = [p["session_id"] for p in resp.json()["pending_approvals"]]
    assert "ssot-p11-kr" in ids

    # /pending/{id} 도 legacy 폴백 없이 SM 단독으로 답한다
    detail = client.get("/api/approval/pending/ssot-p11-kr")
    assert detail.status_code == 200
    assert detail.json()["session_id"] == "ssot-p11-kr"

    await sm.remove_session("ssot-p11-kr")


@pytest.mark.asyncio
async def test_pending_predicate_unchanged_status_blind(client):
    """술어 보존: status 가 RUNNING 이어도 state 플래그+proposal 만으로 노출 (현행 동일)."""
    from services.session_manager import MarketType, get_session_manager
    sm = await get_session_manager()
    await sm.create_session(
        "ssot-p11-runflag", MarketType.KIWOOM, "000660", "SK하이닉스",
        stk_cd="000660", stk_nm="SK하이닉스",
        state={"awaiting_approval": True,
               "trade_proposal": {"action": "BUY", "quantity": 1,
                                  "risk_score": 0.1, "rationale": "t",
                                  "created_at": "2026-07-16T00:00:00+00:00"},
               "reasoning_log": []},
    )  # status 기본 RUNNING
    resp = client.get("/api/approval/pending")
    ids = [p["session_id"] for p in resp.json()["pending_approvals"]]
    assert "ssot-p11-runflag" in ids
    await sm.remove_session("ssot-p11-runflag")


@pytest.mark.asyncio
async def test_pending_predicate_no_proposal_excluded(client):
    """술어 보존: trade_proposal 이 없으면 awaiting_approval=True 여도 제외."""
    from services.session_manager import MarketType, get_session_manager
    sm = await get_session_manager()
    await sm.create_session(
        "ssot-p11-noprop", MarketType.KIWOOM, "005380", "현대차",
        stk_cd="005380", stk_nm="현대차",
        state={"awaiting_approval": True, "reasoning_log": []},
    )
    resp = client.get("/api/approval/pending")
    ids = [p["session_id"] for p in resp.json()["pending_approvals"]]
    assert "ssot-p11-noprop" not in ids
    await sm.remove_session("ssot-p11-noprop")


@pytest.mark.asyncio
async def test_pending_detail_404_when_absent(client):
    """/pending/{id} 는 SM 에 없는 세션에 대해 404 (legacy dict 폴백 없음)."""
    resp = client.get("/api/approval/pending/ssot-p11-does-not-exist")
    assert resp.status_code == 404

