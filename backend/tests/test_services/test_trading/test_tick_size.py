"""
Tests for KRX tick size (호가 단위) functions.

Tests the tick size calculation and price rounding based on KRX regulations.
"""

import pytest

from services.trading.market_hours import (
    get_krx_tick_size,
    round_to_tick_size,
    is_valid_tick_price,
    get_price_with_slippage,
    get_tick_info,
    KRX_TICK_SIZE_TABLE,
)


class TestGetKrxTickSize:
    """Tests for get_krx_tick_size function."""

    def test_price_below_1000(self):
        """Test tick size for prices below 1,000 KRW."""
        assert get_krx_tick_size(500) == 1
        assert get_krx_tick_size(999) == 1
        assert get_krx_tick_size(1) == 1

    def test_price_1000_to_5000(self):
        """Test tick size for prices 1,000 ~ 5,000 KRW."""
        assert get_krx_tick_size(1000) == 5
        assert get_krx_tick_size(3000) == 5
        assert get_krx_tick_size(4999) == 5

    def test_price_5000_to_10000(self):
        """Test tick size for prices 5,000 ~ 10,000 KRW."""
        assert get_krx_tick_size(5000) == 10
        assert get_krx_tick_size(8000) == 10
        assert get_krx_tick_size(9999) == 10

    def test_price_10000_to_50000(self):
        """Test tick size for prices 10,000 ~ 50,000 KRW."""
        assert get_krx_tick_size(10000) == 50
        assert get_krx_tick_size(30000) == 50
        assert get_krx_tick_size(49999) == 50

    def test_price_50000_to_100000(self):
        """Test tick size for prices 50,000 ~ 100,000 KRW."""
        assert get_krx_tick_size(50000) == 100
        assert get_krx_tick_size(80000) == 100
        assert get_krx_tick_size(99999) == 100

    def test_price_100000_to_500000(self):
        """Test tick size for prices 100,000 ~ 500,000 KRW."""
        assert get_krx_tick_size(100000) == 500
        assert get_krx_tick_size(200000) == 500
        assert get_krx_tick_size(499999) == 500

    def test_price_500000_and_above(self):
        """Test tick size for prices 500,000 KRW and above."""
        assert get_krx_tick_size(500000) == 1000
        assert get_krx_tick_size(1000000) == 1000
        assert get_krx_tick_size(5000000) == 1000

    def test_negative_price_raises_error(self):
        """Test that negative price raises ValueError."""
        with pytest.raises(ValueError, match="cannot be negative"):
            get_krx_tick_size(-1000)


class TestRoundToTickSize:
    """Tests for round_to_tick_size function."""

    def test_round_nearest(self):
        """Test rounding to nearest tick size."""
        assert round_to_tick_size(33333, "nearest") == 33350
        assert round_to_tick_size(33324, "nearest") == 33300
        assert round_to_tick_size(33350, "nearest") == 33350

    def test_round_up(self):
        """Test rounding up to next tick size."""
        assert round_to_tick_size(33333, "up") == 33350
        assert round_to_tick_size(33301, "up") == 33350
        assert round_to_tick_size(33350, "up") == 33350  # Already valid

    def test_round_down(self):
        """Test rounding down to previous tick size."""
        assert round_to_tick_size(33333, "down") == 33300
        assert round_to_tick_size(33349, "down") == 33300
        assert round_to_tick_size(33350, "down") == 33350  # Already valid

    def test_round_in_different_price_ranges(self):
        """Test rounding works correctly across price ranges."""
        # Below 1,000
        assert round_to_tick_size(555, "nearest") == 555

        # 1,000 ~ 5,000
        assert round_to_tick_size(2503, "nearest") == 2505
        assert round_to_tick_size(2502, "nearest") == 2500

        # 5,000 ~ 10,000
        assert round_to_tick_size(7777, "nearest") == 7780

        # 50,000 ~ 100,000
        assert round_to_tick_size(55555, "up") == 55600
        assert round_to_tick_size(55555, "down") == 55500

        # 100,000 ~ 500,000
        assert round_to_tick_size(155000, "nearest") == 155000
        assert round_to_tick_size(155333, "nearest") == 155500

        # 500,000+
        assert round_to_tick_size(555555, "nearest") == 556000

    def test_negative_price_raises_error(self):
        """Test that negative price raises ValueError."""
        with pytest.raises(ValueError, match="cannot be negative"):
            round_to_tick_size(-1000, "nearest")


