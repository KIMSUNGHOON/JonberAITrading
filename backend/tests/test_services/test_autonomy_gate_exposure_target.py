from unittest.mock import AsyncMock, patch

import pytest

from services.autonomy.gate import check_autonomy
from services.trading.models import RiskParameters


def _providers(**over):
    base = dict(
        # check 2 (market_mode) requires the literal string "autonomous"
        # (services/autonomy/gate.py: `if mode != "autonomous"`) -- the
        # brief's draft used "active", which check 2 rejects outright and
        # never reaches check 8 at all. Fixed here per the brief's own
        # instruction to keep the property (all pre-checks pass) while
        # correcting the call site.
        mode_provider=AsyncMock(return_value="autonomous"),
        paper_provider=AsyncMock(return_value=True),
        daily_loss_provider=AsyncMock(return_value=0.0),
        positions_count_provider=AsyncMock(return_value=1),
        held_tickers_provider=AsyncMock(return_value=set()),
        coordinator_active_provider=AsyncMock(return_value=True),
        account_equity_provider=AsyncMock(return_value=1_000_000.0),
        risk_params_provider=lambda: RiskParameters(),
    )
    base.update(over)
    return base


async def _call(**over):
    with patch("services.autonomy.gate.get_settings") as gs:
        gs.return_value.AUTONOMY_ENABLED = True
        gs.return_value.REGIME_EXPOSURE_ENABLED = over.pop("enabled", True)
        return await check_autonomy(
            "kiwoom", action="BUY", quantity=10, entry_price=1000.0,
            ticker="005930", **_providers(**over),
        )


@pytest.mark.asyncio
async def test_allows_when_projected_is_under_target():
    """주식 100,000 + 주문 10,000 = 110,000 < 목표 55% × 1,000,000."""
    d = await _call(
        exposure_target_provider=AsyncMock(return_value=0.55),
        stock_value_provider=AsyncMock(return_value=100_000.0),
    )
    assert d.allowed is True


@pytest.mark.asyncio
async def test_denies_when_projected_exceeds_target():
    """주식 545,000 + 주문 10,000 = 555,000 > 550,000."""
    d = await _call(
        exposure_target_provider=AsyncMock(return_value=0.55),
        stock_value_provider=AsyncMock(return_value=545_000.0),
    )
    assert d.allowed is False
    assert d.check == "exposure_target"


@pytest.mark.asyncio
async def test_absent_judgment_skips_the_check():
    """판정 없음(None)은 거절이 아니라 스킵이다 — 기존 천장이 남는다."""
    d = await _call(
        exposure_target_provider=AsyncMock(return_value=None),
        stock_value_provider=AsyncMock(return_value=999_999_999.0),
    )
    assert d.allowed is True


@pytest.mark.asyncio
async def test_read_error_denies_fail_closed():
    """조회 오류는 거절이다. 부재와 절대 합치지 않는다."""
    d = await _call(
        exposure_target_provider=AsyncMock(side_effect=RuntimeError("db down")),
        stock_value_provider=AsyncMock(return_value=0.0),
    )
    assert d.allowed is False
    assert d.check == "exposure_target"


@pytest.mark.asyncio
async def test_stock_value_error_denies_fail_closed():
    d = await _call(
        exposure_target_provider=AsyncMock(return_value=0.55),
        stock_value_provider=AsyncMock(side_effect=RuntimeError("db down")),
    )
    assert d.allowed is False
    assert d.check == "exposure_target"


@pytest.mark.asyncio
async def test_kill_switch_off_skips_the_check_entirely():
    """킬스위치가 꺼지면 프로바이더를 부르지도 않는다."""
    target = AsyncMock(return_value=0.01)
    d = await _call(
        enabled=False,
        exposure_target_provider=target,
        stock_value_provider=AsyncMock(return_value=999_999_999.0),
    )
    assert d.allowed is True
    target.assert_not_awaited()


