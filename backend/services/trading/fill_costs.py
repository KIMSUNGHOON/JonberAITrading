"""KR display-layer cost helper (P2-4 fill-realism, Task P1).

DESIGN PRINCIPLE — see `app/config.py::PaperFillSettings` for the full
rationale. In short: KR headline P&L comes from the mock BROKER ledger
(kt00004 account equity / ka10074 realized P&L), which already deducts its
own commission+tax. This module does NOT touch that ledger — it exists
solely to show the user a realistic "what would I actually keep if I exited
this position right now" number for the real-time unrealized P&L DISPLAY,
since the broker's raw price-diff unrealized figure (e.g. `evlu_pfls_amt`
from kt00004, or the app's own `ManagedPosition.unrealized_pnl`) has no
accounting for the round-trip cost of actually exiting.

Callers MUST NOT feed this back into `ManagedPosition.unrealized_pnl`,
`fill_confirm.py`, coordinator avg_price, or `paper_performance.py` — those
stay exactly as the broker reports them (R5-P1 regression risk otherwise).
"""

from typing import Literal, Optional

from app.config import PaperFillSettings, get_paper_fill_settings

Side = Literal["BUY", "SELL"]


def effective_pnl(
    avg_price: float,
    current_price: float,
    quantity: float,
    side: Side = "BUY",
    settings: Optional[PaperFillSettings] = None,
) -> float:
    """Return P&L net of round-trip KR trading cost (commission on both
    legs + sell-side securities transaction tax).

    KR positions in this app are long-only (no short-selling), so `side`
    defaults to "BUY" (opened via buy, would close via sell — commission on
    both legs, tax only on the sell/exit leg). `side="SELL"` is supported
    for completeness/documentation (a short opened via sell, closed via
    buy — commission+tax on the opening sell leg, commission only on the
    closing buy leg), even though nothing in this app currently opens one.

    This is a pure projection for display — it does not know or care
    whether the position has actually been closed.

    Args:
        avg_price: Position average entry price (the RAW broker/ledger
            value — never fee-adjusted upstream for KR).
        current_price: Current market price.
        quantity: Position quantity.
        side: "BUY" (long, the only KR case) or "SELL" (short, unused
            today but supported).
        settings: PaperFillSettings to read cost rates from; defaults to
            the cached singleton via `get_paper_fill_settings()`.

    Returns:
        Net P&L (KRW), i.e. gross price-diff P&L minus round-trip cost.
    """
    if settings is None:
        settings = get_paper_fill_settings()

    entry_notional = avg_price * quantity
    exit_notional = current_price * quantity

    commission_rate = settings.kr_commission_bps / 10_000
    tax_rate = settings.kr_sell_tax_bps / 10_000

    if side == "SELL":
        # Short: opened via sell (commission + tax on that leg), closes via
        # buy (commission only — KR tax is sell-side only).
        gross = entry_notional - exit_notional
        open_commission = entry_notional * commission_rate
        open_tax = entry_notional * tax_rate
        close_commission = exit_notional * commission_rate
        total_cost = open_commission + open_tax + close_commission
    else:
        # Long (the only case KR positions in this app take): opened via
        # buy (commission only), closes via sell (commission + tax).
        gross = exit_notional - entry_notional
        open_commission = entry_notional * commission_rate
        close_commission = exit_notional * commission_rate
        close_tax = exit_notional * tax_rate
        total_cost = open_commission + close_commission + close_tax

    return gross - total_cost


def effective_pnl_pct(
    avg_price: float,
    current_price: float,
    quantity: float,
    side: Side = "BUY",
    settings: Optional[PaperFillSettings] = None,
) -> float:
    """Same as `effective_pnl`, expressed as a percentage of cost basis
    (avg_price * quantity), matching the convention of the existing raw
    `unrealized_pnl_pct` fields this is meant to sit alongside."""
    cost_basis = avg_price * quantity
    if not cost_basis:
        return 0.0

    net = effective_pnl(avg_price, current_price, quantity, side, settings)
    return (net / cost_basis) * 100
