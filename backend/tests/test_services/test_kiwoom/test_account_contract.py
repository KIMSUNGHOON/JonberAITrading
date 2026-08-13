"""계좌 TR 계약 테스트 (Paper-Proof Phase A1-t2).

픽스처는 공식 스펙(계좌.md)의 **실제 응답 키**를 사용한다 — 기존 테스트가
클라이언트와 같은 가공 키(output/hldg_qty)로 자기 목을 검증하던 것이 감사
C4-C7의 근본 원인이었다.

- C4: kt00004 보유종목 키는 rmnd_qty/avg_prc/pl_amt/pl_rt (계좌.md:2032-2037)
- C5: 응답 stk_cd는 "A005930" 형태 — A 접두사 스트립 필요 (계좌.md:2128)
- C6: ka10075 리스트 키 oso; 요청 all_stk_tp 0:전체/1:종목, stex_tp 0/1/2
- C7: ka10076 필수 요청 qry_tp/sell_tp/stex_tp; 리스트 키 cntr
- M1: 손익은 부호 보존; 평가금액은 tot_est_amt(주식만)
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.kiwoom.client import KiwoomClient


@pytest.fixture
def client():
    return KiwoomClient(
        app_key="k", secret_key="s", is_mock=True,
        enable_rate_limit=False, enable_cache=False,
    )


KT00004_RESPONSE = {
    "return_code": 0,
    "entr": "000000017534",
    "d2_entra": "000000012550",
    "tot_est_amt": "000000342000",   # 유가잔고평가액 (주식만)
    "aset_evlt_amt": "000000761950", # 예탁자산평가액 (현금 포함)
    "tot_pur_amt": "000000505958",
    "tdy_lspft": "-00000000163",     # 당일투자손익 (음수)
    "lspft": "-00000163958",         # 누적투자손익 (음수)
    "lspft_rt": "-32.40",
    "lspft_amt": "000000505958",     # 누적투자원금 — 손익이 아님!
    "stk_acnt_evlt_prst": [
        {
            "stk_cd": "A005930",
            "stk_nm": "삼성전자",
            "rmnd_qty": "000000000003",
            "avg_prc": "000000124500",
            "cur_prc": "000000070000",
            "evlt_amt": "000000210000",
            "pl_amt": "-00000163958",
            "pl_rt": "-43.8977",
            "pur_amt": "000000373500",
        }
    ],
}


class TestAccountBalanceContract:
    @pytest.mark.asyncio
    async def test_holdings_parse_official_keys(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = KT00004_RESPONSE
            balance = await client.get_account_balance()

        assert len(balance.holdings) == 1
        h = balance.holdings[0]
        assert h.stk_cd == "005930"      # C5: A 접두사 스트립
        assert h.hldg_qty == 3           # C4: rmnd_qty
        assert h.avg_buy_prc == 124500   # C4: avg_prc
        assert h.cur_prc == 70000
        assert h.evlu_amt == 210000      # evlt_amt
        assert h.evlu_pfls_amt == -163958  # C4+M1: pl_amt, 부호 보존
        assert h.evlu_pfls_rt == pytest.approx(-43.8977)

    @pytest.mark.asyncio
    async def test_summary_uses_stock_valuation_not_deposit_asset(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = KT00004_RESPONSE
            balance = await client.get_account_balance()

        assert balance.pchs_amt == 505958
        assert balance.evlu_amt == 342000        # M1: tot_est_amt (주식만)
        # M1: 평가손익 = 유가평가액 - 총매입 (누적투자원금 lspft_amt 아님)
        assert balance.evlu_pfls_amt == 342000 - 505958
        assert balance.evlu_pfls_amt < 0         # 손실이 음수로 보존
        assert balance.d2_ord_psbl_amt == 12550  # d2_entra

    @pytest.mark.asyncio
    async def test_request_body_unchanged(self, client):
        # 요청은 감사에서 OK 판정 — 회귀 고정
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = {"return_code": 0, "stk_acnt_evlt_prst": []}
            await client.get_account_balance()
        assert m.call_args.kwargs["data"] == {"qry_tp": "0", "dmst_stex_tp": "KRX"}


KA10075_RESPONSE = {
    "return_code": 0,
    "oso": [
        {
            "ord_no": "0000138", "stk_cd": "A005930", "stk_nm": "삼성전자",
            "ord_qty": "000000000010", "ord_pric": "000000068000",
            "oso_qty": "000000000004", "cntr_qty": "000000000006",
            "trde_tp": "2", "io_tp_nm": "+매수", "tm": "132212",
            "orig_ord_no": "0000000", "ord_stt": "접수",
        }
    ],
}


class TestPendingOrdersContract:
    @pytest.mark.asyncio
    async def test_request_uses_official_value_domains(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = {"return_code": 0, "oso": []}
            await client.get_pending_orders()
        data = m.call_args.kwargs["data"]
        # C6: 기본 전체 조회 — all_stk_tp 0:전체, trde_tp 0:전체, stex_tp 0:통합
        assert data["all_stk_tp"] == "0"
        assert data["trde_tp"] == "0"
        assert data["stex_tp"] == "0"

    @pytest.mark.asyncio
    async def test_single_stock_query_sends_stk_cd(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = {"return_code": 0, "oso": []}
            await client.get_pending_orders(stk_cd="005930")
        data = m.call_args.kwargs["data"]
        assert data["all_stk_tp"] == "1"  # 1:종목
        assert data["stk_cd"] == "005930"

    @pytest.mark.asyncio
    async def test_parses_oso_list_with_official_keys(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = KA10075_RESPONSE
            orders = await client.get_pending_orders()

        assert len(orders) == 1
        o = orders[0]
        assert o.stk_cd == "005930"     # A 스트립
        assert o.ord_qty == 10
        assert o.ord_uv == 68000        # ord_pric
        assert o.ccld_qty == 6          # cntr_qty
        assert o.rmn_qty == 4           # oso_qty
        assert o.ord_tm == "132212"     # tm
        assert o.buy_sell_tp == "1"     # 소비자 계약: "1"=매수 (ka10075 trde_tp 2=매수)


KA10076_RESPONSE = {
    "return_code": 0,
    "cntr": [
        {
            "ord_no": "0000037", "stk_cd": "A005930", "stk_nm": "삼성전자",
            "cntr_qty": "1", "cntr_pric": "70000", "ord_pric": "70000",
            "ord_qty": "1", "oso_qty": "0", "ord_stt": "체결",
            "trde_tp": "보통", "io_tp_nm": "-매도", "ord_tm": "153815",
            "orig_ord_no": "0000000",
        }
    ],
}


class TestFilledOrdersContract:
    @pytest.mark.asyncio
    async def test_request_sends_required_fields(self, client):
        # C7: 모의서버가 실증한 필수 필드 — qry_tp/sell_tp/stex_tp
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = {"return_code": 0, "cntr": []}
            await client.get_filled_orders()
        data = m.call_args.kwargs["data"]
        assert data["qry_tp"] == "0"
        assert data["sell_tp"] == "0"
        assert data["stex_tp"] == "0"

    @pytest.mark.asyncio
    async def test_parses_cntr_list_with_official_keys(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = KA10076_RESPONSE
            fills = await client.get_filled_orders()

        assert len(fills) == 1
        f = fills[0]
        assert f.stk_cd == "005930"
        assert f.ccld_qty == 1          # cntr_qty
        assert f.ccld_uv == 70000       # cntr_pric
        assert f.ccld_amt == 70000      # 응답에 없음 — cntr_qty*cntr_pric 계산
        assert f.ccld_tm == "153815"    # ord_tm
        assert f.buy_sell_tp == "2"     # 소비자 계약: "2"=매도 (io_tp_nm "-매도")


class TestStockCodePrefix:
    def test_strip_prefix(self):
        assert KiwoomClient._strip_stock_prefix("A005930") == "005930"
        assert KiwoomClient._strip_stock_prefix("005930") == "005930"
        assert KiwoomClient._strip_stock_prefix("") == ""
