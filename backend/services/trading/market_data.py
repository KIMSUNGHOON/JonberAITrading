"""Phase 5: normalized market-wide data fetchers (index + investor flow).

Wraps the raw Kiwoom fetchers (KiwoomClient.get_sector_index / .get_inst_
foreign_flow, ka20003/ka10131) into normalized snapshots consumed by the
EOD regime enrichment (services/trading/regime.py::compute_market_regime).

Failure-harmless by design: any missing client, fetch error, or empty
response yields None (or a partial dict) rather than raising — the EOD
orchestrator must never break on a market-data hiccup, and mock/offline
runs simply fall back to breadth-only regime.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ka20003 종합지수 코드: KOSPI 종합 = "001", KOSDAQ 종합 = "101".
_KOSPI_CODE = "001"
_KOSDAQ_CODE = "101"


def _pick_composite(rows: Optional[list[dict]], stk_cd: str) -> Optional[dict]:
    """all_inds_idex 리스트에서 종합지수 행(stk_cd) 하나를 고른다."""
    if not rows:
        return None
    for r in rows:
        if r.get("stk_cd") == stk_cd:
            return r
    return rows[0]  # 폴백: 첫 행(전업종지수는 종합이 선두)


async def fetch_index_snapshot(client: Any) -> Optional[dict]:
    """KOSPI(001)/KOSDAQ(101) 종합지수 레벨·등락률. 둘 다 실패 → None."""
    if client is None:
        return None
    try:
        kospi_rows = await client.get_sector_index(_KOSPI_CODE)
        kosdaq_rows = await client.get_sector_index(_KOSDAQ_CODE)
    except Exception as e:
        logger.warning(f"[MarketData] fetch_index_snapshot failed: {e}")
        return None

    kospi = _pick_composite(kospi_rows, _KOSPI_CODE)
    kosdaq = _pick_composite(kosdaq_rows, _KOSDAQ_CODE)
    if kospi is None and kosdaq is None:
        return None

    return {
        "index_kospi": kospi.get("cur_prc") if kospi else None,
        "index_kospi_chg_pct": kospi.get("chg_pct") if kospi else None,
        "index_kosdaq": kosdaq.get("cur_prc") if kosdaq else None,
        "index_kosdaq_chg_pct": kosdaq.get("chg_pct") if kosdaq else None,
    }


async def fetch_market_flow(client: Any) -> Optional[dict]:
    """KOSPI+KOSDAQ 반환행의 외국인/기관 순매매액 합(시장 방향성 프록시).
    전부 실패 → None."""
    if client is None:
        return None
    orgn_total = 0.0
    frgnr_total = 0.0
    got_any = False
    for mkt in (_KOSPI_CODE, _KOSDAQ_CODE):
        try:
            rows = await client.get_inst_foreign_flow(mkt)
        except Exception as e:
            logger.warning(f"[MarketData] fetch_market_flow({mkt}) failed: {e}")
            rows = None
        if not rows:
            continue
        got_any = True
        for r in rows:
            orgn_total += float(r.get("orgn_net_amt") or 0.0)
            frgnr_total += float(r.get("frgnr_net_amt") or 0.0)
    if not got_any:
        return None
    return {
        "foreign_net_amount": frgnr_total,
        "institution_net_amount": orgn_total,
    }
