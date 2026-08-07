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