@pytest.mark.asyncio
async def test_sell_is_immune_to_the_exposure_check():
    """매도는 어떤 새 조건도 통과해야 한다 — 손절이 막히면 안 된다."""
    target = AsyncMock(return_value=0.01)
    with patch("services.autonomy.gate.get_settings") as gs:
        gs.return_value.AUTONOMY_ENABLED = True
        gs.return_value.REGIME_EXPOSURE_ENABLED = True
        d = await check_autonomy(
            "kiwoom", action="SELL", quantity=10, entry_price=1000.0,
            ticker="005930",
            **_providers(exposure_target_provider=target,
                         stock_value_provider=AsyncMock(return_value=999_999_999.0)),
        )
    assert d.allowed is True
    target.assert_not_awaited()


@pytest.mark.asyncio
async def test_target_is_a_fraction_not_a_percent():
    """`/100.0`을 위 notional_cap에서 복사해 오면 목표가 0.0055가 되어
    아래의 '통과해야 하는' 주문까지 막힌다.

    주식 300,000 + 주문 10,000 = 310,000 < 0.55 × 1,000,000 = 550,000 → 통과.
    /100.0을 하면 cap이 5,500이 되어 310,000이 초과로 잡히고 거절된다."""
    d = await _call(
        exposure_target_provider=AsyncMock(return_value=0.55),
        stock_value_provider=AsyncMock(return_value=300_000.0),
    )
    assert d.allowed is True, "목표는 분율(0.55)이다 — /100.0을 하면 안 된다"


# ---------------------------------------------------------------------------
# 리뷰 후속 (a): target 범위 위생 검사. 행에 55.0(퍼센트)이 잘못 들어오면
# exposure_cap = 55.0 * equity 로 폭주해 검사 8이 로그 한 줄 없이 영구
# 무력화된다. 쓰기 경로가 [0.02, 0.80]으로 클램프하니 지금은 발생할 수 없지만,
# 단위 계약을 "가정"에서 "집행"으로 바꾸는 보험이다.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_target", [55.0, 1.5, 0.0, -0.1])
async def test_target_out_of_fraction_range_denies_fail_closed(bad_target):
    """0 < target <= 1이 아니면 거절 -- 부재(None)와는 다른 경로다."""
    d = await _call(
        exposure_target_provider=AsyncMock(return_value=bad_target),
        stock_value_provider=AsyncMock(return_value=100_000.0),
    )
    assert d.allowed is False
    assert d.check == "exposure_target"


@pytest.mark.asyncio
async def test_target_at_upper_bound_one_is_accepted():
    """1.0(=100%)은 유효한 경계값이다 -- 배타적으로 거절하면 안 된다."""
    d = await _call(
        exposure_target_provider=AsyncMock(return_value=1.0),
        stock_value_provider=AsyncMock(return_value=100_000.0),
    )
    assert d.allowed is True


# ---------------------------------------------------------------------------
# 리뷰 후속 (b): stock_value_provider가 None을 돌려주는 분기(스펙 밖으로
# 추가한 유일한 분기)의 커버리지. target=None(판정 부재/스킵)과 혼동하면
# 안 된다 -- 이건 "목표는 있는데 현재 주식가치를 모른다"이다.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stock_value_none_denies_fail_closed():
    d = await _call(
        exposure_target_provider=AsyncMock(return_value=0.55),
        stock_value_provider=AsyncMock(return_value=None),
    )
    assert d.allowed is False
    assert d.check == "exposure_target"


# ---------------------------------------------------------------------------
# Important 리뷰픽스: `_default_stock_value_provider`는 `balance.evlu_amt`
# (체결·보유된 주식)만 보고 접수됐지만 미체결인 BUY를 놓친다. 검사 7(건별
# 상한)은 이게 무해하지만 검사 8은 **누적** 상한이라 이 지점에서 정확히
# 깨진다 -- 같은 49분 재평가 주기에서 여러 종목이 BUY로 의결되면 각 요청이
# 동일한 스테일 stock_value를 보고 각자 건별 상한 안에서 통과해, 누적으로는
# 목표를 초과해 안착한다. 검사 6의 `_default_positions_count_provider`가
# `coordinator.fill_tracker.tracking()` 합집합으로 이미 푼 문제라
# (gate.py:205-220), 같은 소스·같은 패턴을 따른다.
# ---------------------------------------------------------------------------


