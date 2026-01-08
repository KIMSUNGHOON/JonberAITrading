"""
Kiwoom Models Unit Tests

Tests for Pydantic models used in Kiwoom REST API.
"""

from datetime import datetime, timedelta

import pytest

from services.kiwoom.models import (
    AccountBalance,
    CashBalance,
    ChartData,
    Exchange,
    FilledOrder,
    Holding,
    KiwoomToken,
    Orderbook,
    OrderbookUnit,
    OrderRequest,
    OrderResponse,
    OrderType,
    PendingOrder,
    StockBasicInfo,
)


class TestOrderType:
    """OrderType enum tests"""

    def test_limit_order_value(self):
        assert OrderType.LIMIT.value == "0"

    def test_market_order_value(self):
        assert OrderType.MARKET.value == "3"

    def test_all_order_types_exist(self):
        expected_types = [
            "LIMIT", "MARKET", "CONDITIONAL", "BEST_LIMIT", "FIRST_LIMIT",
            "LIMIT_IOC", "MARKET_IOC", "BEST_IOC", "LIMIT_FOK", "MARKET_FOK",
            "BEST_FOK", "STOP_LIMIT", "MID_PRICE", "MID_IOC", "MID_FOK",
            "PRE_MARKET", "AFTER_SINGLE", "AFTER_MARKET"
        ]
        for type_name in expected_types:
            assert hasattr(OrderType, type_name)


class TestExchange:
    """Exchange enum tests"""

    def test_krx_exchange(self):
        assert Exchange.KRX.value == "KRX"

    def test_nxt_exchange(self):
        assert Exchange.NXT.value == "NXT"

    def test_sor_exchange(self):
        assert Exchange.SOR.value == "SOR"


class TestKiwoomToken:
    """KiwoomToken model tests"""

    def test_token_creation(self):
        expires = datetime.now() + timedelta(hours=24)
        token = KiwoomToken(
            token="test_token_123",
            token_type="Bearer",
            expires_dt=expires
        )
        assert token.token == "test_token_123"
        assert token.token_type == "Bearer"

    def test_token_not_expired(self):
        expires = datetime.now() + timedelta(hours=24)
        token = KiwoomToken(token="test", expires_dt=expires)
        assert token.is_expired is False

    def test_token_expired(self):
        expires = datetime.now() - timedelta(hours=1)
        token = KiwoomToken(token="test", expires_dt=expires)
        assert token.is_expired is True

    def test_authorization_header(self):
        token = KiwoomToken(
            token="abc123",
            token_type="Bearer",
            expires_dt=datetime.now() + timedelta(hours=1)
        )
        assert token.authorization_header == "Bearer abc123"


class TestStockBasicInfo:
    """StockBasicInfo model tests"""

    def test_stock_info_creation(self):
        info = StockBasicInfo(
            stk_cd="005930",
            stk_nm="삼성전자",
            cur_prc=55000,
            prdy_vrss=500,
            prdy_ctrt=0.92
        )
        assert info.stk_cd == "005930"
        assert info.stk_nm == "삼성전자"
        assert info.cur_prc == 55000

    def test_change_sign_positive(self):
        info = StockBasicInfo(
            stk_cd="005930",
            stk_nm="삼성전자",
            cur_prc=55000,
            prdy_vrss=500
        )
        assert info.change_sign == "+"

    def test_change_sign_negative(self):
        info = StockBasicInfo(
            stk_cd="005930",
            stk_nm="삼성전자",
            cur_prc=55000,
            prdy_vrss=-500
        )
        assert info.change_sign == "-"

    def test_change_sign_zero(self):
        info = StockBasicInfo(
            stk_cd="005930",
            stk_nm="삼성전자",
            cur_prc=55000,
            prdy_vrss=0
        )
        assert info.change_sign == ""


class TestOrderbook:
    """Orderbook model tests"""

    def test_orderbook_creation(self):
        sell_hogas = [OrderbookUnit(price=55100, quantity=100)]
        buy_hogas = [OrderbookUnit(price=55000, quantity=200)]

        orderbook = Orderbook(
            stk_cd="005930",
            sell_hogas=sell_hogas,
            buy_hogas=buy_hogas,
            tot_sell_qty=1000,
            tot_buy_qty=2000
        )

        assert orderbook.stk_cd == "005930"
        assert len(orderbook.sell_hogas) == 1
        assert len(orderbook.buy_hogas) == 1

    def test_spread_calculation(self):
        sell_hogas = [OrderbookUnit(price=55100, quantity=100)]
        buy_hogas = [OrderbookUnit(price=55000, quantity=200)]

        orderbook = Orderbook(
            stk_cd="005930",
            sell_hogas=sell_hogas,
            buy_hogas=buy_hogas
        )

        assert orderbook.spread == 100

    def test_bid_ask_ratio(self):
        orderbook = Orderbook(
            stk_cd="005930",
            tot_sell_qty=1000,
            tot_buy_qty=2000
        )

        assert orderbook.bid_ask_ratio == 2.0

    def test_bid_ask_ratio_zero_sell(self):
        orderbook = Orderbook(
            stk_cd="005930",
            tot_sell_qty=0,
            tot_buy_qty=2000
        )

        assert orderbook.bid_ask_ratio == 0.0


class TestChartData:
    """ChartData model tests"""

    def test_chart_data_creation(self):
        chart = ChartData(
            stk_cd="005930",
            dt="20241220",
            open_prc=55000,
            high_prc=56000,
            low_prc=54000,
            clos_prc=55500,
            acml_vol=1000000
        )

        assert chart.stk_cd == "005930"
        assert chart.dt == "20241220"
        assert chart.clos_prc == 55500

    def test_ohlcv_property(self):
        chart = ChartData(
            stk_cd="005930",
            dt="20241220",
            open_prc=55000,
            high_prc=56000,
            low_prc=54000,
            clos_prc=55500,
            acml_vol=1000000
        )

        ohlcv = chart.ohlcv
        assert ohlcv["open"] == 55000
        assert ohlcv["high"] == 56000
        assert ohlcv["low"] == 54000
        assert ohlcv["close"] == 55500
        assert ohlcv["volume"] == 1000000


