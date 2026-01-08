"""
Chart API Unit Tests

Tests for the Korean stock chart data fetching functionality.
Run with: pytest tests/test_chart_api.py -v
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from services.kiwoom.client import KiwoomClient
from services.kiwoom.models import ChartData


class TestKiwoomChartClient:
    """Test KiwoomClient.get_daily_chart method"""

    @pytest.fixture
    def client(self):
        return KiwoomClient(
            app_key="test_key",
            secret_key="test_secret",
            is_mock=True,
            enable_cache=False,
            enable_rate_limit=False,
        )

    @pytest.fixture
    def mock_chart_response(self):
        """
        Mock response format for ka10081 (주식일봉차트조회요청)

        Based on Kiwoom API documentation, the response should have:
        - stk_dt_pole_chart_qry: Array of daily candle data
        """
        return {
            "return_code": 0,
            "return_msg": "정상적으로 처리되었습니다",
            "stk_cd": "005930",
            "stk_dt_pole_chart_qry": [
                {
                    "dt": "20241227",
                    "open_pric": "+55000",
                    "high_pric": "+56000",
                    "low_pric": "+54500",
                    "cur_prc": "+55500",
                    "trde_qty": "15000000",
                    "trde_prica": "825000000000",
                },
                {
                    "dt": "20241226",
                    "open_pric": "+54000",
                    "high_pric": "+55500",
                    "low_pric": "+53500",
                    "cur_prc": "+55000",
                    "trde_qty": "12000000",
                    "trde_prica": "660000000000",
                },
                {
                    "dt": "20241224",
                    "open_pric": "+53500",
                    "high_pric": "+54500",
                    "low_pric": "+53000",
                    "cur_prc": "+54000",
                    "trde_qty": "10000000",
                    "trde_prica": "540000000000",
                },
            ],
        }

    @pytest.mark.asyncio
    async def test_get_daily_chart_success(self, client, mock_chart_response):
        """Test successful daily chart retrieval"""
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_chart_response

            chart_data = await client.get_daily_chart("005930")

            # Verify request was made correctly
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args.kwargs['api_id'] == "ka10081"
            assert call_args.kwargs['endpoint'] == "/api/dostk/chart"
            assert call_args.kwargs['data']['stk_cd'] == "005930"

            # Verify response parsing
            assert len(chart_data) == 3
            assert chart_data[0].dt == "20241227"
            assert chart_data[0].open_prc == 55000
            assert chart_data[0].high_prc == 56000
            assert chart_data[0].low_prc == 54500
            assert chart_data[0].clos_prc == 55500
            assert chart_data[0].acml_vol == 15000000

    @pytest.mark.asyncio
    async def test_get_daily_chart_empty_response(self, client):
        """Test handling of empty chart response"""
        response = {
            "return_code": 0,
            "stk_dt_pole_chart_qry": [],
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            chart_data = await client.get_daily_chart("005930")

            assert len(chart_data) == 0

    @pytest.mark.asyncio
    async def test_get_daily_chart_alternative_field_names(self, client):
        """Test handling of alternative field names in API response"""
        # Some API versions might use different field names
        response = {
            "return_code": 0,
            "output": [  # Alternative to stk_dt_pole_chart_qry
                {
                    "dt": "20241227",
                    "open_prc": "55000",  # Without sign prefix
                    "high_prc": "56000",
                    "low_prc": "54500",
                    "clos_prc": "55500",  # Alternative to cur_prc
                    "acml_vol": "15000000",  # Alternative to trde_qty
                },
            ],
        }

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response

            chart_data = await client.get_daily_chart("005930")

            assert len(chart_data) == 1
            assert chart_data[0].open_prc == 55000
            assert chart_data[0].clos_prc == 55500


class TestChartDataModel:
    """Test ChartData model"""

    def test_chart_data_creation(self):
        """Test ChartData model creation"""
        data = ChartData(
            stk_cd="005930",
            dt="20241227",
            open_prc=55000,
            high_prc=56000,
            low_prc=54500,
            clos_prc=55500,
            acml_vol=15000000,
            acml_tr_pbmn=825000000000,
        )

        assert data.stk_cd == "005930"
        assert data.dt == "20241227"
        assert data.open_prc == 55000
        assert data.high_prc == 56000
        assert data.low_prc == 54500
        assert data.clos_prc == 55500
        assert data.acml_vol == 15000000

    def test_chart_data_ohlcv_property(self):
        """Test ChartData.ohlcv property"""
        data = ChartData(
            stk_cd="005930",
            dt="20241227",
            open_prc=55000,
            high_prc=56000,
            low_prc=54500,
            clos_prc=55500,
            acml_vol=15000000,
        )

        ohlcv = data.ohlcv
        assert ohlcv["open"] == 55000
        assert ohlcv["high"] == 56000
        assert ohlcv["low"] == 54500
        assert ohlcv["close"] == 55500
        assert ohlcv["volume"] == 15000000


class TestChartAPIRoute:
    """Test the /api/kr_stocks/candles/{stk_cd} endpoint"""

    @pytest.mark.asyncio
    async def test_candles_endpoint_success(self):
        """Test successful candle endpoint response"""
        from app.api.routes.kr_stocks import get_candles, _generate_mock_candles
        from app.api.schemas.kr_stocks import KRStockCandlesResponse

        # Test mock candle generation
        result = _generate_mock_candles("005930", count=10)

        assert isinstance(result, KRStockCandlesResponse)
        assert result.stk_cd == "005930"
        assert len(result.candles) <= 10
        assert result.period == "D"

        # Verify candle data structure
        if result.candles:
            candle = result.candles[0]
            assert candle.stck_bsop_date  # Date should be set
            assert candle.stck_oprc > 0  # Open price
            assert candle.stck_hgpr > 0  # High price
            assert candle.stck_lwpr > 0  # Low price
            assert candle.stck_clpr > 0  # Close price
            assert candle.acml_vol > 0  # Volume

    @pytest.mark.asyncio
    async def test_candles_endpoint_invalid_stock_code(self):
        """Test candle endpoint with invalid stock code"""
        from fastapi import HTTPException
        from app.api.routes.kr_stocks import get_candles

        # Invalid stock code (not 6 digits)
        with pytest.raises(HTTPException) as exc_info:
            await get_candles("12345")  # 5 digits
        assert exc_info.value.status_code == 400

        with pytest.raises(HTTPException) as exc_info:
            await get_candles("AAPL")  # Not numeric
        assert exc_info.value.status_code == 400


class TestPriceParser:
    """Test price parsing utilities"""

    def test_parse_signed_price_positive(self):
        """Test parsing positive signed price"""
        assert KiwoomClient._parse_signed_price("+55000") == 55000

    def test_parse_signed_price_negative(self):
        """Test parsing negative signed price (absolute value)"""
        assert KiwoomClient._parse_signed_price("-55000") == 55000

    def test_parse_signed_price_no_sign(self):
        """Test parsing price without sign"""
        assert KiwoomClient._parse_signed_price("55000") == 55000

    def test_parse_signed_price_int_input(self):
        """Test parsing integer input"""
        assert KiwoomClient._parse_signed_price(55000) == 55000

    def test_parse_signed_price_none(self):
        """Test parsing None value"""
        assert KiwoomClient._parse_signed_price(None) == 0

    def test_parse_signed_price_empty_string(self):
        """Test parsing empty string"""
        assert KiwoomClient._parse_signed_price("") == 0


class TestLiveAPIIntegration:
    """
    Integration tests that call the actual Kiwoom API.

    These tests are skipped by default. To run them:
    1. Set KIWOOM_APP_KEY and KIWOOM_SECRET_KEY environment variables
    2. Run: pytest tests/test_chart_api.py -v -k "live" --run-live
    """

    @pytest.fixture
    def live_client(self):
        """Create a client with real credentials from environment"""
        import os

        app_key = os.environ.get("KIWOOM_APP_KEY")
        secret_key = os.environ.get("KIWOOM_SECRET_KEY")

        if not app_key or not secret_key:
            pytest.skip("KIWOOM_APP_KEY and KIWOOM_SECRET_KEY not set")

        return KiwoomClient(
            app_key=app_key,
            secret_key=secret_key,
            is_mock=True,  # Use mock API for safety
        )

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires live API credentials")
    async def test_live_get_daily_chart(self, live_client):
        """Test actual API call for daily chart data"""
        async with live_client:
            chart_data = await live_client.get_daily_chart("005930")

            print(f"\n=== Live API Response ===")
            print(f"Number of candles: {len(chart_data)}")
            if chart_data:
                print(f"First candle: {chart_data[0]}")
                print(f"Last candle: {chart_data[-1]}")

            assert len(chart_data) > 0
            assert chart_data[0].dt  # Should have date
            assert chart_data[0].clos_prc > 0  # Should have price


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v"])
