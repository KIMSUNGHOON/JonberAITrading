"""토스증권 Open API 클라이언트 (2026-08-12).

실호출로 검증한 계약을 고정한다(2026-08-12 22:38, 이 맥에서 직접):
  POST /oauth2/token            → 200, access_token 834자, expires_in 86399
  GET  /api/v1/market-indicators/KOSPI/candles?interval=1d&count=5
                                → 200, {"result": {"candles": [...]}}
  GET  /api/v1/stocks/{sym}/warnings → 200, {"result": []}

🔴 **403을 다른 실패와 반드시 구별한다.** IP 화이트리스트가 깨지면 전
API가 403이 되는데, 넓은 except가 그것을 "데이터 없음"으로 삼키면
2026-08-07 계열의 사고(데이터 실패가 노출도 상한을 두 배로 열던 것)가 된다.
"""
import pytest

from services.toss.client import TossClient, TossIpBlockedError

pytestmark = pytest.mark.asyncio


class _FakeResponse:
    def __init__(self, status: int, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _FakeHttp:
    """httpx.AsyncClient 대역. 요청을 기록하고 정해진 응답을 돌려준다."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.requests: list[tuple[str, str, dict]] = []

    async def post(self, url, data=None, headers=None, **kw):
        self.requests.append(("POST", url, headers or {}))
        return self.routes[("POST", url)]

    async def get(self, url, headers=None, params=None, **kw):
        self.requests.append(("GET", url, headers or {}))
        return self.routes[("GET", url)]


def _token_ok(token="tok-abc"):
    return _FakeResponse(200, {"access_token": token, "token_type": "Bearer", "expires_in": 86399})


async def test_token_is_fetched_once_and_reused():
    """토큰은 24시간 유효하다. 요청마다 새로 받으면 발급 한도를 태운다."""
    http = _FakeHttp({
        ("POST", "https://openapi.tossinvest.com/oauth2/token"): _token_ok(),
        ("GET", "https://openapi.tossinvest.com/api/v1/stocks/005930/warnings"):
            _FakeResponse(200, {"result": []}),
    })
    c = TossClient(client_id="i", client_secret="s", http=http)

    await c.get_warnings("005930")
    await c.get_warnings("005930")

    posts = [r for r in http.requests if r[0] == "POST"]
    assert len(posts) == 1


async def test_bearer_header_is_attached():
    http = _FakeHttp({
        ("POST", "https://openapi.tossinvest.com/oauth2/token"): _token_ok("T123"),
        ("GET", "https://openapi.tossinvest.com/api/v1/stocks/005930/warnings"):
            _FakeResponse(200, {"result": []}),
    })
    c = TossClient(client_id="i", client_secret="s", http=http)

    await c.get_warnings("005930")

    get_req = [r for r in http.requests if r[0] == "GET"][0]
    assert get_req[2]["Authorization"] == "Bearer T123"


async def test_403_raises_a_distinct_error():
    """IP 화이트리스트 이탈을 '데이터 없음'으로 삼키면 안 된다.
    호출자가 이 예외를 보고 로그·Telegram에 올릴 수 있어야 한다."""
    http = _FakeHttp({
        ("POST", "https://openapi.tossinvest.com/oauth2/token"): _token_ok(),
        ("GET", "https://openapi.tossinvest.com/api/v1/stocks/005930/warnings"):
            _FakeResponse(403, {"error": "edge-blocked"}),
    })
    c = TossClient(client_id="i", client_secret="s", http=http)

    with pytest.raises(TossIpBlockedError):
        await c.get_warnings("005930")


async def test_kospi_candles_unwraps_result():
    """응답 래퍼가 {"result": {"candles": [...]}}다 — 실호출로 확인한 모양."""
    http = _FakeHttp({
        ("POST", "https://openapi.tossinvest.com/oauth2/token"): _token_ok(),
        ("GET", "https://openapi.tossinvest.com/api/v1/market-indicators/KOSPI/candles"):
            _FakeResponse(200, {"result": {"candles": [
                {"timestamp": "2026-08-11T00:00:00.000+09:00", "closePrice": 6345.53},
                {"timestamp": "2026-08-10T00:00:00.000+09:00", "closePrice": 6299.66},
            ]}}),
    })
    c = TossClient(client_id="i", client_secret="s", http=http)

    rows = await c.get_index_candles("KOSPI", count=5)

    assert rows == [("2026-08-11", 6345.53), ("2026-08-10", 6299.66)]


async def test_missing_credentials_disable_the_client():
    """`.env`에 키가 없으면 조용히 죽는 대신 명시적으로 비활성이어야 한다."""
    c = TossClient(client_id=None, client_secret=None, http=_FakeHttp({}))
    assert c.enabled is False


# ---- 싱글턴 팩토리 (T2 배선) ----


async def test_factory_returns_disabled_client_without_credentials(monkeypatch):
    """자격증명이 없으면 `enabled=False` 클라이언트를 준다 — None을
    돌려주면 호출자가 매번 None 검사를 해야 하고, 빠뜨리면 AttributeError로
    EOD 체인이 죽는다."""
    import services.toss as toss_mod
    from app.config import get_settings

    monkeypatch.setattr(toss_mod, "_client", None, raising=False)
    s = get_settings()
    monkeypatch.setattr(s, "TOSS_CLIENT_ID", None, raising=False)
    monkeypatch.setattr(s, "TOSS_CLIENT_SECRET", None, raising=False)

    c = toss_mod.get_toss_client()
    assert c.enabled is False


async def test_factory_is_a_singleton(monkeypatch):
    """호출마다 새로 만들면 토큰 캐시가 무의미해진다."""
    import services.toss as toss_mod

    monkeypatch.setattr(toss_mod, "_client", None, raising=False)
    a = toss_mod.get_toss_client()
    b = toss_mod.get_toss_client()
    assert a is b
