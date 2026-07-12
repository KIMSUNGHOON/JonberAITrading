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
