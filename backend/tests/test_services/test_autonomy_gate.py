"""R3 t3: the shared autonomy gate — single fail-closed policy point.

Both autonomy engines (the analysis-pipeline auto-approve injector and the
ChatCoordinator execution path) must pass check_autonomy. Chain order:
master gate → market mode → paper-only (hardcoded) → daily-loss breaker →
coordinator-active (BUY/ADD, kiwoom only, F4b I6) → max positions (BUY/ADD
only, F4b I2 counts F3 pending-fill BUYs too) → notional cap (BUY/ADD only).
Any provider exception denies (fail-closed).
"""

import pytest

from services.autonomy import GateDecision, check_autonomy
from services.trading.models import RiskParameters
import services.autonomy.gate as gate_module


def _providers(
    mode="autonomous",
    paper=True,
    daily_loss_pct=0.0,
    positions=0,
    coordinator_active=True,
):
    async def mode_provider(market):
        return mode

    async def paper_provider(market):
        return paper

    async def daily_loss_provider(market):
        return daily_loss_pct

    async def positions_count_provider(market):
        return positions

    async def coordinator_active_provider(market):
        return coordinator_active

    return dict(
        mode_provider=mode_provider,
        paper_provider=paper_provider,
        daily_loss_provider=daily_loss_provider,
        positions_count_provider=positions_count_provider,
        coordinator_active_provider=coordinator_active_provider,
    )


@pytest.fixture
def master_on(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "AUTONOMY_ENABLED", True)


async def _default_account_equity(market):
    # T1: notional cap is now equity-relative. Default a large-but-realistic
    # equity (10M) so pre-existing pass-fixture tests (written for the old
    # fixed-krw cap) keep their original allow/deny outcomes without needing
    # to touch every call site — override explicitly where a test cares.
    return 10_000_000


async def _check(market="kiwoom", action="BUY", quantity=10, entry_price=50_000, **overrides):
    providers = _providers()
    providers.setdefault("account_equity_provider", _default_account_equity)
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


class TestDailyLossBreakerScopedToPositionIncreasingActions:
    """S-1 / D3 (docs/superpowers/specs/2026-07-19-survival-discipline-design.md
    §D3): this system has no short-selling, so a SELL/REDUCE is always a
    size-down — it can never be the thing that deepens a loss. Blocking the
    stop-loss exit that would stop the bleeding because the breaker itself
    tripped is exactly backwards. Scope the breaker to
    POSITION_INCREASING_ACTIONS (BUY/ADD), same as caps 5/6/7 already are.
    Master/mode/paper stay action-agnostic (they precede the action branch).
    """

    @pytest.mark.parametrize("action", ["SELL", "REDUCE"])
    async def test_tripped_breaker_allows_risk_reducing_actions(self, master_on, action):
        decision = await _check(
            action=action, quantity=None, entry_price=None,
            **_providers(daily_loss_pct=5.0),  # tripped: default limit is 3.0%
        )
        assert decision.allowed is True

    @pytest.mark.parametrize("action", ["BUY", "ADD"])
    async def test_tripped_breaker_still_denies_position_increasing_actions(
        self, master_on, action
    ):
        decision = await _check(action=action, **_providers(daily_loss_pct=5.0))
        assert decision.allowed is False
        assert decision.check == "daily_loss_breaker"

    async def test_master_off_still_denies_sell_even_with_tripped_breaker(self):
        # No master_on fixture: AUTONOMY_ENABLED defaults False. The
        # exemption is breaker-only -- master/mode/paper precede the action
        # branch entirely and must keep denying SELL regardless.
        decision = await _check(
            action="SELL", quantity=None, entry_price=None,
            **_providers(daily_loss_pct=5.0),
        )
        assert decision.allowed is False
        assert decision.check == "master_gate"

    async def test_hitl_mode_still_denies_sell_even_with_tripped_breaker(self, master_on):
        decision = await _check(
            action="SELL", quantity=None, entry_price=None,
            **_providers(mode="hitl", daily_loss_pct=5.0),
        )
        assert decision.allowed is False
        assert decision.check == "market_mode"

    @pytest.mark.parametrize(
        "action", ["BUY", "ADD", "SELL", "REDUCE", "HOLD", "WATCH"]
    )
    async def test_untripped_breaker_behavior_is_unchanged(self, master_on, action):
        # Byte-invariant: with the breaker not tripped, every action's
        # outcome is unchanged from pre-D3 behavior -- allowed, since nothing
        # else denies at these defaults (positions=0, equity=10M, pct=15%).
        decision = await _check(
            action=action, quantity=10, entry_price=50_000,
            **_providers(daily_loss_pct=0.0),
        )
        assert decision.allowed is True


