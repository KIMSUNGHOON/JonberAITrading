"""MarketType 정리 — KIWOOM만 남는다.

세션용(session_manager)과 장시간용(market_hours) 두 열거형을 모두 본다.
자율 게이트의 KR 경로가 코인 분기 제거 후에도 그대로인지도 함께 확인한다.
"""
import pytest

from services.session_manager import MarketType as SessionMarketType
from services.trading.market_hours import MarketType as HoursMarketType


def test_session_market_type_has_only_kiwoom():
    assert {m.name for m in SessionMarketType} == {"KIWOOM"}
    assert SessionMarketType.KIWOOM.value == "kiwoom"


def test_hours_market_type_has_only_krx():
    assert {m.name for m in HoursMarketType} == {"KRX"}
    assert HoursMarketType.KRX.value == "krx"


@pytest.mark.parametrize("gone", ["STOCK", "COIN"])
def test_removed_session_members_raise(gone):
    with pytest.raises(AttributeError):
        getattr(SessionMarketType, gone)


@pytest.mark.parametrize("gone", ["CRYPTO", "NYSE", "NASDAQ"])
def test_removed_hours_members_raise(gone):
    with pytest.raises(AttributeError):
        getattr(HoursMarketType, gone)


def test_gate_module_has_no_coin_branch():
    """자율 게이트 소스에 coin 분기가 남아 있지 않다."""
    from pathlib import Path

    import services.autonomy.gate as gate_mod

    src = Path(gate_mod.__file__).read_text()
    assert 'market == "coin"' not in src
    assert "get_coin_positions" not in src
