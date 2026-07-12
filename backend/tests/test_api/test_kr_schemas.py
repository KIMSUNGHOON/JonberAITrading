"""KR API schema contracts.

LIVE-VERIFICATION BUG (R3-P2, 2026-07-12): KRStockTradeProposalResponse.action
was Literal["BUY","SELL","HOLD"] while the KR graph produces all 7 TradeActions
— a real LLM run returning WATCH made GET /analysis/status/{sid} 500 for the
whole awaiting_approval window (only the WS push path, which skips this model,
kept working).
"""
import pytest
from datetime import datetime, timezone

from agents.graph.kr_stock_state import TradeAction
from app.api.schemas.kr_stocks import KRStockTradeProposalResponse


def _proposal_kwargs(action):
    return dict(
        id="p1",
        stk_cd="005930",
        stk_nm="삼성전자",
        action=action,
        quantity=0,
        entry_price=285_000,
        stop_loss=262_200,
        take_profit=307_800,
        risk_score=0.057,
        position_size_pct=0.0,
        rationale="r",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize("action", [a.value for a in TradeAction])
def test_proposal_response_accepts_every_kr_trade_action(action):
    resp = KRStockTradeProposalResponse(**_proposal_kwargs(action))
    assert resp.action == action


def test_proposal_response_accepts_trade_action_enum_instances():
    # The status route passes the state's TradeAction enum member directly.
    resp = KRStockTradeProposalResponse(**_proposal_kwargs(TradeAction.WATCH))
    assert resp.action == "WATCH"
