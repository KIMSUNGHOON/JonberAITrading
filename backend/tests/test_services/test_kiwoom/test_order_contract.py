"""주문 정정/취소 TR 계약 테스트 (Paper-Proof Phase A1-t3).

감사 C1/C2: kt10002/kt10003의 요청 필드명이 공식 스펙(주문.md:185-194,
263-268)과 전면 불일치 — orig_ord_no/mdfy_qty/mdfy_uv/cncl_qty가 정답이고,
kt10002에 trde_tp 필드는 존재하지 않는다. 정정/취소가 100% 거부되던 상태.
다음 Phase에서 이 코드로 모의 계좌에 실주문이 나간다.
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.kiwoom.client import KiwoomClient

OK_RESPONSE = {
    "return_code": 0,
    "ord_no": "0000140",
    "base_orig_ord_no": "0000138",
    "return_msg": "정상적으로 처리되었습니다",
}


@pytest.fixture
def client():
    return KiwoomClient(
        app_key="k", secret_key="s", is_mock=True,
        enable_rate_limit=False, enable_cache=False,
    )


class TestModifyOrderContract:
    @pytest.mark.asyncio
    async def test_modify_sends_official_field_names(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = OK_RESPONSE
            await client.modify_order(
                org_ord_no="0000138", stk_cd="005930", qty=2, price=70000
            )
        data = m.call_args.kwargs["data"]
        assert data == {
            "orig_ord_no": "0000138",   # C1: org_ord_no 아님
            "stk_cd": "005930",
            "mdfy_qty": "2",            # C1: ord_qty 아님
            "mdfy_uv": "70000",         # C1: ord_uv 아님
            "dmst_stex_tp": "KRX",
        }
        # C1: trde_tp는 kt10002 스펙에 존재하지 않는 필드
        assert "trde_tp" not in data

    @pytest.mark.asyncio
    async def test_modify_parses_base_orig_ord_no(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = OK_RESPONSE
            resp = await client.modify_order(
                org_ord_no="0000138", stk_cd="005930", qty=2, price=70000
            )
        assert resp.ord_no == "0000140"
        assert resp.base_orig_ord_no == "0000138"


class TestCancelOrderContract:
    @pytest.mark.asyncio
    async def test_cancel_sends_official_field_names(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = OK_RESPONSE
            await client.cancel_order(org_ord_no="0000138", stk_cd="005930", qty=3)
        data = m.call_args.kwargs["data"]
        assert data == {
            "orig_ord_no": "0000138",   # C2
            "stk_cd": "005930",
            "cncl_qty": "3",            # C2: ord_qty 아님
            "dmst_stex_tp": "KRX",
        }

    @pytest.mark.asyncio
    async def test_cancel_default_qty_zero_means_cancel_all(self, client):
        # 스펙: cncl_qty '0' 입력 시 잔량 전부 취소 (주문.md:268)
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = OK_RESPONSE
            await client.cancel_order(org_ord_no="0000138", stk_cd="005930")
        assert m.call_args.kwargs["data"]["cncl_qty"] == "0"
