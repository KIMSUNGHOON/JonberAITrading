"""R3 t3: the shared autonomy gate — single fail-closed policy point.

Both autonomy engines (the analysis-pipeline auto-approve injector and the
ChatCoordinator execution path) must pass check_autonomy. Chain order:
master gate → market mode → paper-only (hardcoded) → daily-loss breaker →
max positions (BUY/ADD only) → notional cap (BUY/ADD only). Any provider
exception denies (fail-closed).
"""

import pytest

from services.autonomy import GateDecision, check_autonomy
import services.autonomy.gate as gate_module


def _providers(
    mode="autonomous",
    paper=True,
    daily_loss_pct=0.0,
    positions=0,
):
    async def mode_provider(market):
        return mode

    async def paper_provider(market):
        return paper

    async def daily_loss_provider(market):
        return daily_loss_pct

    async def positions_count_provider(market):
        return positions

    return dict(
        mode_provider=mode_provider,
        paper_provider=paper_provider,
        daily_loss_provider=daily_loss_provider,
        positions_count_provider=positions_count_provider,
    )


@pytest.fixture
def master_on(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "AUTONOMY_ENABLED", True)


async def _check(market="kiwoom", action="BUY", quantity=10, entry_price=50_000, **overrides):
    providers = _providers()
    providers.update(overrides)
    return await check_autonomy(
        market, action=action, quantity=quantity, entry_price=entry_price, **providers
    )


async def test_happy_path_allows(master_on):
    decision = await _check()
    assert decision == GateDecision(allowed=True, reason="ok", check="all")


async def test_master_gate_denies_by_default():
    # AUTONOMY_ENABLED defaults False — everything else green must not matter.
    decision = await _check()
    assert not decision.allowed
    assert decision.check == "master_gate"


async def test_hitl_mode_denies(master_on):
    decision = await _check(**_providers(mode="hitl"))
    assert not decision.allowed
    assert decision.check == "market_mode"


@pytest.mark.parametrize("market", ["kiwoom", "coin"])
async def test_live_mode_is_hard_denied(master_on, market):
    """The paper-only check is the load-bearing safety line: autonomous+live
    must be impossible regardless of every other setting."""
    decision = await _check(market=market, **_providers(paper=False))
    assert not decision.allowed
    assert decision.check == "paper_only"


async def test_daily_loss_breaker_denies(master_on):
    decision = await _check(**_providers(daily_loss_pct=3.5))
    assert not decision.allowed
    assert decision.check == "daily_loss_breaker"


async def test_daily_loss_breaker_notifies_once_per_day(master_on, monkeypatch):
    sent = []

    async def fake_notify(message):
        sent.append(message)

    monkeypatch.setattr(gate_module, "_notify_breaker", fake_notify)
    monkeypatch.setattr(gate_module, "_last_breaker_notice_date", None)

    await _check(**_providers(daily_loss_pct=5.0))
    await _check(**_providers(daily_loss_pct=5.0))

    assert len(sent) == 1


async def test_max_positions_denies_buy(master_on):
    decision = await _check(action="BUY", **_providers(positions=5))
    assert not decision.allowed
    assert decision.check == "max_positions"


async def test_notional_cap_denies_buy(master_on):
    decision = await _check(action="BUY", quantity=100, entry_price=50_000)  # ₩5M > ₩1M
    assert not decision.allowed
    assert decision.check == "notional_cap"


async def test_buy_with_unknown_notional_is_denied(master_on):
    """Fail-closed: a BUY whose size we cannot price never auto-executes."""
    decision = await _check(action="BUY", quantity=None, entry_price=None)
    assert not decision.allowed
    assert decision.check == "notional_cap"


@pytest.mark.parametrize("action", ["SELL", "REDUCE", "HOLD", "WATCH"])
async def test_non_increasing_actions_skip_position_and_notional_checks(master_on, action):
    """SELL/REDUCE/HOLD/WATCH don't grow exposure — caps 5/6 don't apply."""
    decision = await _check(
        action=action, quantity=None, entry_price=None, **_providers(positions=99)
    )
    assert decision.allowed


async def test_provider_exception_is_fail_closed(master_on):
    async def boom(market):
        raise RuntimeError("broker unreachable")

    decision = await _check(positions_count_provider=boom)
    assert not decision.allowed
    assert decision.check == "max_positions"
    assert "broker unreachable" in decision.reason
