"""CRITICAL safety fix (2026-07-14): kr_market_data.py must NEVER fabricate
random-mock prices/fundamentals/orderbook/chart data when the real Kiwoom
fetch fails. Before this fix, every one of these functions caught the
exception and silently returned `_get_mock_*`/`np.random`-generated data —
which then flowed straight into analysis, HITL approval, agent-chat votes,
and (via PositionManager) held-position stop-loss checks. A transient
Kiwoom hiccup could therefore fabricate a price low enough to trigger a
real defensive sell.

These tests pin the new contract: a fetch failure returns None, full stop —
never `_get_mock_*` output and never a random number.
"""

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from agents.tools.kr_market_data import (
    get_kr_current_price,
    get_kr_daily_chart,
    get_kr_orderbook,
    get_kr_stock_info,
)
from services.kiwoom.models import OrderbookUnit, Orderbook, StockBasicInfo

pytestmark = pytest.mark.asyncio


class _RaisingClient:
    """A fake Kiwoom client where every method raises, simulating a
    transient API/network failure (timeout, 5xx, connection reset, etc.)."""

    async def get_stock_info(self, stk_cd):
        raise RuntimeError("kiwoom timeout")

    async def get_current_price(self, stk_cd):
        raise RuntimeError("kiwoom timeout")

    async def get_orderbook(self, stk_cd):
        raise RuntimeError("kiwoom timeout")

    async def get_daily_chart_df(self, stk_cd, base_dt=None):
        raise RuntimeError("kiwoom timeout")


@pytest.fixture
def raising_client():
    return _RaisingClient()


class TestStockInfoFallback:
    async def test_client_exception_returns_none_not_mock(self, raising_client):
        """The old behavior returned _get_mock_kr_stock_info(stk_cd) — a
        np.random.seed(hash(stk_cd))-derived fabricated price/PER/PBR. The
        fix must return None so callers can detect the failure explicitly."""
        with patch(
            "agents.tools.kr_market_data.get_shared_kiwoom_client_async",
            AsyncMock(return_value=raising_client),
        ):
            result = await get_kr_stock_info("005930")

        assert result is None

    async def test_client_exception_does_not_call_mock_helper(self, raising_client):
        """Belt-and-suspenders: the mock generator must not even be invoked
        on the exception path."""
        with (
            patch(
                "agents.tools.kr_market_data.get_shared_kiwoom_client_async",
                AsyncMock(return_value=raising_client),
            ),
            patch(
                "agents.tools.kr_market_data._get_mock_kr_stock_info"
            ) as mock_helper,
        ):
            await get_kr_stock_info("005930")

        mock_helper.assert_not_called()


class TestCurrentPriceFallback:
    async def test_client_exception_returns_none_not_random_price(
        self, raising_client
    ):
        """The old behavior did `np.random.seed(hash(stk_cd)); return
        int(np.random.uniform(10000, 500000))` inline. That fabricated
        price is exactly the kind of number that could trip a stop-loss."""
        with patch(
            "agents.tools.kr_market_data.get_shared_kiwoom_client_async",
            AsyncMock(return_value=raising_client),
        ):
            result = await get_kr_current_price("005930")

        assert result is None


class TestOrderbookFallback:
    async def test_client_exception_returns_none_not_mock(self, raising_client):
        with patch(
            "agents.tools.kr_market_data.get_shared_kiwoom_client_async",
            AsyncMock(return_value=raising_client),
        ):
            result = await get_kr_orderbook("005930")

        assert result is None

    async def test_client_exception_does_not_call_mock_helper(self, raising_client):
        with (
            patch(
                "agents.tools.kr_market_data.get_shared_kiwoom_client_async",
                AsyncMock(return_value=raising_client),
            ),
            patch(
                "agents.tools.kr_market_data._get_mock_kr_orderbook"
            ) as mock_helper,
        ):
            await get_kr_orderbook("005930")

        mock_helper.assert_not_called()


