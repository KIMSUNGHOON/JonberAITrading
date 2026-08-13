"""실현손익 조회 (ka10074) 계약 테스트 (Paper-Proof Phase B1).

공식 계약 (계좌.md:276-334): 요청 strt_dt/end_dt(YYYYMMDD, 필수); 응답 합계
tot_buy_amt/tot_sell_amt/rlzt_pl/trde_cmsn/trde_tax + 일자별 리스트 dt_rlzt_pl.
주의: 실현손익이 발생한 일자만 데이터가 채워진다 (거래 없으면 빈 리스트).

이 메서드가 daily-loss 브레이커(Phase B2)와 성과 리포트(Phase D1)의 데이터
소스다 — 손익 부호 보존이 필수.

`_request`는 `with_continuation=True`일 때 (응답 dict, {"cont_yn","next_key"})
튜플을 반환한다 — 연속조회 값이 응답 **헤더**로 오기 때문이다(공식 계약,
get_stock_list/test_client_stocklist.py와 동일 계약). 아래 목은 전부 이
튜플 모양을 흉내낸다.
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


def _page(body: dict, cont_yn: str = "N", next_key: str = "") -> tuple[dict, dict]:
    """`_request(with_continuation=True)`가 돌려주는 (응답, 연속조회정보) 모양."""
    return body, {"cont_yn": cont_yn, "next_key": next_key}


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
            m.return_value = _page({"return_code": 0, "dt_rlzt_pl": []})
            await client.get_realized_pnl(strt_dt="20260701", end_dt="20260712")
        assert m.call_args.kwargs["api_id"] == "ka10074"
        assert m.call_args.kwargs["endpoint"] == "/api/dostk/acnt"
        assert m.call_args.kwargs["data"] == {"strt_dt": "20260701", "end_dt": "20260712"}
        assert m.call_args.kwargs["with_continuation"] is True

    @pytest.mark.asyncio
    async def test_defaults_to_today_kst(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = _page({"return_code": 0, "dt_rlzt_pl": []})
            await client.get_realized_pnl()
        today = datetime.now(KST).strftime("%Y%m%d")
        assert m.call_args.kwargs["data"] == {"strt_dt": today, "end_dt": today}

    @pytest.mark.asyncio
    async def test_parses_totals_with_sign_preserved(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = _page(KA10074_RESPONSE)
            pnl = await client.get_realized_pnl()
        assert pnl.realized_pnl == -100000   # 손실이 음수로 보존
        assert pnl.total_buy_amount == 7000000
        assert pnl.total_sell_amount == 6900000
        assert pnl.commission == 3500
        assert pnl.tax == 12420

    @pytest.mark.asyncio
    async def test_parses_daily_rows(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = _page(KA10074_RESPONSE)
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
            m.return_value = _page({"return_code": 0})
            pnl = await client.get_realized_pnl()
        assert pnl.realized_pnl == 0
        assert pnl.daily == []


class TestRealizedPnlPagination:
    """계좌.md:296-312의 cont-yn/next-key 연속조회 계약.

    1페이지만 읽으면 조회 기간의 손익 발생 일수가 페이지 크기를 넘는
    순간부터 dt_rlzt_pl이 조용히 잘린다 — 에러도 표시도 없이 누적
    실현손익이 실제보다 작게 나온다(발굴 유니버스가 유량제한 오분류로
    조용히 축소됐던 사고와 같은 형태). get_stock_list의 페이지네이션
    루프(client.py, ka10099)와 동일 패턴을 검증한다.
    """

    @pytest.mark.asyncio
    async def test_two_page_response_is_fully_aggregated(self, client):
        page1 = {
            "return_code": 0,
            "tot_buy_amt": "14000000",
            "tot_sell_amt": "13800000",
            "rlzt_pl": "-200000",
            "trde_cmsn": "7000",
            "trde_tax": "24840",
            "dt_rlzt_pl": [
                {
                    "dt": "20260710", "buy_amt": "7000000", "sell_amt": "6900000",
                    "tdy_sel_pl": "-100000", "tdy_trde_cmsn": "3500", "tdy_trde_tax": "12420",
                },
            ],
        }
        page2 = {
            "return_code": 0,
            "tot_buy_amt": "14000000",
            "tot_sell_amt": "13800000",
            "rlzt_pl": "-200000",
            "trde_cmsn": "7000",
            "trde_tax": "24840",
            "dt_rlzt_pl": [
                {
                    "dt": "20260712", "buy_amt": "7000000", "sell_amt": "6900000",
                    "tdy_sel_pl": "-100000", "tdy_trde_cmsn": "3500", "tdy_trde_tax": "12420",
                },
            ],
        }
        with patch.object(client, "_request", new_callable=AsyncMock) as m, patch(
            "services.kiwoom.client.asyncio.sleep", new_callable=AsyncMock
        ):
            m.side_effect = [
                _page(page1, cont_yn="Y", next_key="NEXT1"),
                _page(page2, cont_yn="N", next_key=""),
            ]
            pnl = await client.get_realized_pnl(strt_dt="20260701", end_dt="20260712")

        # 두 페이지의 dt_rlzt_pl이 모두 합쳐져야 한다 — 1페이지만 읽으면
        # 20260712 행이 조용히 빠진다.
        assert [d.dt for d in pnl.daily] == ["20260710", "20260712"]
        assert sum(d.sell_pnl for d in pnl.daily) == -200000
        # 합계 필드는 이미 전체 기간 기준으로 응답에 채워지므로 마지막
        # 페이지 값을 그대로 쓴다(페이지별로 다시 합산하지 않는다).
        assert pnl.realized_pnl == -200000
        assert pnl.total_buy_amount == 14000000

        assert m.await_count == 2
        first_kwargs = m.await_args_list[0].kwargs
        assert first_kwargs["cont_yn"] == ""
        assert first_kwargs["next_key"] == ""
        second_kwargs = m.await_args_list[1].kwargs
        assert second_kwargs["cont_yn"] == "Y"
        assert second_kwargs["next_key"] == "NEXT1"
        assert second_kwargs["with_continuation"] is True

    @pytest.mark.asyncio
    async def test_three_page_response_is_fully_aggregated(self, client):
        """2페이지보다 더 깊은 연속조회도 끝까지 따라간다(회귀: 첫 Y만
        보고 멈추는 구현 방지)."""
        pages = [
            _page(
                {"return_code": 0, "dt_rlzt_pl": [{"dt": "20260710", "tdy_sel_pl": "1"}]},
                cont_yn="Y", next_key="N1",
            ),
            _page(
                {"return_code": 0, "dt_rlzt_pl": [{"dt": "20260711", "tdy_sel_pl": "2"}]},
                cont_yn="Y", next_key="N2",
            ),
            _page(
                {"return_code": 0, "dt_rlzt_pl": [{"dt": "20260712", "tdy_sel_pl": "3"}]},
                cont_yn="N", next_key="",
            ),
        ]
        with patch.object(client, "_request", new_callable=AsyncMock) as m, patch(
            "services.kiwoom.client.asyncio.sleep", new_callable=AsyncMock
        ):
            m.side_effect = pages
            pnl = await client.get_realized_pnl(strt_dt="20260701", end_dt="20260712")

        assert [d.dt for d in pnl.daily] == ["20260710", "20260711", "20260712"]
        assert m.await_count == 3

    @pytest.mark.asyncio
    async def test_single_page_response_does_not_loop(self, client):
        """cont-yn=N인 단일 페이지 응답은 한 번만 호출한다 — 대부분의
        콜사이트(/performance 30일 창 등)가 여기 해당하며, 불필요한
        추가 브로커 호출로 레이트리밋을 소모하지 않는다."""
        with patch.object(client, "_request", new_callable=AsyncMock) as m:
            m.return_value = _page({"return_code": 0, "dt_rlzt_pl": []})
            await client.get_realized_pnl(strt_dt="20260701", end_dt="20260701")
        assert m.await_count == 1