async def test_max_positions_denies_buy(master_on):
    decision = await _check(action="BUY", **_providers(positions=5))
    assert not decision.allowed
    assert decision.check == "max_positions"


def _held(*tickers):
    async def held_tickers_provider(market):
        return set(tickers)

    return held_tickers_provider


class TestAddToHeldTickerExemptFromSlotCap:
    """이미 보유한 종목을 더 사는 것은 max_open_positions를 소비하지 않는다.

    2026-08-05 라이브: 316140이 ADD를 7회 의결했는데 전부
    `check=max_positions`("open positions 5 >= limit 5")로 거절돼 체결 0건이
    었다. 보유 종목 수는 계좌의 **서로 다른 티커 집합** 크기이므로, 이미
    보유한 종목을 추가매수해도 그 수는 변하지 않는다. 만석(5/5)이 이
    시스템의 정상 상태라, 이 검사는 자율 추가매수를 상시 불가능하게 만들고
    있었다(이전 아크의 "매수 81건 중 ADD 라벨 0건"의 정체).

    면제는 **티커가 실제로 보유 목록에 있을 때만** 적용된다 — 호출자의
    주장이 아니라 게이트가 직접 확인한다.
    """

    async def test_add_to_held_ticker_allowed_when_slots_full(self, master_on):
        decision = await _check(
            action="BUY",
            ticker="316140",
            held_tickers_provider=_held(
                "004370", "068270", "089860", "090430", "316140"
            ),
            **_providers(positions=5),
        )
        assert decision.allowed is True

    async def test_unheld_ticker_still_denied_when_slots_full(self, master_on):
        decision = await _check(
            action="BUY",
            ticker="005930",
            held_tickers_provider=_held(
                "004370", "068270", "089860", "090430", "316140"
            ),
            **_providers(positions=5),
        )
        assert not decision.allowed
        assert decision.check == "max_positions"

    async def test_omitting_ticker_preserves_existing_behavior(self, master_on):
        # 기존 호출부(티커를 넘기지 않는 곳)는 동작이 한 톨도 바뀌면 안 된다.
        decision = await _check(action="BUY", **_providers(positions=5))
        assert not decision.allowed
        assert decision.check == "max_positions"

    async def test_slot_count_comes_from_the_same_held_snapshot(self, master_on):
        """ticker가 주어지면 소속과 개수를 같은 스냅샷에서 읽는다.

        따로 조회하면 그 사이에 체결이 끼어 "목록엔 없는데 카운트는 0"
        같은 어긋난 쌍으로 판정할 수 있다. 보유 목록이 5종이면 카운트
        프로바이더가 뭐라 하든 5로 판정해야 한다.
        """
        decision = await _check(
            action="BUY",
            ticker="005930",
            held_tickers_provider=_held(
                "004370", "068270", "089860", "090430", "316140"
            ),
            **_providers(positions=0),  # 어긋난 값 — 무시되어야 한다
        )
        assert not decision.allowed
        assert decision.check == "max_positions"
        assert "5 >= limit 5" in decision.reason

    async def test_held_lookup_failure_denies_fail_closed(self, master_on):
        async def boom(market):
            raise RuntimeError("broker unreachable")

        decision = await _check(
            action="BUY",
            ticker="316140",
            held_tickers_provider=boom,
            **_providers(positions=5),
        )
        assert not decision.allowed
        assert decision.check == "max_positions"
        assert "broker unreachable" in decision.reason

    async def test_held_ticker_still_subject_to_other_caps(self, master_on):
        # 슬롯 면제가 다른 검사까지 열어주면 안 된다 — 일일 손실 브레이커는
        # 여전히 물어야 한다.
        decision = await _check(
            action="BUY",
            ticker="316140",
            held_tickers_provider=_held("316140"),
            **_providers(positions=5, daily_loss_pct=99.0),
        )
        assert not decision.allowed
        assert decision.check == "daily_loss_breaker"


