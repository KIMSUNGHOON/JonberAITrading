"""POST /trading/discovery/run — 수동 발굴 파이프라인 트리거.

이 라우트는 마감 엣지의 discovery 두 스텝(_run_discovery_scan →
run_discovery_pipeline)을 라이브 coordinator/scanner 싱글턴에 대해 실행하되,
전 종목 스캔이 수 시간이라 asyncio.create_task로 백그라운드에 던지고 즉시
반환한다(POST /scanner/start와 동일한 fire-and-forget).

TestClient(동기)는 자체 포털/루프에서 ASGI를 돌려 create_task된 백그라운드
잡을 테스트 스레드에서 드레인하기 어렵다. 그래서 여기서는 httpx.AsyncClient +
ASGITransport로 **테스트와 동일한 이벤트 루프**에서 앱을 구동하고, 라우트가
_discovery_run_tasks 집합에 담아둔 태스크를 직접 await해 잡 본체까지 결정론적으로
검증한다.

실 LLM/네트워크/DB 없음: get_trading_coordinator는 dependency_overrides로 스텁,
get_settings/get_storage_service/get_background_scanner/run_discovery_pipeline은
trading 모듈 네임스페이스에서 패치한다. 앱 lifespan은 구동하지 않는다(이 라우트가
SessionManager/실 storage를 건드리지 않으므로 불필요).
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import app.api.routes.trading as trading_module
from app.api.routes.trading import get_trading_coordinator
from app.main import app


def _settings(enabled: bool) -> MagicMock:
    s = MagicMock()
    s.DISCOVERY_ENABLED = enabled
    return s


async def _post(json_body: dict):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/trading/discovery/run", json=json_body)


async def _drain_discovery_jobs():
    # 라우트가 방금 스케줄한 fire-and-forget 잡을 완주시킨다. 동일 루프이므로
    # 집합에 담긴 태스크를 await하면 잡 본체(_run_discovery_scan +
    # run_discovery_pipeline)가 결정론적으로 실행된다. 잡이 이미 끝나
    # done-callback으로 집합에서 빠졌다면(모두 즉시 반환하는 AsyncMock이라
    # 가능) 이미 mock이 호출된 뒤이므로 그대로 통과한다.
    for _ in range(3):
        pending = list(trading_module._discovery_run_tasks)
        if not pending:
            await asyncio.sleep(0)
            continue
        for t in pending:
            await t


async def test_discovery_run_disabled_short_circuits():
    """DISCOVERY_ENABLED off → enabled/started False, 스캔·파이프라인 미호출."""
    coordinator = MagicMock()
    coordinator._run_discovery_scan = AsyncMock(return_value=True)
    app.dependency_overrides[get_trading_coordinator] = lambda: coordinator
    try:
        with patch.object(trading_module, "get_settings", return_value=_settings(False)), patch.object(
            trading_module, "run_discovery_pipeline", new=AsyncMock()
        ) as pipeline:
            resp = await _post({})
            await _drain_discovery_jobs()
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["enabled"] is False
    assert body["started"] is False
    coordinator._run_discovery_scan.assert_not_awaited()
    pipeline.assert_not_awaited()


async def test_discovery_run_spawns_scan_then_pipeline_with_live_singletons():
    """enabled → started True + 백그라운드 잡이 _run_discovery_scan 후
    run_discovery_pipeline를 **주입된 라이브 coordinator/scanner/storage**와
    올바른 trade_date·scan_ok로 호출한다."""
    coordinator = MagicMock()
    coordinator._run_discovery_scan = AsyncMock(return_value=True)
    app.dependency_overrides[get_trading_coordinator] = lambda: coordinator
    fake_scanner = MagicMock()
    fake_storage = MagicMock()
    try:
        with patch.object(
            trading_module, "get_settings", return_value=_settings(True)
        ), patch.object(
            trading_module, "get_storage_service", new=AsyncMock(return_value=fake_storage)
        ), patch.object(
            trading_module, "get_background_scanner", new=AsyncMock(return_value=fake_scanner)
        ), patch.object(
            trading_module,
            "run_discovery_pipeline",
            new=AsyncMock(return_value={"promoted": ["005930"], "scan_ok": True}),
        ) as pipeline:
            resp = await _post({"date": "2026-07-21"})
            await _drain_discovery_jobs()
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["enabled"] is True
    assert body["started"] is True
    assert body["trade_date"] == "2026-07-21"

    coordinator._run_discovery_scan.assert_awaited_once()
    pipeline.assert_awaited_once()
    _, kwargs = pipeline.call_args
    assert kwargs["coordinator"] is coordinator  # 라이브 싱글턴 그대로
    assert kwargs["scanner"] is fake_scanner
    assert kwargs["storage"] is fake_storage
    assert kwargs["trade_date"] == "2026-07-21"
    assert kwargs["scan_ok"] is True


async def test_discovery_run_defaults_trade_date_to_today_naive():
    """date 생략 시 trade_date = 서버 로컬 오늘(naive) — 마감 체인과 동일 계산
    (스캔 세션 started_at 날짜 매칭 불변식)."""
    coordinator = MagicMock()
    coordinator._run_discovery_scan = AsyncMock(return_value=False)
    app.dependency_overrides[get_trading_coordinator] = lambda: coordinator
    try:
        with patch.object(
            trading_module, "get_settings", return_value=_settings(True)
        ), patch.object(
            trading_module, "get_storage_service", new=AsyncMock(return_value=MagicMock())
        ), patch.object(
            trading_module, "get_background_scanner", new=AsyncMock(return_value=MagicMock())
        ), patch.object(
            trading_module, "run_discovery_pipeline", new=AsyncMock(return_value=None)
        ) as pipeline:
            resp = await _post({})
            await _drain_discovery_jobs()
    finally:
        app.dependency_overrides.clear()

    today = datetime.now().strftime("%Y-%m-%d")
    assert resp.status_code == 200
    assert resp.json()["trade_date"] == today
    # scan_ok=False여도 파이프라인은 호출된다(backfill은 scan_ok 무관 — 파이프라인
    # 내부가 소유). trade_date는 요청 시점 오늘로 넘어간다.
    pipeline.assert_awaited_once()
    _, kwargs = pipeline.call_args
    assert kwargs["trade_date"] == today
    assert kwargs["scan_ok"] is False