class TestOrderRequest:
    """OrderRequest model tests"""

    def test_order_request_creation(self):
        request = OrderRequest(
            stk_cd="005930",
            ord_qty=10,
            ord_uv=55000,
            trde_tp=OrderType.LIMIT
        )

        assert request.stk_cd == "005930"
        assert request.ord_qty == 10
        assert request.ord_uv == 55000

    def test_to_api_dict(self):
        request = OrderRequest(
            dmst_stex_tp=Exchange.KRX,
            stk_cd="005930",
            ord_qty=10,
            ord_uv=55000,
            trde_tp=OrderType.LIMIT
        )

        api_dict = request.to_api_dict()
        assert api_dict["dmst_stex_tp"] == "KRX"
        assert api_dict["stk_cd"] == "005930"
        assert api_dict["ord_qty"] == "10"
        assert api_dict["ord_uv"] == "55000"
        assert api_dict["trde_tp"] == "0"

    def test_market_order_no_price(self):
        request = OrderRequest(
            stk_cd="005930",
            ord_qty=10,
            trde_tp=OrderType.MARKET
        )

        api_dict = request.to_api_dict()
        assert api_dict["ord_uv"] == ""


class TestOrderResponse:
    """OrderResponse model tests"""

    def test_order_response_success(self):
        response = OrderResponse(
            ord_no="123456",
            return_code=0,
            return_msg="정상처리"
        )

        assert response.is_success is True
        assert response.ord_no == "123456"

    def test_order_response_failure(self):
        response = OrderResponse(
            ord_no="",
            return_code=-1,
            return_msg="주문 실패"
        )

        assert response.is_success is False


class TestHolding:
    """Holding model tests"""

    def test_holding_creation(self):
        holding = Holding(
            stk_cd="005930",
            stk_nm="삼성전자",
            hldg_qty=100,
            avg_buy_prc=50000,
            cur_prc=55000,
            evlu_amt=5500000,
            evlu_pfls_amt=500000,
            evlu_pfls_rt=10.0
        )

        assert holding.stk_cd == "005930"
        assert holding.hldg_qty == 100

    def test_total_cost(self):
        holding = Holding(
            stk_cd="005930",
            stk_nm="삼성전자",
            hldg_qty=100,
            avg_buy_prc=50000,
            cur_prc=55000,
            evlu_amt=5500000,
            evlu_pfls_amt=500000,
            evlu_pfls_rt=10.0
        )

        assert holding.total_cost == 5000000


class TestAccountBalance:
    """AccountBalance model tests"""

    def test_account_balance_creation(self):
        balance = AccountBalance(
            pchs_amt=10000000,
            evlu_amt=11000000,
            evlu_pfls_amt=1000000,
            evlu_pfls_rt=10.0,
            d2_ord_psbl_amt=5000000
        )

        assert balance.pchs_amt == 10000000
        assert balance.evlu_amt == 11000000

    def test_total_value(self):
        balance = AccountBalance(
            evlu_amt=11000000,
            d2_ord_psbl_amt=5000000
        )

        assert balance.total_value == 16000000


class TestCashBalance:
    """CashBalance model tests"""

    def test_cash_balance_creation(self):
        cash = CashBalance(
            dnca_tot_amt=10000000,
            ord_psbl_amt=9000000,
            sttl_psbk_amt=8000000,
            d1_ord_psbl_amt=9500000,
            d2_ord_psbl_amt=9000000
        )

        assert cash.dnca_tot_amt == 10000000
        assert cash.ord_psbl_amt == 9000000


class TestPendingOrder:
    """PendingOrder model tests"""

    def test_pending_order_creation(self):
        order = PendingOrder(
            ord_no="123456",
            stk_cd="005930",
            stk_nm="삼성전자",
            ord_qty=100,
            ord_uv=55000,
            ccld_qty=50,
            rmn_qty=50,
            ord_dt="20241220",
            ord_tm="143000",
            buy_sell_tp="1"
        )

        assert order.ord_no == "123456"
        assert order.rmn_qty == 50

    def test_partial_filled(self):
        order = PendingOrder(
            ord_no="123456",
            stk_cd="005930",
            stk_nm="삼성전자",
            ord_qty=100,
            ord_uv=55000,
            ccld_qty=50,
            rmn_qty=50,
            ord_dt="20241220",
            ord_tm="143000",
            buy_sell_tp="1"
        )

        assert order.is_partial_filled is True

    def test_not_partial_filled(self):
        order = PendingOrder(
            ord_no="123456",
            stk_cd="005930",
            stk_nm="삼성전자",
            ord_qty=100,
            ord_uv=55000,
            ccld_qty=0,
            rmn_qty=100,
            ord_dt="20241220",
            ord_tm="143000",
            buy_sell_tp="1"
        )

        assert order.is_partial_filled is False


class TestFilledOrder:
    """FilledOrder model tests"""

    def test_filled_order_creation(self):
        order = FilledOrder(
            ord_no="123456",
            stk_cd="005930",
            stk_nm="삼성전자",
            ccld_qty=100,
            ccld_uv=55000,
            ccld_amt=5500000,
            ccld_dt="20241220",
            ccld_tm="143000",
            buy_sell_tp="1"
        )

        assert order.ord_no == "123456"
        assert order.ccld_amt == 5500000