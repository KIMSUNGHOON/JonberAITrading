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


# ---------------------------------------------------------------------------
# DQ-3: 발행사 브랜드 프리픽스 강화 — DQ-1 키워드 목록은 브랜드명만 있고
# 키워드가 없는 ETF("KODEX 200" 등)를 못 잡는 결함이 있었다. 브랜드는 줄
# 시작(^)만 매칭해 실주식명 중간의 우연일치를 방지한다.
# ---------------------------------------------------------------------------

_BRAND_UNIVERSE = {
    "return_code": 0,
    "list": [
        # 실주식 -- 브랜드 프리픽스와 무관하게 통과해야 함(오탐 방지 회귀).
        {"code": "005930", "name": "삼성전자", "marketName": "코스피"},
        {"code": "000660", "name": "SK하이닉스", "marketName": "코스피"},
        {"code": "900001", "name": "크레오에스지", "marketName": "코스닥"},
        {"code": "900002", "name": "웹젠", "marketName": "코스닥"},
        {"code": "900003", "name": "제이에스링크", "marketName": "코스닥"},
        {"code": "900004", "name": "다스코", "marketName": "코스닥"},
        {"code": "900005", "name": "코웨이", "marketName": "코스피"},
        {"code": "900006", "name": "슈프리마에이치큐", "marketName": "코스닥"},
        {"code": "900007", "name": "솔본", "marketName": "코스닥"},
        # 브랜드 프리픽스가 우연히 종목명 앞부분과 겹치는 실제 상장사 --
        # 공백 경계 요구가 없으면 오탐(잘못 제외)되는 케이스.
        {"code": "138930", "name": "BNK금융지주", "marketName": "코스피"},
        {"code": "195940", "name": "HK이노엔", "marketName": "코스닥"},
        # 브랜드-프리픽스만 있고 DQ-1 키워드는 전혀 없는 ETF -- DQ-1 결함
        # 재현 케이스(브랜드 필터 없으면 실주식으로 오분류됨).
        {"code": "500010", "name": "KODEX 200", "marketName": "코스피"},
        {"code": "500011", "name": "TIGER 미국나스닥100", "marketName": "코스피"},
        {"code": "500012", "name": "ACE 미국S&P500", "marketName": "코스피"},
        {"code": "500013", "name": "KBSTAR 200", "marketName": "코스피"},
        {"code": "500014", "name": "SOL 미국배당다우존스", "marketName": "코스피"},
        {"code": "500015", "name": "1Q 200", "marketName": "코스피"},
        # 해외/상품 키워드 보강 -- 브랜드 없이 키워드만으로 잡히는 케이스.
        {"code": "500016", "name": "KODEX 인도Nifty50", "marketName": "코스피"},
        {"code": "500017", "name": "TIGER 커버드콜", "marketName": "코스피"},
    ],
}

_BRAND_REAL_STOCK_CODES = [
    "005930", "000660", "900001", "900002", "900003", "900004",
    "900005", "900006", "900007", "138930", "195940",
]
_BRAND_ETF_CODES = [
    "500010", "500011", "500012", "500013", "500014", "500015",
    "500016", "500017",
]


@pytest.mark.asyncio
async def test_get_all_stocks_brand_prefix_filters_etf_keeps_real_stocks():
    """브랜드 프리픽스 전용 ETF(키워드 없이 브랜드+지수명만)는 제외되고,
    브랜드 프리픽스와 우연히 겹치는 실주식(BNK금융지주/HK이노엔 -- 공백 없이
    바로 한글이 이어짐)은 통과해야 한다."""
    client, _ = _client_with_fake_http(_BRAND_UNIVERSE)
    items = await client.get_all_stocks(
        include_kospi=True, include_kosdaq=True, exclude_etf_etn=True,
    )
    codes = {i.code for i in items}
    assert codes == set(_BRAND_REAL_STOCK_CODES)
    for code in _BRAND_ETF_CODES:
        assert code not in codes