def _mock_kiwoom_balance(monkeypatch, evlu_amt):
    from services.kiwoom.models import AccountBalance

    client = AsyncMock()
    client.get_account_balance.return_value = AccountBalance(evlu_amt=evlu_amt)

    async def fake_get_client():
        return client

    import app.core.kiwoom_singleton as singleton

    monkeypatch.setattr(singleton, "get_shared_kiwoom_client_async", fake_get_client)
    return client


def _coordinator_with_pending_buy(total_quantity, filled_quantity, limit_price):
    from services.trading.pending_order_tracker import PendingOrderTracker, TrackedOrder

    class FakeCoordinator:
        pass

    coord = FakeCoordinator()
    coord.fill_tracker = PendingOrderTracker()
    coord.fill_tracker.register(
        TrackedOrder(
            ord_no="ord-pending-buy",
            ticker="000660",
            side="buy",
            total_quantity=total_quantity,
            filled_quantity=filled_quantity,
            limit_price=limit_price,
        )
    )
    return coord


class TestDefaultStockValueProviderIncludesPendingBuys:
    @pytest.mark.asyncio
    async def test_adds_unfilled_buy_notional_to_held_value(self, monkeypatch):
        from services.autonomy.gate import _default_stock_value_provider

        _mock_kiwoom_balance(monkeypatch, evlu_amt=500_000)

        import app.dependencies as deps

        coord = _coordinator_with_pending_buy(
            total_quantity=100, filled_quantity=0, limit_price=1_000.0
        )
        monkeypatch.setattr(deps, "_trading_coordinator_instance", coord)

        value = await _default_stock_value_provider("kiwoom")
        # 보유 500,000 + 미체결 100주 × 1,000 = 600,000
        assert value == 600_000.0

    @pytest.mark.asyncio
    async def test_partially_filled_buy_counts_only_the_remainder(self, monkeypatch):
        """60/100주가 이미 체결됐다면 그 60주는 이미 balance.evlu_amt에
        반영돼 있다 -- 남은 40주만 미반영분으로 더해야 이중 계산이 안 된다."""
        from services.autonomy.gate import _default_stock_value_provider

        _mock_kiwoom_balance(monkeypatch, evlu_amt=500_000)

        import app.dependencies as deps

        coord = _coordinator_with_pending_buy(
            total_quantity=100, filled_quantity=60, limit_price=1_000.0
        )
        monkeypatch.setattr(deps, "_trading_coordinator_instance", coord)

        value = await _default_stock_value_provider("kiwoom")
        # 보유 500,000 + 미체결 잔량 40주 × 1,000 = 540,000
        assert value == 540_000.0

    @pytest.mark.asyncio
    async def test_gate_denies_when_pending_buy_pushes_projected_past_target(
        self, monkeypatch
    ):
        """미체결 100,000을 빼면 510,000 + 10,000(이번 주문) = 520,000 < 550,000
        → 통과. 포함하면 600,000 + 10,000 = 610,000 > 550,000 → 거절.

        `stock_value_provider`를 오버라이드하지 않고 실제 기본 프로바이더를
        태워 종단으로 검증한다 -- 미체결 합산이 빠지면(리그레션) 이 테스트가
        실제로 실패한다."""
        _mock_kiwoom_balance(monkeypatch, evlu_amt=500_000)

        import app.dependencies as deps

        coord = _coordinator_with_pending_buy(
            total_quantity=100, filled_quantity=0, limit_price=1_000.0
        )
        monkeypatch.setattr(deps, "_trading_coordinator_instance", coord)

        d = await _call(exposure_target_provider=AsyncMock(return_value=0.55))
        assert d.allowed is False
        assert d.check == "exposure_target"

    @pytest.mark.asyncio
    async def test_gate_allows_the_same_order_without_the_pending_buy(
        self, monkeypatch
    ):
        """대조군: 미체결 BUY가 없으면(코디네이터 미존재) 같은 주문은
        통과한다 -- 위 거절이 미체결분 때문이지 다른 이유가 아님을 보인다."""
        _mock_kiwoom_balance(monkeypatch, evlu_amt=500_000)

        import app.dependencies as deps

        monkeypatch.setattr(deps, "_trading_coordinator_instance", None)

        d = await _call(exposure_target_provider=AsyncMock(return_value=0.55))
        assert d.allowed is True