class TestCoordinatorActiveGate:
    """F4b I6: an autonomous BUY/ADD must deny when the trading coordinator
    isn't active — otherwise the F3 post-fill tail (fill-tracker poll /
    reconciler / stop-loss registration) never runs and the new exposure
    goes unwatched. Scoped to kiwoom + BUY/ADD only; HITL never calls
    check_autonomy at all (see TestCoordinatorCheckNeverBlocksHitl below), so
    this link can't touch a manual approval regardless of scoping.
    """

    # NOTE: these call check_autonomy directly (not the _check() helper) so
    # popping "coordinator_active_provider" actually exercises the REAL
    # default provider — _check() rebuilds its own full _providers() default
    # set internally and only ever *updates* it with overrides, so a popped
    # key would silently keep _check()'s own default instead of falling
    # through to check_autonomy's real one.

    async def test_denies_when_coordinator_is_none(self, master_on, monkeypatch):
        import app.dependencies as deps

        monkeypatch.setattr(deps, "_trading_coordinator_instance", None)
        providers = _providers()
        providers.pop("coordinator_active_provider")  # exercise the REAL default
        decision = await check_autonomy(
            "kiwoom", action="BUY", quantity=10, entry_price=50_000, **providers
        )
        assert not decision.allowed
        assert decision.check == "coordinator_active"
        assert "미기동" in decision.reason

    async def test_denies_when_coordinator_is_inactive(self, master_on, monkeypatch):
        import app.dependencies as deps

        class FakeCoordinator:
            is_active = False

        monkeypatch.setattr(deps, "_trading_coordinator_instance", FakeCoordinator())
        providers = _providers()
        providers.pop("coordinator_active_provider")
        decision = await check_autonomy(
            "kiwoom", action="BUY", quantity=10, entry_price=50_000, **providers
        )
        assert not decision.allowed
        assert decision.check == "coordinator_active"
        assert "미기동" in decision.reason

    async def test_allows_when_coordinator_is_active(self, master_on, monkeypatch):
        import app.dependencies as deps

        class FakeCoordinator:
            is_active = True

        monkeypatch.setattr(deps, "_trading_coordinator_instance", FakeCoordinator())
        providers = _providers()
        providers.pop("coordinator_active_provider")
        # T1: reaches the (kiwoom-only) notional check now — supply a
        # deterministic equity so this stays a coordinator-active test, not
        # an incidental notional/broker-reachability test.
        decision = await check_autonomy(
            "kiwoom", action="BUY", quantity=10, entry_price=50_000,
            account_equity_provider=_default_account_equity, **providers
        )
        assert decision == GateDecision(allowed=True, reason="ok", check="all")

    @pytest.mark.parametrize("action", ["SELL", "REDUCE", "HOLD", "WATCH"])
    async def test_skipped_for_non_increasing_actions(self, master_on, monkeypatch, action):
        """Scoped like caps 6/7 — SELL/REDUCE/HOLD/WATCH must not deny even
        with no coordinator at all."""
        import app.dependencies as deps

        monkeypatch.setattr(deps, "_trading_coordinator_instance", None)
        providers = _providers()
        providers.pop("coordinator_active_provider")
        decision = await check_autonomy(
            "kiwoom", action=action, quantity=None, entry_price=None, **providers
        )
        assert decision.allowed

    async def test_scoped_to_kiwoom_only(self, master_on, monkeypatch):
        """coin has no equivalent coordinator/fill-tracker — a coin BUY must
        not be denied by this link even with the real (None) coordinator."""
        import app.dependencies as deps

        monkeypatch.setattr(deps, "_trading_coordinator_instance", None)
        providers = _providers()
        providers.pop("coordinator_active_provider")
        decision = await check_autonomy(
            "coin", action="BUY", quantity=1, entry_price=1_000, **providers
        )
        assert decision.check != "coordinator_active"


