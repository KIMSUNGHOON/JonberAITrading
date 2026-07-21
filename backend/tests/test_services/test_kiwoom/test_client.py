"""
Kiwoom Client Unit Tests

Tests for KiwoomClient with mocked HTTP responses.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pandas as pd
import pytest

from services.kiwoom.client import KiwoomClient
from services.kiwoom.errors import KiwoomError, KiwoomNetworkError
from services.kiwoom.models import Exchange, OrderType


class TestKiwoomClientParsers:
    """Test static parser methods"""

    def test_parse_signed_price_positive(self):
        assert KiwoomClient._parse_signed_price("+55000") == 55000

    def test_parse_signed_price_negative(self):
        assert KiwoomClient._parse_signed_price("-55000") == 55000

    def test_parse_signed_price_no_sign(self):
        assert KiwoomClient._parse_signed_price("55000") == 55000

    def test_parse_signed_price_with_comma(self):
        assert KiwoomClient._parse_signed_price("+55,000") == 55000

    def test_parse_signed_price_int(self):
        assert KiwoomClient._parse_signed_price(55000) == 55000

    def test_parse_signed_price_negative_int(self):
        assert KiwoomClient._parse_signed_price(-55000) == 55000

    def test_parse_signed_price_none(self):
        assert KiwoomClient._parse_signed_price(None) == 0

    def test_parse_signed_price_empty(self):
        assert KiwoomClient._parse_signed_price("") == 0

    def test_parse_signed_price_zero(self):
        assert KiwoomClient._parse_signed_price("0") == 0

    def test_parse_change_positive(self):
        assert KiwoomClient._parse_change("+500") == 500

    def test_parse_change_negative(self):
        assert KiwoomClient._parse_change("-500") == -500

    def test_parse_change_int(self):
        assert KiwoomClient._parse_change(500) == 500

    def test_parse_change_none(self):
        assert KiwoomClient._parse_change(None) == 0

    def test_parse_float_string(self):
        assert KiwoomClient._parse_float("3.14") == 3.14

    def test_parse_float_with_sign(self):
        assert KiwoomClient._parse_float("+3.14") == 3.14

    def test_parse_float_int(self):
        assert KiwoomClient._parse_float(3) == 3.0

    def test_parse_float_none(self):
        assert KiwoomClient._parse_float(None) == 0.0

    def test_parse_float_empty(self):
        assert KiwoomClient._parse_float("") == 0.0

    # --- _parse_float: Kiwoom 부호 규약 (--N=음수 이중부호) ---
    def test_parse_float_double_minus_is_negative(self):
        assert KiwoomClient._parse_float("--35") == -35.0
        assert KiwoomClient._parse_float("--3206") == -3206.0

    def test_parse_float_single_plus_stripped(self):
        assert KiwoomClient._parse_float("+122068") == 122068.0

    def test_parse_float_single_minus_kept(self):
        assert KiwoomClient._parse_float("-2") == -2.0
        assert KiwoomClient._parse_float("-1.22") == -1.22

    def test_parse_float_plus_decimal(self):
        assert KiwoomClient._parse_float("+2.50") == 2.5

    def test_parse_float_plain_and_comma(self):
        assert KiwoomClient._parse_float("123") == 123.0
        assert KiwoomClient._parse_float("+55,000") == 55000.0

    def test_parse_float_none_empty_lone_sign(self):
        assert KiwoomClient._parse_float(None) == 0.0
        assert KiwoomClient._parse_float("") == 0.0
        assert KiwoomClient._parse_float("-") == 0.0

    def test_parse_float_numeric_passthrough(self):
        assert KiwoomClient._parse_float(55000) == 55000.0
        assert KiwoomClient._parse_float(-55000) == -55000.0


class TestKiwoomClientInit:
    """Test client initialization"""

    def test_init_mock_mode(self):
        client = KiwoomClient(
            app_key="test_key",
            secret_key="test_secret",
            is_mock=True
        )
        assert client.is_mock is True
        assert client.base_url == "https://mockapi.kiwoom.com"

    def test_init_live_mode(self):
        client = KiwoomClient(
            app_key="test_key",
            secret_key="test_secret",
            is_mock=False
        )
        assert client.is_mock is False
        assert client.base_url == "https://api.kiwoom.com"


class TestKiwoomClientStockInfo:
    """Test get_stock_info method"""

    @pytest.fixture
    def client(self):
        return KiwoomClient(
            app_key="test_key",
            secret_key="test_secret",
            is_mock=True
        )

    @pytest.fixture
    def mock_stock_response(self):
        return {
            "return_code": 0,
            "output": {
                "stk_cd": "005930",
                "stk_nm": "삼성전자",
                "cur_prc": "-55000",
                "pred_pre": "-500",
                "flu_rt": "-0.90",
                "trde_qty": "10000000",
                "open_pric": "-54500",
                "high_pric": "-55500",
                "low_pric": "-54000",
                "upl_pric": "71500",
                "lst_pric": "38500"
            }
        }

    @pytest.mark.asyncio
    async def test_get_stock_info_success(self, client, mock_stock_response):
        """Test successful stock info retrieval"""
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_stock_response

            info = await client.get_stock_info("005930")

            assert info.stk_cd == "005930"
            assert info.stk_nm == "삼성전자"
            assert info.cur_prc == 55000
            assert info.prdy_vrss == -500
            assert info.prdy_ctrt == -0.90

    @pytest.mark.asyncio
    async def test_get_stock_info_output_as_list(self, client):
        """Test stock info with output as list"""
        response = {
            "return_code": 0,
            "output": [{
                "stk_cd": "005930",
                "stk_nm": "삼성전자",
                "cur_prc": "55000"
            }]
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            info = await client.get_stock_info("005930")

            assert info.stk_cd == "005930"

    @pytest.mark.asyncio
    async def test_get_stock_info_passes_explicit_ttl_to_cache(
        self, client, mock_stock_response
    ):
        """Dynamic held-position TTL (monitoring-cadence-tuning arc): when a
        caller passes `ttl=`, it must be forwarded to `cache.set` so held
        lookups can use a TTL derived from `compute_held_ttl(N)` instead of
        the hardcoded 3.0s `stock_info` prefix default."""
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request, \
                patch.object(client._cache, 'set') as mock_cache_set:
            mock_request.return_value = mock_stock_response

            await client.get_stock_info("005930", ttl=7.0)

            assert mock_cache_set.call_args.kwargs.get("ttl") == 7.0

    @pytest.mark.asyncio
    async def test_get_stock_info_no_ttl_keeps_prefix_default(
        self, client, mock_stock_response
    ):
        """Regression guard: a caller passing NO ttl must behave exactly as
        before — `cache.set` still receives `ttl=None` so the cache falls
        back to the `stock_info` prefix default (3.0s)."""
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request, \
                patch.object(client._cache, 'set') as mock_cache_set:
            mock_request.return_value = mock_stock_response

            await client.get_stock_info("005930")

            assert mock_cache_set.call_args.kwargs.get("ttl") is None


class TestKiwoomClientOrderbook:
    """Test get_orderbook method"""

    @pytest.fixture
    def client(self):
        return KiwoomClient(
            app_key="test_key",
            secret_key="test_secret",
            is_mock=True
        )

    @pytest.mark.asyncio
    async def test_get_orderbook_success(self, client):
        """Test successful orderbook retrieval (공식 스펙 키 — 시세.md ka10004)"""
        response = {
            "return_code": 0,
            "output": {
                "sel_fpr_bid": "55100",
                "sel_fpr_req": "1000",
                "sel_2th_pre_bid": "55200",
                "sel_2th_pre_req": "2000",
                "buy_fpr_bid": "55000",
                "buy_fpr_req": "1500",
                "buy_2th_pre_bid": "54900",
                "buy_2th_pre_req": "2500",
                "tot_sel_req": "50000",
                "tot_buy_req": "60000"
            }
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            orderbook = await client.get_orderbook("005930")

            assert orderbook.stk_cd == "005930"
            assert len(orderbook.sell_hogas) == 2
            assert len(orderbook.buy_hogas) == 2
            assert orderbook.sell_hogas[0].price == 55100
            assert orderbook.buy_hogas[0].price == 55000


class TestKiwoomClientDailyChart:
    """Test get_daily_chart method"""

    @pytest.fixture
    def client(self):
        return KiwoomClient(
            app_key="test_key",
            secret_key="test_secret",
            is_mock=True
        )

    @pytest.fixture
    def mock_chart_response(self):
        return {
            "return_code": 0,
            "stk_cd": "005930",
            "stk_dt_pole_chart_qry": [
                {
                    "dt": "20241220",
                    "open_pric": "-54500",
                    "high_pric": "-55500",
                    "low_pric": "-54000",
                    "cur_prc": "-55000",
                    "trde_qty": "10000000"
                },
                {
                    "dt": "20241219",
                    "open_pric": "-54000",
                    "high_pric": "-55000",
                    "low_pric": "-53500",
                    "cur_prc": "-54500",
                    "trde_qty": "8000000"
                }
            ]
        }

    @pytest.mark.asyncio
    async def test_get_daily_chart_success(self, client, mock_chart_response):
        """Test successful daily chart retrieval"""
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_chart_response

            charts = await client.get_daily_chart("005930")

            assert len(charts) == 2
            assert charts[0].dt == "20241220"
            assert charts[0].clos_prc == 55000
            assert charts[1].dt == "20241219"

    @pytest.mark.asyncio
    async def test_get_daily_chart_empty_response(self, client):
        """Test daily chart with empty response"""
        response = {
            "return_code": 0,
            "stk_cd": "005930",
            "stk_dt_pole_chart_qry": []
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            charts = await client.get_daily_chart("005930")

            assert len(charts) == 0

    @pytest.mark.asyncio
    async def test_get_daily_chart_df(self, client, mock_chart_response):
        """Test get_daily_chart_df returns DataFrame"""
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_chart_response

            df = await client.get_daily_chart_df("005930")

            assert isinstance(df, pd.DataFrame)
            assert len(df) == 2
            assert "date" in df.columns
            assert "open" in df.columns
            assert "close" in df.columns

    @pytest.mark.asyncio
    async def test_get_daily_chart_df_empty(self, client):
        """Test get_daily_chart_df with empty data"""
        response = {
            "return_code": 0,
            "stk_cd": "005930",
            "stk_dt_pole_chart_qry": []
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            df = await client.get_daily_chart_df("005930")

            assert isinstance(df, pd.DataFrame)
            assert len(df) == 0


class TestKiwoomClientAccountBalance:
    """Test account balance methods"""

    @pytest.fixture
    def client(self):
        return KiwoomClient(
            app_key="test_key",
            secret_key="test_secret",
            is_mock=True
        )

    @pytest.mark.asyncio
    async def test_get_cash_balance(self, client):
        """Test get_cash_balance"""
        # 실제 API 응답 필드명 사용 (문서와 실제 응답이 다름)
        response = {
            "return_code": 0,
            "entr": 10000000,              # 예수금 (dnca_tot_amt)
            "ord_alow_amt": 9000000,       # 주문가능금액 (ord_psbl_amt)
            "pymn_alow_amt": 8000000,      # 출금가능금액 (sttl_psbk_amt)
            "d1_pymn_alow_amt": 9500000,   # D+1 출금가능금액
            "d2_pymn_alow_amt": 9000000    # D+2 출금가능금액
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            cash = await client.get_cash_balance()

            assert cash.dnca_tot_amt == 10000000
            assert cash.ord_psbl_amt == 9000000

    @pytest.mark.asyncio
    async def test_get_account_balance(self, client):
        """Test get_account_balance (공식 스펙 키 — 계좌.md kt00004)"""
        response = {
            "return_code": 0,
            "tot_pur_amt": "10000000",     # 총매입금액 (pchs_amt)
            "tot_est_amt": "11000000",     # 유가잔고평가액 (evlu_amt)
            "d2_entra": "5000000",         # D+2 추정예수금 (d2_ord_psbl_amt)
            "stk_acnt_evlt_prst": [
                {
                    "stk_cd": "A005930",
                    "stk_nm": "삼성전자",
                    "rmnd_qty": "100",
                    "avg_prc": "50000",
                    "cur_prc": "55000",
                    "evlt_amt": "5500000",
                    "pl_amt": "500000",
                    "pl_rt": "10.0"
                }
            ]
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            balance = await client.get_account_balance()

            assert balance.pchs_amt == 10000000
            assert balance.evlu_amt == 11000000
            assert balance.evlu_pfls_amt == 1000000  # 평가 - 매입
            assert len(balance.holdings) == 1
            assert balance.holdings[0].stk_cd == "005930"  # A 접두사 스트립
            assert balance.holdings[0].hldg_qty == 100
            assert balance.holdings[0].avg_buy_prc == 50000

    @pytest.mark.asyncio
    async def test_get_account_balance_fresh_fetch_bypasses_stored_snapshot(self, client):
        """use_cache=False는 30s TTL 스냅샷을 우회해 재조회한다 —
        get_filled_orders와 동일 패턴 (F3 t6 리뷰 M1: 리컨실러는 체결 폴
        직후의 최신 잔고를 봐야 하며, 스테일 스냅샷은 방금 등록된 포지션을
        '외부 매도'로 오판해 제거한다)."""
        response = {
            "return_code": 0,
            "tot_pur_amt": "10000000",
            "tot_est_amt": "11000000",
            "d2_entra": "5000000",
            "stk_acnt_evlt_prst": [],
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            await client.get_account_balance()  # 스냅샷 저장
            assert mock_request.call_count == 1

            await client.get_account_balance()  # 기본값: 저장분 반환, 재조회 없음
            assert mock_request.call_count == 1

            await client.get_account_balance(use_cache=False)  # 리컨실러 경로: 재조회
            assert mock_request.call_count == 2


class TestKiwoomClientOrders:
    """Test order methods"""

    @pytest.fixture
    def client(self):
        return KiwoomClient(
            app_key="test_key",
            secret_key="test_secret",
            is_mock=True
        )

    @pytest.mark.asyncio
    async def test_get_pending_orders(self, client):
        """Test get_pending_orders (공식 스펙 키 — 계좌.md ka10075, 리스트 키 oso)"""
        response = {
            "return_code": 0,
            "oso": [
                {
                    "ord_no": "123456",
                    "stk_cd": "A005930",
                    "stk_nm": "삼성전자",
                    "ord_qty": "100",
                    "ord_pric": "55000",
                    "cntr_qty": "50",
                    "oso_qty": "50",
                    "tm": "143000",
                    "trde_tp": "2",
                    "io_tp_nm": "+매수"
                }
            ]
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            orders = await client.get_pending_orders()

            assert len(orders) == 1
            assert orders[0].ord_no == "123456"
            assert orders[0].ord_uv == 55000
            assert orders[0].rmn_qty == 50
            assert orders[0].buy_sell_tp == "1"  # 소비자 계약: 1=매수

    @pytest.mark.asyncio
    async def test_get_filled_orders(self, client):
        """Test get_filled_orders (공식 스펙 키 — 계좌.md ka10076, 리스트 키 cntr)"""
        response = {
            "return_code": 0,
            "cntr": [
                {
                    "ord_no": "123456",
                    "stk_cd": "A005930",
                    "stk_nm": "삼성전자",
                    "cntr_qty": "100",
                    "cntr_pric": "55000",
                    "ord_tm": "143000",
                    "io_tp_nm": "+매수"
                }
            ]
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            orders = await client.get_filled_orders()

            assert len(orders) == 1
            assert orders[0].ccld_amt == 5500000  # cntr_qty * cntr_pric
            assert orders[0].buy_sell_tp == "1"

    @pytest.mark.asyncio
    async def test_place_buy_order(self, client):
        """Test place_buy_order"""
        response = {
            "return_code": 0,
            "ord_no": "123456",
            "dmst_stex_tp": "KRX",
            "return_msg": "정상처리"
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            result = await client.place_buy_order(
                stk_cd="005930",
                qty=10,
                price=55000,
                order_type=OrderType.LIMIT
            )

            assert result.is_success is True
            assert result.ord_no == "123456"

    @pytest.mark.asyncio
    async def test_place_sell_order(self, client):
        """Test place_sell_order"""
        response = {
            "return_code": 0,
            "ord_no": "654321",
            "dmst_stex_tp": "KRX",
            "return_msg": "정상처리"
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            result = await client.place_sell_order(
                stk_cd="005930",
                qty=10,
                order_type=OrderType.MARKET
            )

            assert result.is_success is True
            assert result.ord_no == "654321"

    @pytest.mark.asyncio
    async def test_modify_order(self, client):
        """Test modify_order"""
        response = {
            "return_code": 0,
            "ord_no": "789012",
            "dmst_stex_tp": "KRX",
            "return_msg": "정정처리"
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            result = await client.modify_order(
                org_ord_no="123456",
                stk_cd="005930",
                qty=10,
                price=54000
            )

            assert result.is_success is True
            assert result.ord_no == "789012"

    @pytest.mark.asyncio
    async def test_cancel_order(self, client):
        """Test cancel_order"""
        response = {
            "return_code": 0,
            "ord_no": "999999",
            "dmst_stex_tp": "KRX",
            "return_msg": "취소처리"
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            result = await client.cancel_order(
                org_ord_no="123456",
                stk_cd="005930",
                qty=10
            )

            assert result.is_success is True


class TestKiwoomClientConvenienceMethods:
    """Test convenience methods"""

    @pytest.fixture
    def client(self):
        return KiwoomClient(
            app_key="test_key",
            secret_key="test_secret",
            is_mock=True
        )

    @pytest.mark.asyncio
    async def test_get_current_price(self, client):
        """Test get_current_price"""
        response = {
            "return_code": 0,
            "output": {
                "stk_cd": "005930",
                "stk_nm": "삼성전자",
                "cur_prc": "-55000"
            }
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            price = await client.get_current_price("005930")

            assert price == 55000

    @pytest.mark.asyncio
    async def test_buy_market_order(self, client):
        """Test buy_market_order"""
        response = {
            "return_code": 0,
            "ord_no": "123456",
            "return_msg": "정상처리"
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            result = await client.buy_market_order("005930", 10)

            assert result.is_success is True

    @pytest.mark.asyncio
    async def test_sell_market_order(self, client):
        """Test sell_market_order"""
        response = {
            "return_code": 0,
            "ord_no": "654321",
            "return_msg": "정상처리"
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            result = await client.sell_market_order("005930", 10)

            assert result.is_success is True


class TestKiwoomClientRequest:
    """Test internal _request method"""

    @pytest.fixture
    def client(self):
        return KiwoomClient(
            app_key="test_key",
            secret_key="test_secret",
            is_mock=True
        )

    @pytest.mark.asyncio
    async def test_request_error_response(self, client):
        """Test _request with error response"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "return_code": -1,
            "return_msg": "API Error"
        }

        with patch.object(client.auth, 'get_token', new_callable=AsyncMock) as mock_token:
            mock_token.return_value = "test_token"

            with patch.object(client, '_get_client', new_callable=AsyncMock) as mock_get_client:
                mock_http = AsyncMock()
                mock_http.post.return_value = mock_response
                mock_get_client.return_value = mock_http

                with pytest.raises(KiwoomError):
                    await client._request(
                        api_id="ka10001",
                        endpoint="/api/dostk/stkinfo",
                        data={"stk_cd": "005930"}
                    )

    @pytest.mark.asyncio
    async def test_request_network_error(self, client):
        """Test _request with network error"""
        with patch.object(client.auth, 'get_token', new_callable=AsyncMock) as mock_token:
            mock_token.return_value = "test_token"

            with patch.object(client, '_get_client', new_callable=AsyncMock) as mock_get_client:
                mock_http = AsyncMock()
                mock_http.post.side_effect = httpx.HTTPError("Connection failed")
                mock_get_client.return_value = mock_http

                with pytest.raises(KiwoomNetworkError):
                    await client._request(
                        api_id="ka10001",
                        endpoint="/api/dostk/stkinfo",
                        data={"stk_cd": "005930"}
                    )


class TestKiwoomClientContextManager:
    """Test async context manager"""

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        """Test async with statement"""
        async with KiwoomClient(
            app_key="test_key",
            secret_key="test_secret",
            is_mock=True
        ) as client:
            assert client is not None
            assert client.is_mock is True