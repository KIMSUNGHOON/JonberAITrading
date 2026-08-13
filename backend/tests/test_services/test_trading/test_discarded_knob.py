"""전략이 산출한 값이 봉인 때문에 버려질 때 로그를 남긴다.

봉인 자체는 의도된 설계다. 문제는 strategy_consensus가 여전히
max_positions를 조정 노브로 패널에 제시한다는 것 — LLM이 도달하지 못할
결정에 추론을 쓰고, 그 사실이 아무에게도 보이지 않는다.

이 아크의 절대 규칙: 관측만 추가한다, 매매 행동은 절대 바꾸지 않는다.
max_open_positions는 GATE_PROTECTED_FIELDS에 봉인돼 있고 이 태스크 이후에도
계속 봉인이어야 한다 — 아래 배선 테스트가 실효값 불변을 직접 확인한다.
"""
import pytest
from unittest.mock import patch


def test_logs_when_strategy_value_differs_from_effective():
    from services.trading.strategy_apply import log_discarded_knobs

    with patch("services.trading.strategy_apply.logger") as mock_logger:
        log_discarded_knobs(
            strategy_values={"max_positions": 6},
            effective_values={"max_open_positions": 5},
        )

    calls = [c for c in mock_logger.info.call_args_list
             if c.args and c.args[0] == "strategy_knob_discarded"]
    assert len(calls) == 1
    assert calls[0].kwargs["knob"] == "max_positions"
    assert calls[0].kwargs["voted"] == 6
    assert calls[0].kwargs["effective"] == 5


def test_no_log_when_values_agree():
    from services.trading.strategy_apply import log_discarded_knobs

    with patch("services.trading.strategy_apply.logger") as mock_logger:
        log_discarded_knobs(
            strategy_values={"max_positions": 5},
            effective_values={"max_open_positions": 5},
        )

    calls = [c for c in mock_logger.info.call_args_list
             if c.args and c.args[0] == "strategy_knob_discarded"]
    assert calls == []


def test_never_raises_on_malformed_input():
    from services.trading.strategy_apply import log_discarded_knobs
    log_discarded_knobs(strategy_values=None, effective_values={})  # 예외 없이 반환


def test_never_raises_when_values_are_wrong_type():
    """never-raise는 dict 자체가 없을 때만이 아니라, get()이 예외를 던지는
    기형 입력(예: dict가 아닌 값)에서도 지켜져야 한다."""
    from services.trading.strategy_apply import log_discarded_knobs
    log_discarded_knobs(strategy_values="not-a-dict", effective_values={"max_open_positions": 5})


def test_wired_into_apply_strategy_to_risk_params():
    """Step5 배선: EOD 패널이 산출한 전략(TradingStrategy 기본값 max_positions=10)을
    RiskParameters(기본값 max_open_positions=5)에 매핑할 때, 불일치가 로그로
    관측돼야 한다 — 그리고 그 관측이 실효값(max_open_positions)을 절대
    바꾸지 않는다는 것을 봉인 검증으로 함께 확인한다.

    뮤테이션 검증: apply_strategy_to_risk_params 안의 log_discarded_knobs
    호출을 지우면 이 테스트는 red가 된다 (calls == [] 가 되어 len(calls)==1
    단언이 실패).
    """
    from services.trading.models import RiskParameters
    from services.trading.strategy import TradingStrategy
    from services.trading.strategy_apply import apply_strategy_to_risk_params

    risk_params = RiskParameters()
    before = risk_params.max_open_positions
    strategy = TradingStrategy()
    voted = strategy.position_sizing.max_positions
    assert voted != before, "test fixture assumption: strategy/effective defaults must differ"

    with patch("services.trading.strategy_apply.logger") as mock_logger:
        apply_strategy_to_risk_params(strategy, risk_params)

    # 실효값 불변 — 봉인은 이 태스크로도 깨지지 않는다.
    assert risk_params.max_open_positions == before

    calls = [c for c in mock_logger.info.call_args_list
             if c.args and c.args[0] == "strategy_knob_discarded"]
    assert len(calls) == 1
    assert calls[0].kwargs["knob"] == "max_positions"
    assert calls[0].kwargs["field"] == "max_open_positions"
    assert calls[0].kwargs["voted"] == voted
    assert calls[0].kwargs["effective"] == before


def test_wired_call_silent_when_strategy_agrees_with_effective():
    """전략의 max_positions가 우연히 실효값과 같으면 조용해야 한다(합의는
    무음이라는 규칙이 배선 지점에서도 지켜지는지)."""
    from services.trading.models import RiskParameters
    from services.trading.strategy import TradingStrategy
    from services.trading.strategy_apply import apply_strategy_to_risk_params

    risk_params = RiskParameters()
    strategy = TradingStrategy()
    strategy.position_sizing.max_positions = risk_params.max_open_positions

    with patch("services.trading.strategy_apply.logger") as mock_logger:
        apply_strategy_to_risk_params(strategy, risk_params)

    calls = [c for c in mock_logger.info.call_args_list
             if c.args and c.args[0] == "strategy_knob_discarded"]
    assert calls == []
