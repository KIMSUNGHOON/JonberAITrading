import pytest
from services.trading import market_data


class _FakeClient:
    def __init__(self, index_by_code=None, flow_by_mkt=None):
        self._index = index_by_code or {}
        self._flow = flow_by_mkt or {}

    async def get_sector_index(self, inds_cd="001"):
        return self._index.get(inds_cd)

    async def get_inst_foreign_flow(self, mrkt_tp="001"):
        return self._flow.get(mrkt_tp)


class _PartialRaisingClient:
    """KOSPI(001) call raises; KOSDAQ(101) call succeeds — for exception-isolation tests."""

    def __init__(self, kosdaq_rows):
        self._kosdaq_rows = kosdaq_rows

    async def get_sector_index(self, inds_cd="001"):
        if inds_cd == "001":
            raise RuntimeError("1700")
        return self._kosdaq_rows


@pytest.mark.asyncio
async def test_fetch_index_snapshot_extracts_both_markets():
    client = _FakeClient(index_by_code={
        "001": [{"stk_cd": "001", "cur_prc": 2393.33, "chg_pct": -1.2}],
        "101": [{"stk_cd": "101", "cur_prc": 850.5, "chg_pct": 0.4}],
    })
    snap = await market_data.fetch_index_snapshot(client)
    assert snap["index_kospi"] == pytest.approx(2393.33)
    assert snap["index_kospi_chg_pct"] == pytest.approx(-1.2)
    assert snap["index_kosdaq"] == pytest.approx(850.5)
    assert snap["index_kosdaq_chg_pct"] == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_fetch_index_snapshot_none_when_both_fail():
    client = _FakeClient(index_by_code={"001": None, "101": None})
    assert await market_data.fetch_index_snapshot(client) is None


@pytest.mark.asyncio
async def test_fetch_index_snapshot_none_client():
    assert await market_data.fetch_index_snapshot(None) is None


@pytest.mark.asyncio
async def test_fetch_index_snapshot_partial_success_when_one_market_raises():
    client = _PartialRaisingClient(
        kosdaq_rows=[{"stk_cd": "101", "cur_prc": 850.5, "chg_pct": 0.4}]
    )
    snap = await market_data.fetch_index_snapshot(client)
    assert snap is not None
    assert snap["index_kosdaq"] == pytest.approx(850.5)
    assert snap["index_kosdaq_chg_pct"] == pytest.approx(0.4)
    assert snap["index_kospi"] is None
    assert snap["index_kospi_chg_pct"] is None


@pytest.mark.asyncio
async def test_fetch_market_flow_aggregates():
    client = _FakeClient(flow_by_mkt={
        "001": [{"orgn_net_amt": 10.0, "frgnr_net_amt": -5.0},
                {"orgn_net_amt": 2.0, "frgnr_net_amt": 1.0}],
        "101": [{"orgn_net_amt": -3.0, "frgnr_net_amt": 4.0}],
    })
    flow = await market_data.fetch_market_flow(client)
    assert flow["institution_net_amount"] == pytest.approx(9.0)   # 10+2-3
    assert flow["foreign_net_amount"] == pytest.approx(0.0)       # -5+1+4


@pytest.mark.asyncio
async def test_fetch_market_flow_none_when_all_fail():
    client = _FakeClient(flow_by_mkt={"001": None, "101": None})
    assert await market_data.fetch_market_flow(client) is None
