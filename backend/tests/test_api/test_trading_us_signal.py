"""읽기전용 US 신호 엔드포인트 계약 테스트 (관측성 T1).

GET /api/trading/discovery/us-signal -- pure observability, no state mutation.

Convention notes (verified against neighboring tests/test_api files before
writing this):
- ``client: TestClient`` is the repo's established shared fixture
  (tests/conftest.py, module-scoped ``with TestClient(app) as test_client``)
  used directly (no extra isolation) by test_strategy_routes.py /
  test_health.py for routes with no SessionManager/storage dependency --
  this route touches neither, so the plain shared fixture applies as-is.
  (tests/conftest.py also defines an ``async_client`` fixture, but it is
  unused anywhere in the suite and is broken under the pinned httpx 0.28.1
  -- ``AsyncClient(app=app, ...)`` was removed in favor of
  ``ASGITransport``,  so it raises
  ``TypeError: AsyncClient.__init__() got an unexpected keyword argument
  'app'`` before a single request is sent. Verified by running this file
  with async-def + ``async_client`` first: all 3 tests errored identically
  at fixture setup. The sync ``client`` fixture is the only proven-working
  house pattern for exercising async routes -- TestClient runs the ASGI app
  through its own portal, so ``await``ing an ``AsyncMock``-patched
  dependency inside the route still works fine synchronously from the
  test's point of view, exactly as test_discovery_routes.py already relies
  on for its ``AsyncMock``-patched ``get_storage_service``.)
- Route uses function-local imports (``from app.config import
  get_settings``, ``from services.trading.us_market_data import
  get_cached_us_ai_signal, US_AI_TICKERS``) specifically so tests can patch
  at the source module -- the import statement resolves the *current*
  module attribute at call time, so patching ``app.config.get_settings`` /
  ``services.trading.us_market_data.get_cached_us_ai_signal`` before the
  request is enough; no need to patch the attribute as imported into
  trading.py.
"""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def _fake_settings(enabled: bool):
    class S:
        US_SIGNAL_ENABLED = enabled

    return S()


def test_us_signal_enabled_fresh(client: TestClient):
    cached = {
        "signal": 1.0,
        "signal_pct": 5.8,
        "components": {"SMH": 4.52, "MU": 12.17, "NVDA": 1.97},
        "as_of": "2026-07-22",
        "computed_at": "2026-07-22T03:09:12Z",
    }
    with patch("app.config.get_settings", return_value=_fake_settings(True)), \
         patch(
             "services.trading.us_market_data.get_cached_us_ai_signal",
             new=AsyncMock(return_value=cached),
         ):
        r = client.get("/api/trading/discovery/us-signal")
    assert r.status_code == 200
    d = r.json()
    assert d["enabled"] is True
    assert d["as_of"] == "2026-07-22"
    assert d["signal_pct"] == 5.8 and d["signal"] == 1.0
    comps = {c["ticker"]: c for c in d["components"]}
    assert comps["SMH"]["weight"] == 0.5 and comps["SMH"]["change_pct"] == 4.52
    assert comps["MU"]["change_pct"] == 12.17
    # 큐레이션 7종 항상
    codes = {c["ticker"] for c in d["curation"]}
    assert {
        "005930", "000660", "042700", "007660", "353200", "009150", "402340",
    } <= codes


def test_us_signal_enabled_stale_returns_nulls(client: TestClient):
    with patch("app.config.get_settings", return_value=_fake_settings(True)), \
         patch(
             "services.trading.us_market_data.get_cached_us_ai_signal",
             new=AsyncMock(return_value=None),
         ):
        r = client.get("/api/trading/discovery/us-signal")
    assert r.status_code == 200
    d = r.json()
    assert d["enabled"] is True
    assert d["as_of"] is None and d["signal_pct"] is None and d["signal"] is None
    # components 골격은 유지, change_pct=null
    assert {c["ticker"] for c in d["components"]} == {"SMH", "MU", "NVDA"}
    assert all(c["change_pct"] is None for c in d["components"])
    assert len(d["curation"]) == 7  # 큐레이션은 항상


def test_us_signal_disabled(client: TestClient):
    with patch("app.config.get_settings", return_value=_fake_settings(False)), \
         patch(
             "services.trading.us_market_data.get_cached_us_ai_signal",
             new=AsyncMock(return_value=None),
         ):
        r = client.get("/api/trading/discovery/us-signal")
    assert r.status_code == 200
    d = r.json()
    assert d["enabled"] is False
    assert d["signal_pct"] is None
    assert len(d["curation"]) == 7