class TestCoordinatorCheckNeverBlocksHitl:
    """F4b I6 scoping guarantee: check_autonomy is the SINGLE policy point
    for AUTONOMOUS execution only (module docstring). A human's manual
    decision goes through `approval.submit_decision`
    (actor='user') — including the injector's own actor='system' call INTO
    it after its own gate re-check — and that function never calls
    check_autonomy itself. So the coordinator-active link added inside
    check_autonomy cannot gate a manual HITL approval: that code path
    doesn't run through this module at all.
    """

    def test_submit_decision_never_calls_check_autonomy(self):
        import inspect

        from app.api.routes import approval

        src = inspect.getsource(approval.submit_decision) + inspect.getsource(
            approval._submit_decision_locked
        )
        assert "check_autonomy" not in src

    async def test_hitl_mode_denied_before_coordinator_check_is_ever_reached(
        self, master_on, monkeypatch
    ):
        """Belt-and-braces: even if check_autonomy were ever invoked for a
        non-autonomous mode, market_mode (check 2) fails first — the new
        coordinator link (check 5) is unreachable for it, so it can never be
        the reason a hitl-mode request is denied."""
        import app.dependencies as deps

        monkeypatch.setattr(deps, "_trading_coordinator_instance", None)
        providers = _providers(mode="hitl")
        providers.pop("coordinator_active_provider")  # exercise the REAL default
        decision = await check_autonomy(
            "kiwoom", action="BUY", quantity=10, entry_price=50_000, **providers
        )
        assert not decision.allowed
        assert decision.check == "market_mode"


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
    """SELL/REDUCE/HOLD/WATCH don't grow exposure — caps 6/7 don't apply."""
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
        # 통합: 기본 프로바이더 조회 실패 → 게이트 deny (fail-closed).
        # S-1/D3: the breaker is now scoped to POSITION_INCREASING_ACTIONS,
        # so this must exercise a BUY/ADD (HOLD would now legitimately skip
        # the breaker entirely — see
        # TestDailyLossBreakerScopedToPositionIncreasingActions).
        self._mock_client(monkeypatch, realized_pnl=0,
                          pnl_exc=RuntimeError("mockapi down"))
        providers = _providers()
        providers.pop("daily_loss_provider")  # 기본 프로바이더 사용
        decision = await check_autonomy(
            "kiwoom", action="BUY", quantity=None, entry_price=None, **providers
        )
        assert decision.allowed is False
        assert decision.check == "daily_loss_breaker"


