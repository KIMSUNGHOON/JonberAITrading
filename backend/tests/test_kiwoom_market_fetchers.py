import pytest
from unittest.mock import AsyncMock
from services.kiwoom.client import KiwoomClient


def _make_client() -> KiwoomClient:
    c = KiwoomClient.__new__(KiwoomClient)  # bypass __init__ (no network/auth)
    c._cache = None
    return c


@pytest.mark.asyncio
async def test_get_sector_index_parses_kospi_row():
    c = _make_client()
    c._request = AsyncMock(return_value={
        "all_inds_idex": [
            {"stk_cd": "001", "stk_nm": "종합(KOSPI)", "cur_prc": "-2393.33",
             "flu_rt": "-10.46", "rising": "17", "stdns": "184", "fall": "129"},
            {"stk_cd": "002", "stk_nm": "대형주", "cur_prc": "-2379.14",
             "flu_rt": "-12.08", "rising": "5", "stdns": "10", "fall": "20"},
        ]
    })
    rows = await c.get_sector_index("001")
    assert rows is not None and len(rows) == 2
    kospi = rows[0]
    assert kospi["stk_cd"] == "001"
    assert kospi["cur_prc"] == pytest.approx(2393.33)   # abs — sign is direction
    assert kospi["chg_pct"] == pytest.approx(-10.46)    # signed — real pct
    assert kospi["rising"] == 17 and kospi["fall"] == 129
    c._request.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_sector_index_returns_none_on_error():
    c = _make_client()
    c._request = AsyncMock(side_effect=RuntimeError("1700"))
    assert await c.get_sector_index("001") is None


@pytest.mark.asyncio
async def test_get_inst_foreign_flow_parses_signed_amounts():
    c = _make_client()
    c._request = AsyncMock(return_value={
        "orgn_frgnr_cont_trde_prst": [
            {"stk_cd": "005930", "orgn_nettrde_amt": "+48", "frgnr_nettrde_amt": "-12",
             "orgn_cont_netprps_dys": "+1", "frgnr_cont_netprps_dys": "+3"},
        ]
    })
    rows = await c.get_inst_foreign_flow("001")
    assert rows is not None and len(rows) == 1
    r = rows[0]
    assert r["orgn_net_amt"] == pytest.approx(48.0)
    assert r["frgnr_net_amt"] == pytest.approx(-12.0)
    assert r["orgn_cont_days"] == 1 and r["frgnr_cont_days"] == 3


@pytest.mark.asyncio
async def test_get_inst_foreign_flow_returns_none_on_empty():
    c = _make_client()
    c._request = AsyncMock(return_value={})   # no key
    assert await c.get_inst_foreign_flow("001") is None


@pytest.mark.asyncio
async def test_get_inst_foreign_flow_parses_double_minus():
    c = _make_client()
    c._request = AsyncMock(return_value={
        "orgn_frgnr_cont_trde_prst": [
            {"stk_cd": "005935", "orgn_nettrde_amt": "--35", "frgnr_nettrde_amt": "+122068",
             "orgn_cont_netprps_dys": "-2", "frgnr_cont_netprps_dys": "+1"},
        ]
    })
    rows = await c.get_inst_foreign_flow("001")
    assert rows is not None and len(rows) == 1
    assert rows[0]["orgn_net_amt"] == pytest.approx(-35.0)
    assert rows[0]["frgnr_net_amt"] == pytest.approx(122068.0)
    assert rows[0]["orgn_cont_days"] == -2 and rows[0]["frgnr_cont_days"] == 1


@pytest.mark.asyncio
async def test_get_inst_foreign_flow_skips_bad_row_keeps_rest():
    c = _make_client()
    c._request = AsyncMock(return_value={
        "orgn_frgnr_cont_trde_prst": [
            {"stk_cd": "AAA", "orgn_nettrde_amt": "+10", "frgnr_nettrde_amt": "+1",
             "orgn_cont_netprps_dys": "+1", "frgnr_cont_netprps_dys": "+1"},
            {"stk_cd": "BAD", "orgn_nettrde_amt": "not_a_number", "frgnr_nettrde_amt": "+1",
             "orgn_cont_netprps_dys": "+1", "frgnr_cont_netprps_dys": "+1"},
            {"stk_cd": "CCC", "orgn_nettrde_amt": "--5", "frgnr_nettrde_amt": "+2",
             "orgn_cont_netprps_dys": "+1", "frgnr_cont_netprps_dys": "+1"},
        ]
    })
    rows = await c.get_inst_foreign_flow("001")
    assert rows is not None
    codes = [r["stk_cd"] for r in rows]
    assert codes == ["AAA", "CCC"]   # BAD 행만 skip, 나머지 보존
