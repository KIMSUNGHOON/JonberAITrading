"""P2-4 Task P1: `PaperFillSettings` (app/config.py) — the config surface
new fee/tax/slippage rates are read from. `docs/superpowers/audits/
2026-07-14-paper-fill-realism-audit.md` (§C, "설정화") called out that
`app/config.py` had zero fee/slippage settings (grep 0 hits) before this;
rates must be env-overridable and never hardcoded elsewhere in the codebase.
"""

from app.config import PaperFillSettings, get_paper_fill_settings, paper_fill_settings


def test_paper_fill_settings_has_the_four_fields_with_conservative_defaults():
    s = PaperFillSettings(_env_file=None)

    assert hasattr(s, "kr_commission_bps")
    assert hasattr(s, "kr_sell_tax_bps")
    assert hasattr(s, "coin_fee_bps")
    assert hasattr(s, "slippage_bps")

    # Conservative = real-or-higher, never zero (a zero default would be
    # exactly the bug this task fixes — "no fees modeled anywhere").
    assert s.kr_commission_bps > 0
    assert s.kr_sell_tax_bps > 0
    assert s.coin_fee_bps > 0
    assert s.slippage_bps > 0

    # Sanity vs. real-world magnitudes this task's brief specified:
    # coin_fee_bps ~5 (0.05%, matches real Upbit KRW-market taker fee),
    # kr_sell_tax_bps ~23 (0.23%, at/above real KRX transaction tax),
    # kr_commission_bps small (real KR discount-brokerage commission).
    assert s.coin_fee_bps == 5.0
    assert s.kr_sell_tax_bps == 23.0
    assert s.kr_commission_bps < s.kr_sell_tax_bps  # "small" relative to tax


def test_paper_fill_settings_env_override_works(monkeypatch):
    monkeypatch.setenv("PAPER_FILL_COIN_FEE_BPS", "12.5")
    monkeypatch.setenv("PAPER_FILL_KR_COMMISSION_BPS", "3.5")

    overridden = PaperFillSettings(_env_file=None)

    assert overridden.coin_fee_bps == 12.5
    assert overridden.kr_commission_bps == 3.5
    # Untouched fields keep their defaults.
    assert overridden.kr_sell_tax_bps == 23.0


def test_get_paper_fill_settings_is_cached_singleton():
    a = get_paper_fill_settings()
    b = get_paper_fill_settings()
    assert a is b
    assert paper_fill_settings is a


def test_paper_fill_settings_rejects_negative_rates():
    """ge=0 constraint — a negative fee/tax rate would mean the app pays
    you to trade, which is never correct for a cost model."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PaperFillSettings(_env_file=None, coin_fee_bps=-1.0)
