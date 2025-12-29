"""
Korean Encoding Tests

Tests to verify Korean text encoding is properly handled.
"""

import pytest

from services.kiwoom.models import (
    POPULAR_KR_TICKERS,
    FilledOrder,
    Holding,
    PendingOrder,
    StockBasicInfo,
)


class TestKoreanEncoding:
    """Test Korean text encoding in models"""

    def test_stock_basic_info_korean_name(self):
        """Test StockBasicInfo with Korean stock name"""
        info = StockBasicInfo(
            stk_cd="005930",
            stk_nm="삼성전자",
            cur_prc=55000,
            prdy_vrss=500,
            prdy_ctrt=0.92
        )

        assert info.stk_nm == "삼성전자"
        assert len(info.stk_nm) == 4  # 4 Korean characters

    def test_stock_basic_info_korean_comparison(self):
        """Test Korean text comparison"""
        info = StockBasicInfo(
            stk_cd="005930",
            stk_nm="삼성전자",
            cur_prc=55000
        )

        expected_name = "삼성전자"
        assert info.stk_nm == expected_name

    def test_popular_tickers_korean(self):
        """Test POPULAR_KR_TICKERS contains valid Korean names"""
        # Test Samsung Electronics
        assert "005930" in POPULAR_KR_TICKERS
        assert POPULAR_KR_TICKERS["005930"] == "삼성전자"

        # Test SK Hynix
        assert "000660" in POPULAR_KR_TICKERS
        assert POPULAR_KR_TICKERS["000660"] == "SK하이닉스"

        # Test Kakao
        assert "035720" in POPULAR_KR_TICKERS
        assert POPULAR_KR_TICKERS["035720"] == "카카오"

        # Test NAVER
        assert "035420" in POPULAR_KR_TICKERS
        assert POPULAR_KR_TICKERS["035420"] == "NAVER"

    def test_holding_korean_name(self):
        """Test Holding model with Korean name"""
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

        assert holding.stk_nm == "삼성전자"

    def test_pending_order_korean_name(self):
        """Test PendingOrder with Korean name"""
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

        assert order.stk_nm == "삼성전자"

    def test_filled_order_korean_name(self):
        """Test FilledOrder with Korean name"""
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

        assert order.stk_nm == "삼성전자"

    def test_mixed_korean_english(self):
        """Test mixed Korean and English text"""
        info = StockBasicInfo(
            stk_cd="000660",
            stk_nm="SK하이닉스",
            cur_prc=150000
        )

        assert info.stk_nm == "SK하이닉스"
        assert "SK" in info.stk_nm
        assert "하이닉스" in info.stk_nm

    def test_korean_string_length(self):
        """Test Korean string length is correct"""
        # Korean characters should be counted as 1 character each
        name = "삼성전자"
        assert len(name) == 4

        name2 = "SK하이닉스"
        assert len(name2) == 6  # S, K, 하, 이, 닉, 스

    def test_korean_json_serialization(self):
        """Test Korean text survives JSON serialization"""
        import json

        info = StockBasicInfo(
            stk_cd="005930",
            stk_nm="삼성전자",
            cur_prc=55000
        )

        # Serialize to JSON
        json_str = info.model_dump_json()

        # Deserialize back
        data = json.loads(json_str)

        assert data["stk_nm"] == "삼성전자"

    def test_korean_dict_serialization(self):
        """Test Korean text in dict serialization"""
        info = StockBasicInfo(
            stk_cd="005930",
            stk_nm="삼성전자",
            cur_prc=55000
        )

        # Convert to dict
        data = info.model_dump()

        assert data["stk_nm"] == "삼성전자"

    def test_korean_string_operations(self):
        """Test various string operations with Korean text"""
        name = "삼성전자"

        # startswith
        assert name.startswith("삼성")

        # endswith
        assert name.endswith("전자")

        # contains
        assert "성전" in name

        # upper/lower (Korean doesn't have case, should remain unchanged)
        assert name.upper() == name
        assert name.lower() == name

    def test_utf8_bytes(self):
        """Test UTF-8 byte representation"""
        name = "삼성전자"

        # Encode to UTF-8
        utf8_bytes = name.encode("utf-8")

        # Korean characters are 3 bytes each in UTF-8
        assert len(utf8_bytes) == 12  # 4 characters * 3 bytes

        # Decode back
        decoded = utf8_bytes.decode("utf-8")
        assert decoded == name