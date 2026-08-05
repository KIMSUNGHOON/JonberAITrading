"""체결 1건의 수수료·세금 산정. 원장이 gross인 채로 남으면
kr_realized_pnl(gross)과 daily_perf_snapshot(net)이 서로 다른 단위를
쓰게 되고, 실제로 07-31에 gross +1,186,512 vs net +984,533으로 갈렸다.
"""
import pytest

from services.trading.cost_model import compute_fill_cost


def test_buy_has_commission_but_no_tax():
    # 100,000원 x 10주 = 1,000,000원, 수수료 2bp = 200원
    commission, tax = compute_fill_cost("buy", 100_000.0, 10)
    assert commission == 200
    assert tax == 0, "증권거래세는 매도에만 붙는다"


def test_sell_has_both_commission_and_tax():
    # 1,000,000원 -> 수수료 2bp = 200원, 매도세 23bp = 2,300원
    commission, tax = compute_fill_cost("sell", 100_000.0, 10)
    assert commission == 200
    assert tax == 2_300


def test_side_is_case_insensitive():
    assert compute_fill_cost("SELL", 100_000.0, 10) == compute_fill_cost("sell", 100_000.0, 10)


def test_zero_quantity_costs_nothing():
    assert compute_fill_cost("buy", 100_000.0, 0) == (0, 0)


def test_rounds_to_whole_won():
    # 33,333원 x 1주 x 2bp = 6.6666원 -> 7원
    commission, tax = compute_fill_cost("buy", 33_333.0, 1)
    assert isinstance(commission, int) and isinstance(tax, int)
    assert commission == 7


@pytest.mark.asyncio
async def test_recorded_sell_fill_carries_commission_and_tax(isolated_storage_service):
    from services.trading.trade_log import record_trade_fill_async

    await record_trade_fill_async(
        stk_cd="005930", side="sell", order_type="limit",
        price=100_000.0, quantity=10, executed_quantity=10, status="completed",
    )
    rows = await isolated_storage_service.get_kr_stock_trades(stk_cd="005930")
    assert len(rows) == 1
    assert rows[0]["fee"] == 200
    assert rows[0]["tax"] == 2_300
    assert rows[0]["cost_source"] == "model"