class TestIsValidTickPrice:
    """Tests for is_valid_tick_price function."""

    def test_valid_prices(self):
        """Test that valid tick prices return True."""
        assert is_valid_tick_price(555) is True  # 1원 단위
        assert is_valid_tick_price(2505) is True  # 5원 단위
        assert is_valid_tick_price(7770) is True  # 10원 단위
        assert is_valid_tick_price(33350) is True  # 50원 단위
        assert is_valid_tick_price(55600) is True  # 100원 단위
        assert is_valid_tick_price(155500) is True  # 500원 단위
        assert is_valid_tick_price(556000) is True  # 1000원 단위

    def test_invalid_prices(self):
        """Test that invalid tick prices return False."""
        assert is_valid_tick_price(2503) is False  # Not divisible by 5
        assert is_valid_tick_price(7777) is False  # Not divisible by 10
        assert is_valid_tick_price(33333) is False  # Not divisible by 50
        assert is_valid_tick_price(55555) is False  # Not divisible by 100
        assert is_valid_tick_price(155333) is False  # Not divisible by 500
        assert is_valid_tick_price(555555) is False  # Not divisible by 1000

    def test_negative_price_returns_false(self):
        """Test that negative price returns False."""
        assert is_valid_tick_price(-1000) is False


class TestGetPriceWithSlippage:
    """Tests for get_price_with_slippage function."""

    def test_buy_with_slippage(self):
        """Test buy order slippage calculation."""
        # 50,000 * 1.005 = 50,250 -> rounded up to valid tick
        result = get_price_with_slippage(50000, 0.5, "buy")
        assert result == 50300  # 100원 단위로 올림

        # 100,000 * 1.01 = 101,000 -> valid 500원 단위
        result = get_price_with_slippage(100000, 1.0, "buy")
        assert result == 101000  # Already valid

    def test_sell_with_slippage(self):
        """Test sell order slippage calculation."""
        # 50,000 * 0.995 = 49,750 -> at 49,750 tick size is 50 (10,000~50,000 range)
        result = get_price_with_slippage(50000, 0.5, "sell")
        assert result == 49750  # 49,750 is valid at 50원 단위

        # 100,000 * 0.99 = 99,000 -> 100원 단위 (50,000~100,000 range)
        result = get_price_with_slippage(100000, 1.0, "sell")
        assert result == 99000  # Valid 100원 단위

    def test_zero_slippage(self):
        """Test with zero slippage."""
        result = get_price_with_slippage(50000, 0, "buy")
        assert result == 50000

        result = get_price_with_slippage(50000, 0, "sell")
        assert result == 50000


class TestGetTickInfo:
    """Tests for get_tick_info function."""

    def test_get_tick_info_basic(self):
        """Test basic tick info retrieval."""
        info = get_tick_info(33350)

        assert info["tick_size"] == 50
        assert info["is_valid"] is True
        assert info["price_range"] == "10,000원 ~ 50,000원 미만"
        assert info["rounded_price"] == 33350

    def test_get_tick_info_invalid_price(self):
        """Test tick info for invalid price."""
        info = get_tick_info(33333)

        assert info["tick_size"] == 50
        assert info["is_valid"] is False
        assert info["rounded_price"] == 33350
        assert info["next_up"] == 33350
        assert info["next_down"] == 33300

    def test_get_tick_info_high_price(self):
        """Test tick info for high price."""
        info = get_tick_info(600000)

        assert info["tick_size"] == 1000
        assert info["price_range"] == "500,000원 이상"

    def test_get_tick_info_low_price(self):
        """Test tick info for low price."""
        info = get_tick_info(500)

        assert info["tick_size"] == 1
        assert info["price_range"] == "1,000원 미만"


class TestTickSizeTable:
    """Tests for KRX_TICK_SIZE_TABLE structure."""

    def test_table_structure(self):
        """Test that the table is properly structured."""
        assert len(KRX_TICK_SIZE_TABLE) == 7

        # Check each entry has (max_price, tick_size)
        for entry in KRX_TICK_SIZE_TABLE:
            assert len(entry) == 2
            max_price, tick_size = entry
            assert isinstance(tick_size, int)

    def test_table_boundaries(self):
        """Test boundary prices match expected tick sizes."""
        # Test at exact boundaries
        assert get_krx_tick_size(999) == 1
        assert get_krx_tick_size(1000) == 5
        assert get_krx_tick_size(4999) == 5
        assert get_krx_tick_size(5000) == 10
        assert get_krx_tick_size(9999) == 10
        assert get_krx_tick_size(10000) == 50
        assert get_krx_tick_size(49999) == 50
        assert get_krx_tick_size(50000) == 100
        assert get_krx_tick_size(99999) == 100
        assert get_krx_tick_size(100000) == 500
        assert get_krx_tick_size(499999) == 500
        assert get_krx_tick_size(500000) == 1000
