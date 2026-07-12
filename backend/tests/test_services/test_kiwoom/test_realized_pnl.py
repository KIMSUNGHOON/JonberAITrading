"""실현손익 조회 (ka10074) 계약 테스트 (Paper-Proof Phase B1).

공식 계약 (계좌.md:276-334): 요청 strt_dt/end_dt(YYYYMMDD, 필수); 응답 합계
tot_buy_amt/tot_sell_amt/rlzt_pl/trde_cmsn/trde_tax + 일자별 리스트 dt_rlzt_pl.
주의: 실현손익이 발생한 일자만 데이터가 채워진다 (거래 없으면 빈 리스트).

이 메서드가 daily-loss 브레이커(Phase B2)와 성과 리포트(Phase D1)의 데이터
소스다 — 손익 부호 보존이 필수.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from services.kiwoom.client import KiwoomClient

KST = timezone(timedelta(hours=9))


@pytest.fixture
def client():
    return KiwoomClient(
        app_key="k", secret_key="s", is_mock=True,
        enable_rate_limit=False, enable_cache=False,
    )


KA10074_RESPONSE = {
    "return_code": 0,
    "tot_buy_amt": "7000000",
    "tot_sell_amt": "6900000",
    "rlzt_pl": "-100000",
    "trde_cmsn": "3500",
    "trde_tax": "12420",
    "dt_rlzt_pl": [
        {
            "dt": "20260712",
            "buy_amt": "7000000",
            "sell_amt": "6900000",
            "tdy_sel_pl": "-100000",
            "tdy_trde_cmsn": "3500",
            "tdy_trde_tax": "12420",
        }
    ],
}


class TestRealizedPnlContract:
    @pytest.mark.asyncio
    async def test_request_sends_date_range(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = {"return_code": 0, "dt_rlzt_pl": []}
            await client.get_realized_pnl(strt_dt="20260701", end_dt="20260712")
        assert m.call_args.kwargs["api_id"] == "ka10074"
        assert m.call_args.kwargs["endpoint"] == "/api/dostk/acnt"
        assert m.call_args.kwargs["data"] == {"strt_dt": "20260701", "end_dt": "20260712"}

    @pytest.mark.asyncio
    async def test_defaults_to_today_kst(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = {"return_code": 0, "dt_rlzt_pl": []}
            await client.get_realized_pnl()
        today = datetime.now(KST).strftime("%Y%m%d")
        assert m.call_args.kwargs["data"] == {"strt_dt": today, "end_dt": today}

    @pytest.mark.asyncio
    async def test_parses_totals_with_sign_preserved(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = KA10074_RESPONSE
            pnl = await client.get_realized_pnl()
        assert pnl.realized_pnl == -100000   # 손실이 음수로 보존
        assert pnl.total_buy_amount == 7000000
        assert pnl.total_sell_amount == 6900000
        assert pnl.commission == 3500
        assert pnl.tax == 12420

    @pytest.mark.asyncio
    async def test_parses_daily_rows(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = KA10074_RESPONSE
            pnl = await client.get_realized_pnl()
        assert len(pnl.daily) == 1
        d = pnl.daily[0]
        assert d.dt == "20260712"
        assert d.sell_pnl == -100000
        assert d.sell_amount == 6900000

    @pytest.mark.asyncio
    async def test_no_trades_returns_zeros(self, client):
        # 스펙 주의사항: 실현손익 발생 일자만 채워짐 — 무거래면 빈/0
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = {"return_code": 0}
            pnl = await client.get_realized_pnl()
        assert pnl.realized_pnl == 0
        assert pnl.daily == []
