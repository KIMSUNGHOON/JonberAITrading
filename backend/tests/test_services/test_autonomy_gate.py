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


async def test_default_paper_provider_binds_to_executing_clients(master_on, monkeypatch):
    """SAFETY (review-critical fix): the runtime intent flag alone is not
    paper-proof — a coordinator built while LIVE keeps its live client after
    the flag is flipped back. The provider must deny then."""
    from services.autonomy.gate import _default_paper_provider

    class FakeClient:
        MOCK_URL = "https://mockapi.kiwoom.com"

        def __init__(self, is_mock):
            self.is_mock = is_mock
            self.base_url = self.MOCK_URL if is_mock else "https://api.kiwoom.com"

    monkeypatch.setattr("app.api.routes.settings.get_kiwoom_is_mock", lambda: True)

    async def shared_mock():
        return FakeClient(is_mock=True)

    monkeypatch.setattr(
        "app.core.kiwoom_singleton.get_shared_kiwoom_client_async", shared_mock
    )

    import app.dependencies as deps

    class FakeCoordinator:
        pass

    # Coordinator captured a LIVE client → deny despite the paper flag.
    live_coord = FakeCoordinator()
    live_coord._kiwoom = FakeClient(is_mock=False)
    monkeypatch.setattr(deps, "_trading_coordinator_instance", live_coord)
    assert await _default_paper_provider("kiwoom") is False

    # Coordinator's client is genuinely mock → allow.
    mock_coord = FakeCoordinator()
    mock_coord._kiwoom = FakeClient(is_mock=True)
    monkeypatch.setattr(deps, "_trading_coordinator_instance", mock_coord)
    assert await _default_paper_provider("kiwoom") is True

    # No coordinator constructed yet → the shared client decides.
    monkeypatch.setattr(deps, "_trading_coordinator_instance", None)
    assert await _default_paper_provider("kiwoom") is True


async def test_queued_autonomous_trade_is_regated_at_execution(master_on, monkeypatch):
    """SAFETY (review fix): a gate verdict from queueing time is stale — the
    queue processor must re-check before executing autonomy-originated trades
    (a mode flip to HITL between queueing and execution must win)."""
    import services.autonomy as autonomy_pkg
    from services.trading.coordinator import ExecutionCoordinator
    from services.trading.models import QueueStatus

    coordinator = ExecutionCoordinator(kiwoom_client=None)
    coordinator.add_to_queue(
        session_id="s1", ticker="005930", stock_name="삼성전자", action="BUY",
        entry_price=50_000, stop_loss=None, take_profit=None, risk_score=5,
        reason="Market closed", autonomous=True,
    )

    executed = []

    async def record_on_trade_approved(*args, **kwargs):
        executed.append(kwargs.get("ticker") or (args and args[1]))

    coordinator.on_trade_approved = record_on_trade_approved

    async def deny_gate(market, **kwargs):
        return GateDecision(allowed=False, reason="trading_mode:kiwoom is 'hitl'", check="market_mode")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", deny_gate)

    await coordinator.process_trade_queue()

    assert executed == [], "gate-denied queued autonomous trade must not execute"
    assert coordinator._state.trade_queue[0].status == QueueStatus.CANCELLED


async def test_provider_exception_is_fail_closed(master_on):
    async def boom(market):
        raise RuntimeError("broker unreachable")

    decision = await _check(positions_count_provider=boom)
    assert not decision.allowed
    assert decision.check == "max_positions"
    assert "broker unreachable" in decision.reason


class TestDefaultDailyLossProvider:
    """Phase B2: kiwoom 기본 daily-loss 프로바이더가 ka10074 실현손익에 배선됨.

    조회 실패는 예외 전파 → 게이트 체인의 기존 fail-closed 랩이 deny 처리.
    coin은 실현 P&L 소스 부재로 0(비활성) 유지 — 사유 문서화.
    """

    def _mock_client(self, monkeypatch, realized_pnl, evlu_amt=0, d2=0, pnl_exc=None):
        from unittest.mock import AsyncMock

        from services.kiwoom.models import AccountBalance, RealizedPnl

        client = AsyncMock()
        if pnl_exc is not None:
            client.get_realized_pnl.side_effect = pnl_exc
        else:
            client.get_realized_pnl.return_value = RealizedPnl(
                strt_dt="20260712", end_dt="20260712", realized_pnl=realized_pnl
            )
        client.get_account_balance.return_value = AccountBalance(
            evlu_amt=evlu_amt, d2_ord_psbl_amt=d2
        )

        async def fake_get_client():
            return client

        import app.core.kiwoom_singleton as singleton

        monkeypatch.setattr(
            singleton, "get_shared_kiwoom_client_async", fake_get_client
        )
        return client

    @pytest.mark.asyncio
    async def test_kiwoom_loss_pct_from_realized_pnl(self, monkeypatch):
        # 당일 실현손실 -100,000 / 자산 (주식 3,000,000 + 예수금 2,000,000) = 2%
        self._mock_client(monkeypatch, realized_pnl=-100_000,
                          evlu_amt=3_000_000, d2=2_000_000)
        pct = await gate_module._default_daily_loss_provider("kiwoom")
        assert pct == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_kiwoom_profit_or_flat_is_zero_loss(self, monkeypatch):
        client = self._mock_client(monkeypatch, realized_pnl=50_000)
        pct = await gate_module._default_daily_loss_provider("kiwoom")
        assert pct == 0.0
        client.get_account_balance.assert_not_called()  # 손실 없으면 계좌 조회 불필요

    @pytest.mark.asyncio
    async def test_kiwoom_lookup_failure_propagates_for_fail_closed(self, monkeypatch):
        self._mock_client(monkeypatch, realized_pnl=0,
                          pnl_exc=RuntimeError("mockapi down"))
        with pytest.raises(RuntimeError):
            await gate_module._default_daily_loss_provider("kiwoom")

    @pytest.mark.asyncio
    async def test_kiwoom_zero_account_value_raises(self, monkeypatch):
        # 손실은 있는데 자산 평가가 0 — 손실률 계산 불가는 통과가 아니라 예외
        self._mock_client(monkeypatch, realized_pnl=-100_000, evlu_amt=0, d2=0)
        with pytest.raises(ValueError):
            await gate_module._default_daily_loss_provider("kiwoom")

    @pytest.mark.asyncio
    async def test_coin_stays_zero(self):
        assert await gate_module._default_daily_loss_provider("coin") == 0.0

    @pytest.mark.asyncio
    async def test_gate_denies_when_default_provider_lookup_fails(
        self, master_on, monkeypatch
    ):
        # 통합: 기본 프로바이더 조회 실패 → 게이트 deny (fail-closed)
        self._mock_client(monkeypatch, realized_pnl=0,
                          pnl_exc=RuntimeError("mockapi down"))
        providers = _providers()
        providers.pop("daily_loss_provider")  # 기본 프로바이더 사용
        decision = await check_autonomy(
            "kiwoom", action="HOLD", quantity=None, entry_price=None, **providers
        )
        assert decision.allowed is False
        assert decision.check == "daily_loss_breaker"