class TestDefaultPositionsCountProvider:
    """F4b I2: the kiwoom positions-count provider must count F3 pending-fill
    BUY orders too. The account-balance snapshot it's built on is ~30s
    cached and blind to a BUY that's been placed but not yet (fully)
    filled — a burst of autonomous BUYs could blow past max_open_positions
    before the cache catches up. Union in tickers the coordinator's fill
    tracker is still watching for a BUY fill.
    """

    def _mock_holdings(self, monkeypatch, tickers):
        from unittest.mock import AsyncMock

        from services.kiwoom.models import AccountBalance, Holding

        client = AsyncMock()
        client.get_account_balance.return_value = AccountBalance(
            holdings=[
                Holding(
                    stk_cd=t, stk_nm=t, hldg_qty=10, avg_buy_prc=50_000,
                    cur_prc=50_000, evlu_amt=500_000, evlu_pfls_amt=0,
                    evlu_pfls_rt=0.0,
                )
                for t in tickers
            ]
        )

        async def fake_get_client():
            return client

        import app.core.kiwoom_singleton as singleton

        monkeypatch.setattr(singleton, "get_shared_kiwoom_client_async", fake_get_client)
        return client

    def _coordinator_with_tracker(self, *tracked_orders):
        from services.trading.pending_order_tracker import PendingOrderTracker

        class FakeCoordinator:
            pass

        coord = FakeCoordinator()
        coord.fill_tracker = PendingOrderTracker()
        for order in tracked_orders:
            coord.fill_tracker.register(order)
        return coord

    def _tracked_order(self, ticker, side="buy", ord_no=None):
        from services.trading.pending_order_tracker import TrackedOrder

        return TrackedOrder(
            ord_no=ord_no or f"ord-{ticker}-{side}",
            ticker=ticker,
            side=side,
            total_quantity=10,
        )

    @pytest.mark.asyncio
    async def test_counts_holdings_plus_pending_buy_ticker(self, monkeypatch):
        # 보유 2 (005930, 035720) ∪ 미체결 BUY 1 distinct ticker (000660) = 3
        self._mock_holdings(monkeypatch, ["005930", "035720"])

        import app.dependencies as deps

        coord = self._coordinator_with_tracker(self._tracked_order("000660", side="buy"))
        monkeypatch.setattr(deps, "_trading_coordinator_instance", coord)

        count = await gate_module._default_positions_count_provider("kiwoom")
        assert count == 3

    @pytest.mark.asyncio
    async def test_pending_buy_overlapping_a_holding_is_not_double_counted(self, monkeypatch):
        self._mock_holdings(monkeypatch, ["005930", "035720"])

        import app.dependencies as deps

        coord = self._coordinator_with_tracker(self._tracked_order("005930", side="buy"))
        monkeypatch.setattr(deps, "_trading_coordinator_instance", coord)

        count = await gate_module._default_positions_count_provider("kiwoom")
        assert count == 2

    @pytest.mark.asyncio
    async def test_pending_sell_is_not_counted(self, monkeypatch):
        self._mock_holdings(monkeypatch, ["005930"])

        import app.dependencies as deps

        coord = self._coordinator_with_tracker(self._tracked_order("035720", side="sell"))
        monkeypatch.setattr(deps, "_trading_coordinator_instance", coord)

        count = await gate_module._default_positions_count_provider("kiwoom")
        assert count == 1

    @pytest.mark.asyncio
    async def test_no_coordinator_falls_back_to_holdings_only(self, monkeypatch):
        self._mock_holdings(monkeypatch, ["005930", "035720"])

        import app.dependencies as deps

        monkeypatch.setattr(deps, "_trading_coordinator_instance", None)

        count = await gate_module._default_positions_count_provider("kiwoom")
        assert count == 2

    async def test_gate_denies_buy_when_pending_fill_pushes_past_cap(
        self, master_on, monkeypatch
    ):
        """Integration: max_open_positions=3 with 2 held + 1 distinct
        pending-BUY ticker = 3 >= 3 -> denied. Without the F3-aware union
        this would read as 2 (comfortably under cap) — exactly the
        cap-exceeded miss I2 exists to catch."""
        self._mock_holdings(monkeypatch, ["005930", "035720"])

        import app.dependencies as deps

        coord = self._coordinator_with_tracker(self._tracked_order("000660", side="buy"))
        coord.is_active = True
        monkeypatch.setattr(deps, "_trading_coordinator_instance", coord)

        from services.trading.models import RiskParameters

        providers = _providers()
        providers.pop("positions_count_provider")  # exercise the REAL default
        providers.pop("coordinator_active_provider")  # exercise the REAL default
        decision = await check_autonomy(
            "kiwoom", action="BUY", quantity=1, entry_price=50_000,
            risk_params_provider=lambda: RiskParameters(max_open_positions=3),
            **providers,
        )
        assert not decision.allowed
        assert decision.check == "max_positions"


def _params(pct=15.0):
    p = RiskParameters()
    p.max_trade_notional_pct = pct
    return p


class TestNotionalPctCap:
    """T1: notional cap is equity-relative (equity × pct), fail-closed on a
    broker/equity lookup failure — replaces the old fixed max_trade_notional_krw."""

    async def test_notional_pct_cap_allows_and_denies(self, master_on):
        async def equity(market):
            return 100_000_000  # ₩100M, pct 15% → cap ₩15M

        # 50×200k=₩10M < 15M → allow
        d = await check_autonomy(
            "kiwoom", action="BUY", quantity=50, entry_price=200_000,
            risk_params_provider=lambda: _params(15.0), account_equity_provider=equity,
            **_providers(),
        )
        assert d.allowed is True

        # 100×200k=₩20M > 15M → deny
        d = await check_autonomy(
            "kiwoom", action="BUY", quantity=100, entry_price=200_000,
            risk_params_provider=lambda: _params(15.0), account_equity_provider=equity,
            **_providers(),
        )
        assert d.allowed is False and d.check == "notional_cap"

    async def test_notional_equity_fetch_fail_fail_closed(self, master_on):
        async def boom(market):
            raise RuntimeError("1700")

        d = await check_autonomy(
            "kiwoom", action="BUY", quantity=1, entry_price=1000,
            risk_params_provider=lambda: _params(15.0), account_equity_provider=boom,
            **_providers(),
        )
        assert d.allowed is False and d.check == "notional_cap"