class TestDailyChartFallback:
    async def test_client_exception_returns_none_not_mock_dataframe(
        self, raising_client
    ):
        with patch(
            "agents.tools.kr_market_data.get_shared_kiwoom_client_async",
            AsyncMock(return_value=raising_client),
        ):
            result = await get_kr_daily_chart("005930")

        assert result is None

    async def test_client_exception_does_not_call_mock_helper(self, raising_client):
        with (
            patch(
                "agents.tools.kr_market_data.get_shared_kiwoom_client_async",
                AsyncMock(return_value=raising_client),
            ),
            patch(
                "agents.tools.kr_market_data._generate_mock_kr_chart"
            ) as mock_helper,
        ):
            await get_kr_daily_chart("005930")

        mock_helper.assert_not_called()


class TestHappyPathUnaffected:
    """The real (or mock-server-backed, via KIWOOM_IS_MOCK) success path
    must be completely unchanged by this fix."""

    async def test_stock_info_success_returns_real_client_data(self):
        client = AsyncMock()
        client.get_stock_info = AsyncMock(
            return_value=StockBasicInfo(
                stk_cd="005930",
                stk_nm="삼성전자",
                cur_prc=72500,
                prdy_vrss=500,
                prdy_ctrt=0.69,
                acml_vol=1000000,
                acml_tr_pbmn=1_000_000_000,
                strt_prc=72000,
                high_prc=73000,
                low_prc=71500,
                stk_hgpr=90000,
                stk_lwpr=50000,
                per=12.5,
                pbr=1.2,
                eps=5800,
                bps=60000,
                lstg_stqt=5_969_782_550,
                mrkt_tot_amt=400_000_000_000_000,
            )
        )
        with patch(
            "agents.tools.kr_market_data.get_shared_kiwoom_client_async",
            AsyncMock(return_value=client),
        ):
            result = await get_kr_stock_info("005930")

        assert result is not None
        assert result["stk_cd"] == "005930"
        assert result["cur_prc"] == 72500

    async def test_daily_chart_success_returns_real_dataframe(self):
        client = AsyncMock()
        real_df = pd.DataFrame(
            {
                "open": [70000, 71000],
                "high": [71500, 72000],
                "low": [69500, 70500],
                "close": [71000, 71800],
                "volume": [100000, 120000],
            }
        )
        client.get_daily_chart_df = AsyncMock(return_value=real_df)
        with patch(
            "agents.tools.kr_market_data.get_shared_kiwoom_client_async",
            AsyncMock(return_value=client),
        ):
            result = await get_kr_daily_chart("005930")

        assert result is not None
        pd.testing.assert_frame_equal(result, real_df)

    async def test_orderbook_success_returns_real_client_data(self):
        client = AsyncMock()
        client.get_orderbook = AsyncMock(
            return_value=Orderbook(
                stk_cd="005930",
                sell_hogas=[OrderbookUnit(price=72600, quantity=500)],
                buy_hogas=[OrderbookUnit(price=72500, quantity=800)],
                tot_sell_qty=500,
                tot_buy_qty=800,
            )
        )
        with patch(
            "agents.tools.kr_market_data.get_shared_kiwoom_client_async",
            AsyncMock(return_value=client),
        ):
            result = await get_kr_orderbook("005930")

        assert result is not None
        assert result["stk_cd"] == "005930"
        assert result["tot_buy_qty"] == 800


class TestExplicitMockModeStillAvailable:
    """(d) The mock generators themselves must remain usable — they are no
    longer reachable from the exception path, but stay available for
    explicit/direct use (offline dev, unit tests). This mirrors the existing
    tests in tests/test_agents/test_kr_stock_graph.py::TestKRMarketData."""

    def test_mock_stock_info_still_generates_data(self):
        from agents.tools.kr_market_data import _get_mock_kr_stock_info

        info = _get_mock_kr_stock_info("005930")
        assert info["stk_cd"] == "005930"
        assert "cur_prc" in info

    def test_mock_orderbook_still_generates_data(self):
        from agents.tools.kr_market_data import _get_mock_kr_orderbook

        book = _get_mock_kr_orderbook("005930")
        assert book["stk_cd"] == "005930"
        assert len(book["sell_hogas"]) == 10

    def test_mock_chart_still_generates_data(self):
        from agents.tools.kr_market_data import _generate_mock_kr_chart

        df = _generate_mock_kr_chart("005930", days=10)
        assert len(df) == 10
