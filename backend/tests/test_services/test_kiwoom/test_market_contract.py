"""시세/종목정보/차트 TR 계약 테스트 (Paper-Proof Phase A1-t4).

- C8: ka10004 호가 응답 키는 sel_fpr_bid(1호가)/sel_{n}th_pre_bid(2~10호가)/
  buy_* / tot_sel_req/tot_buy_req (시세.md:90-137) — 기존 sell_hoga_* 키는
  스펙에 없어 호가 10단이 조용히 빈 리스트였다.
- M2: ka10001 상장주식수는 flo_stk (lstg_stqt는 미존재 키 — 항상 None이었음).
- M3: ka10099 marketCode "0"=코스피, "10"=코스닥 (기존 판정 반전).
- M4: ka10081 수정주가 기본 "1" + trde_prica 단위 백만원→원 환산.
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.kiwoom.client import KiwoomClient
from services.kiwoom.models import StockListItem


@pytest.fixture
def client():
    return KiwoomClient(
        app_key="k", secret_key="s", is_mock=True,
        enable_rate_limit=False, enable_cache=False,
    )


def _orderbook_response():
    resp = {
        "return_code": 0,
        "sel_fpr_bid": "+70100", "sel_fpr_req": "100",
        "buy_fpr_bid": "+70000", "buy_fpr_req": "200",
        "tot_sel_req": "5500", "tot_buy_req": "7700",
    }
    for n in range(2, 11):
        resp[f"sel_{n}th_pre_bid"] = str(70100 + (n - 1) * 100)
        resp[f"sel_{n}th_pre_req"] = str(100 + n)
        resp[f"buy_{n}th_pre_bid"] = str(70000 - (n - 1) * 100)
        resp[f"buy_{n}th_pre_req"] = str(200 + n)
    return resp


class TestOrderbookContract:
    @pytest.mark.asyncio
    async def test_parses_official_hoga_keys_all_ten_levels(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = _orderbook_response()
            ob = await client.get_orderbook("005930")

        assert len(ob.sell_hogas) == 10
        assert len(ob.buy_hogas) == 10
        assert ob.sell_hogas[0].price == 70100   # sel_fpr_bid (1호가)
        assert ob.sell_hogas[0].quantity == 100
        assert ob.sell_hogas[1].price == 70200   # sel_2th_pre_bid
        assert ob.buy_hogas[0].price == 70000    # buy_fpr_bid
        assert ob.buy_hogas[9].price == 70000 - 900
        assert ob.tot_sell_qty == 5500           # tot_sel_req
        assert ob.tot_buy_qty == 7700            # tot_buy_req
        assert ob.spread == 100


class TestStockInfoContract:
    @pytest.mark.asyncio
    async def test_listed_shares_from_flo_stk(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = {
                "return_code": 0,
                "output": {
                    "stk_cd": "005930", "stk_nm": "삼성전자",
                    "cur_prc": "70000", "flo_stk": "5969783",
                },
            }
            info = await client.get_stock_info("005930")
        assert info.lstg_stqt == 5969783  # M2: flo_stk가 정답 키


class TestMarketCodeClassification:
    def test_market_code_0_is_kospi(self):
        item = StockListItem(code="005930", name="삼성전자",
                             market_code="0", market_name="코스피")
        assert item.is_kospi is True
        assert item.is_kosdaq is False

    def test_market_code_10_is_kosdaq(self):
        # M3: 스펙 예제(종목정보.md:3201-3202) marketCode "10" = 코스닥
        item = StockListItem(code="123456", name="코스닥종목",
                             market_code="10", market_name="코스닥")
        assert item.is_kosdaq is True
        assert item.is_kospi is False


class TestDailyChartContract:
    @pytest.mark.asyncio
    async def test_adjusted_price_by_default(self, client):
        # M4: 원주가(0)는 액면분할 시 가짜 갭 — 분석용 기본은 수정주가(1)
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = {"return_code": 0, "stk_dt_pole_chart_qry": []}
            await client.get_daily_chart("005930")
        assert m.call_args.kwargs["data"]["upd_stkpc_tp"] == "1"

    @pytest.mark.asyncio
    async def test_trde_prica_converted_from_millions_to_won(self, client):
        # M4: trde_prica 단위는 백만원 (kiwoom_api_spec.json) — 하류는 원 단위
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = {"return_code": 0, "stk_dt_pole_chart_qry": [{
                "dt": "20260710", "open_pric": "70000", "high_pric": "71000",
                "low_pric": "69000", "cur_prc": "70500", "trde_qty": "1000",
                "trde_prica": "825000",  # 백만원 단위
            }]}
            candles = await client.get_daily_chart("005930")
        assert candles[0].acml_tr_pbmn == 825_000 * 1_000_000

    # ---- 밸류에이션 필드 결측/0 구분 (2026-07-29) ----

    @pytest.mark.asyncio
    async def test_zero_eps_is_preserved_not_collapsed_to_none(self, client):
        """EPS 0은 실재하는 값(이익이 정확히 0)이므로 None으로 붕괴하면 안 된다.

        `if output.get("eps")` 진위값 검사는 숫자 0을 falsy로 보고 None을
        만든다. 적자 배제 게이트(factors.passes_quality_filter)는 EPS<=0을
        배제하도록 설계됐는데, 0이 None이 되면 "모름"으로 분류돼 fail-open으로
        통과한다 — 게이트가 조용히 뚫린다.
        """
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = {
                "return_code": 0,
                "output": {
                    "stk_cd": "005930", "stk_nm": "삼성전자",
                    "cur_prc": "70000", "eps": 0, "bps": 0,
                },
            }
            info = await client.get_stock_info("005930")
        assert info.eps == 0, "EPS 0이 None으로 붕괴하면 적자 게이트가 뚫린다"
        assert info.bps == 0

    @pytest.mark.asyncio
    async def test_missing_valuation_fields_stay_none(self, client):
        """필드가 아예 없으면 None — '모름'과 '0'은 다른 상태다."""
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = {
                "return_code": 0,
                "output": {"stk_cd": "005930", "stk_nm": "삼성전자", "cur_prc": "70000"},
            }
            info = await client.get_stock_info("005930")
        assert info.eps is None
        assert info.bps is None
        assert info.per is None
        assert info.pbr is None

    @pytest.mark.asyncio
    async def test_empty_string_valuation_is_none(self, client):
        """빈 문자열은 결측으로 취급한다(키움이 미제공 시 ""를 주는 경우)."""
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = {
                "return_code": 0,
                "output": {
                    "stk_cd": "005930", "stk_nm": "삼성전자",
                    "cur_prc": "70000", "eps": "", "per": "", "pbr": "", "bps": "",
                },
            }
            info = await client.get_stock_info("005930")
        assert info.eps is None
        assert info.per is None
        assert info.pbr is None
        assert info.bps is None
