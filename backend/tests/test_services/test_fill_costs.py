"""P2-4 Task P1: KR display-layer cost helper (`services/trading/fill_costs.py`).

Design principle under test: this helper is a pure, standalone projection —
it must NEVER be the thing that mutates the KR broker ledger. These tests
prove (a) `effective_pnl`/`effective_pnl_pct` compute round-trip-cost-aware
P&L correctly in isolation, and (b) `ManagedPosition.unrealized_pnl` (the
actual ledger field) stays a raw, cost-free price-diff — i.e. Task P1 did
NOT touch the ledger, only added a parallel display-layer helper.
"""

import pytest

from app.config import PaperFillSettings
from services.trading.fill_costs import effective_pnl, effective_pnl_pct
from services.trading.models import ManagedPosition


def _settings(**overrides) -> PaperFillSettings:
    """Build a PaperFillSettings with explicit, deterministic rates for
    unit-testable arithmetic (bypasses env/.env entirely)."""
    fields = dict(
        kr_commission_bps=10.0,  # 0.10% per side, round numbers for easy math
        kr_sell_tax_bps=20.0,    # 0.20%, sell-side only
        coin_fee_bps=5.0,
        slippage_bps=10.0,
    )
    fields.update(overrides)
    return PaperFillSettings(_env_file=None, **fields)


# -------------------------------------------
# effective_pnl / effective_pnl_pct — long (BUY) position, the only side
# KR positions in this app actually take.
# -------------------------------------------


def test_effective_pnl_long_nets_out_round_trip_commission_and_tax():
    settings = _settings()
    avg_price, current_price, quantity = 100_000.0, 110_000.0, 10.0

    gross = (current_price - avg_price) * quantity  # 100,000
    net = effective_pnl(avg_price, current_price, quantity, "BUY", settings)

    entry_notional = avg_price * quantity      # 1,000,000
    exit_notional = current_price * quantity   # 1,100,000
    expected_cost = (
        entry_notional * 0.0010       # entry commission
        + exit_notional * 0.0010      # exit commission
        + exit_notional * 0.0020      # sell tax
    )
    assert net == pytest.approx(gross - expected_cost)
    assert net < gross  # cost-aware net must never exceed the gross price-diff


def test_effective_pnl_long_default_side_is_buy():
    settings = _settings()
    a = effective_pnl(100_000.0, 110_000.0, 10.0, settings=settings)
    b = effective_pnl(100_000.0, 110_000.0, 10.0, "BUY", settings=settings)
    assert a == pytest.approx(b)


def test_effective_pnl_pct_matches_manual_ratio():
    settings = _settings()
    avg_price, current_price, quantity = 100_000.0, 110_000.0, 10.0

    net = effective_pnl(avg_price, current_price, quantity, "BUY", settings)
    pct = effective_pnl_pct(avg_price, current_price, quantity, "BUY", settings)

    cost_basis = avg_price * quantity
    assert pct == pytest.approx(net / cost_basis * 100)


def test_effective_pnl_pct_zero_cost_basis_is_zero_not_divide_by_zero():
    settings = _settings()
    assert effective_pnl_pct(0.0, 110_000.0, 10.0, "BUY", settings) == 0.0
    assert effective_pnl_pct(100_000.0, 110_000.0, 0.0, "BUY", settings) == 0.0


def test_effective_pnl_short_side_mirrors_long_with_legs_swapped():
    """side="SELL" (short — unused by any KR flow today, but supported for
    completeness): opened via sell (commission+tax on that leg), closed via
    buy (commission only)."""
    settings = _settings()
    avg_price, current_price, quantity = 110_000.0, 100_000.0, 10.0  # price fell -> short profits

    gross = (avg_price - current_price) * quantity  # 100,000
    net = effective_pnl(avg_price, current_price, quantity, "SELL", settings)

    entry_notional = avg_price * quantity
    exit_notional = current_price * quantity
    expected_cost = (
        entry_notional * 0.0010    # open commission
        + entry_notional * 0.0020  # open tax (sell-side)
        + exit_notional * 0.0010   # close commission (buy leg, no tax)
    )
    assert net == pytest.approx(gross - expected_cost)


def test_effective_pnl_uses_cached_settings_by_default():
    """No explicit settings -> falls back to get_paper_fill_settings()
    (proves the default wiring works, not just the explicit-settings path
    exercised by every other test above)."""
    net = effective_pnl(100_000.0, 110_000.0, 10.0, "BUY")
    assert isinstance(net, float)
    assert net < (110_000.0 - 100_000.0) * 10.0  # some cost was applied


# -------------------------------------------
# Regression: the actual KR ledger field (ManagedPosition.unrealized_pnl)
# must stay a raw, cost-free price-diff — Task P1 must NOT have touched it.
# -------------------------------------------


def test_managed_position_unrealized_pnl_ledger_field_stays_raw():
    pos = ManagedPosition(
        ticker="005930", stock_name="삼성전자", quantity=10,
        avg_price=260000.0, current_price=266000.0,
    )
    # Raw broker-style price-diff, NO commission/tax applied — this is the
    # actual ledger field coordinator/fill_confirm/paper_performance read,
    # and it must diverge from (be strictly greater than) the
    # cost-aware `effective_pnl` for the same inputs.
    assert pos.unrealized_pnl == pytest.approx((266000.0 - 260000.0) * 10)
    assert pos.unrealized_pnl == 60000.0

    net = effective_pnl(260000.0, 266000.0, 10, "BUY")
    assert net < pos.unrealized_pnl
