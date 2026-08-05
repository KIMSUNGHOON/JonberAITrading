"""체결 1건의 거래비용 산정 — 순수 함수, 부작용 없음.

요율은 `app/config.py`의 `PaperFillSettings`에서 온다(수수료 편도 2bp,
매도 증권거래세 23bp). 그 설정군은 2026-08-05까지 소비처가 0곳이었다 —
정의만 되고 아무도 쓰지 않아 `kr_stock_trades` 103건이 전부 fee=0이었고,
그래서 kr_realized_pnl은 gross인데 daily_perf_snapshot은 net인 상태가
누구에게도 표시되지 않은 채 유지됐다.

브로커가 체결 단위 수수료를 주면 그 값이 이 모델보다 우선한다 —
`cost_source` 컬럼이 어느 쪽인지 구분한다.
"""
from __future__ import annotations

from app.config import get_paper_fill_settings

_BPS = 10_000.0


def compute_fill_cost(side: str, price: float, quantity: int) -> tuple[int, int]:
    """(수수료, 세금)을 원 단위 정수로 반환한다.

    수수료는 매수·매도 양쪽에 붙고, 증권거래세는 매도에만 붙는다.
    """
    if quantity <= 0 or price <= 0:
        return (0, 0)

    settings = get_paper_fill_settings()
    notional = price * quantity

    commission = round(notional * settings.kr_commission_bps / _BPS)
    tax = (
        round(notional * settings.kr_sell_tax_bps / _BPS)
        if side.lower() == "sell"
        else 0
    )
    return (int(commission), int(tax))
