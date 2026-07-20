"""Regression: get_stock_list must not TypeError into the 15-stock fallback.

The pagination loop passed `extra_headers=` to `_request`, which does not accept
it -> TypeError -> swallowed by the scanner's blanket except -> 15 hardcoded
stocks. `_request` already forwards `cont_yn`/`next_key` into the cont-yn/next-key
headers, so the loop must use those.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.kiwoom.client import KiwoomClient
from services.kiwoom.models import MarketType


def _client_with_fake_http(body):
    client = KiwoomClient(app_key="k", secret_key="s", is_mock=True)
    client.auth.get_token = AsyncMock(return_value="tok")
    client._rate_limiter = None
    client._cache = None

    captured = {}

    class FakeResp:
        status_code = 200
        headers = {}

        def json(self):
            return body

    async def fake_post(url, json=None, headers=None):
        captured["headers"] = headers
        return FakeResp()

    fake_http = MagicMock()
    fake_http.post = AsyncMock(side_effect=fake_post)
    client._get_client = AsyncMock(return_value=fake_http)
    return client, captured


@pytest.mark.asyncio
async def test_request_forwards_cont_yn_and_next_key():
    client, captured = _client_with_fake_http({"return_code": 0, "list": []})
    await client._request(
        api_id="ka10099",
        endpoint="/api/dostk/stkinfo",
        data={"mrkt_tp": "0"},
        cont_yn="Y",
        next_key="ABC",
    )
    assert captured["headers"]["cont-yn"] == "Y"
    assert captured["headers"]["next-key"] == "ABC"


@pytest.mark.asyncio
async def test_get_stock_list_returns_real_items_not_fallback():
    client, _ = _client_with_fake_http({"return_code": 0, "list": [
        {"code": "005930", "name": "삼성전자", "marketName": "코스피"},
        {"code": "000660", "name": "SK하이닉스", "marketName": "코스피"},
    ]})
    items = await client.get_stock_list(MarketType.KOSPI)  # pre-fix: TypeError
    assert [i.code for i in items] == ["005930", "000660"]


# ---------------------------------------------------------------------------
# DQ-1: ETN/스팩 유니버스 이름 필터 (get_all_stocks exclude_etf_etn)
# ---------------------------------------------------------------------------

_MIXED_UNIVERSE = {
    "return_code": 0,
    "list": [
        {"code": "005930", "name": "삼성전자", "marketName": "코스피"},
        {"code": "000660", "name": "SK하이닉스", "marketName": "코스피"},
        {"code": "900001", "name": "크레오에스지", "marketName": "코스닥"},
        {"code": "900002", "name": "웹젠", "marketName": "코스닥"},
        {"code": "900003", "name": "제이에스링크", "marketName": "코스닥"},
        {"code": "500001", "name": "1Q 현대차그룹채권", "marketName": "코스피"},
        {"code": "500002", "name": "CD금리투자 ETN", "marketName": "코스피"},
        {"code": "500003", "name": "OO스팩3호", "marketName": "코스닥"},
        {"code": "500004", "name": "TIGER 회사채", "marketName": "코스피"},
    ],
}

_REAL_STOCK_CODES = ["005930", "000660", "900001", "900002", "900003"]
_ETF_ETN_CODES = ["500001", "500002", "500003", "500004"]


@pytest.mark.asyncio
async def test_get_all_stocks_exclude_etf_etn_true_filters_names_keeps_real_stocks():
    """exclude_etf_etn=True(신규 기본값)면 ETN/스팩/채권 파생상품 이름은
    제외되고 실주식(삼성전자/SK하이닉스/크레오에스지/웹젠/제이에스링크)은
    통과해야 한다(오탐 방지 회귀)."""
    client, _ = _client_with_fake_http(_MIXED_UNIVERSE)
    items = await client.get_all_stocks(
        include_kospi=True, include_kosdaq=True, exclude_etf_etn=True,
    )
    codes = {i.code for i in items}
    assert codes == set(_REAL_STOCK_CODES)
    for code in _ETF_ETN_CODES:
        assert code not in codes


@pytest.mark.asyncio
async def test_get_all_stocks_exclude_etf_etn_defaults_to_true():
    """exclude_etf_etn 인자를 생략해도(신규 기본값 True) ETN/스팩류가
    제외돼야 한다."""
    client, _ = _client_with_fake_http(_MIXED_UNIVERSE)
    items = await client.get_all_stocks(include_kospi=True, include_kosdaq=True)
    codes = {i.code for i in items}
    for code in _ETF_ETN_CODES:
        assert code not in codes
    assert set(_REAL_STOCK_CODES).issubset(codes)


@pytest.mark.asyncio
async def test_get_all_stocks_exclude_etf_etn_false_keeps_everything_byte_invariant():
    """기존 콜사이트 하위호환: exclude_etf_etn=False면 이름 필터 없이 전량
    유지된다(byte-불변 — is_normal 필터만 적용됨, 이 목 응답은 orderWarning
    기본값 '0'이라 전부 정상 종목)."""
    client, _ = _client_with_fake_http(_MIXED_UNIVERSE)
    items = await client.get_all_stocks(
        include_kospi=True, include_kosdaq=True, exclude_etf_etn=False,
    )
    codes = {i.code for i in items}
    assert codes == set(_REAL_STOCK_CODES) | set(_ETF_ETN_CODES)
