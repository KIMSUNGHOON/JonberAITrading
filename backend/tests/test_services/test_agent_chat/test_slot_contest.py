"""슬롯 만석으로 거절된 기회를 기록한다.

2026-08-04에 251970이 3회(합의 0.7435/0.7434/0.7364), 08-05 새벽에
207940이 2회(0.7323/0.7299) 거절됐는데 원장에 그 사실이 없다. 교체가
이득인지 판단할 데이터가 애초에 쌓이지 않는다.

판정하지 않는다. 기록만 한다 -- 게이트 결과/기존 로그/`_notify_gate_denied`는
전부 불변이어야 한다.

브리프 대비 확인된 두 가지 차이(둘 다 이 파일의 테스트가 실제로 강제한다):
1. storage 접근자의 실제 임포트 경로는 `app.dependencies.get_storage_service`
   가 아니라 `services.storage_service.get_storage_service`다 -- 전자는
   존재하지 않는다(app/dependencies.py는 `get_storage()`만 노출).
2. `record_slot_contest`는 그 이름을 함수 본문에서 매번 로컬 임포트하면 안
   되고 모듈 스코프에서 임포트해야 한다 -- 아래
   test_never_raises_when_storage_explodes가 patch("services.agent_chat.
   slot_contest.get_storage_service", ...)로 가로채려는 이름이 바로 그
   모듈 전역이고, 로컬 임포트는 매번 services.storage_service에서 새로
   가져오므로 그 patch를 우회한다(tests/test_services/test_checkpoint_gc.py의
   `sm` fixture 독스트링과 동일한 근거).

또한 TradeDecision.rationale은 브리프 예시엔 없지만 pydantic 모델에서
필수(기본값 없음)라 아래 모든 인스턴스에 채워 넣었다.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Step 1: record_slot_contest 자체
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_records_challenger_and_incumbents(isolated_storage_service):
    from services.agent_chat.slot_contest import record_slot_contest
    from services.agent_chat.models import TradeDecision, DecisionAction

    decision = TradeDecision(
        action=DecisionAction.BUY, confidence=0.63, consensus_level=0.743,
        entry_price=47_000.0, stop_loss=44_180.0, take_profit=50_760.0,
        rationale="test",
    )
    incumbents = [
        {"ticker": "004370", "consensus": 0.71, "unrealized_pnl_pct": -0.46},
        {"ticker": "089860", "consensus": 0.74, "unrealized_pnl_pct": 2.31},
    ]

    await record_slot_contest(ticker="251970", decision=decision, incumbents=incumbents)

    rows = await isolated_storage_service.get_slot_contests()
    assert len(rows) == 1
    assert rows[0]["challenger_ticker"] == "251970"
    assert rows[0]["challenger_consensus"] == pytest.approx(0.743)
    assert len(json.loads(rows[0]["incumbents_json"])) == 2


@pytest.mark.asyncio
async def test_never_raises_when_storage_explodes():
    from services.agent_chat.slot_contest import record_slot_contest
    from services.agent_chat.models import TradeDecision, DecisionAction

    decision = TradeDecision(
        action=DecisionAction.BUY, confidence=0.6, consensus_level=0.7,
        rationale="test",
    )

    with patch("services.agent_chat.slot_contest.get_storage_service",
               AsyncMock(side_effect=RuntimeError("boom"))):
        # 예외가 새어나오면 게이트 경로가 죽는다 — 이 스펙의 유일한 실 위험이다
        await record_slot_contest(ticker="005930", decision=decision, incumbents=[])


# ---------------------------------------------------------------------------
# Step 7: 배선 테스트 + 무해성 테스트
#
# services.agent_chat.coordinator.ChatCoordinator._handle_decision을 실제로
# 구동해 (a) max_positions 거절 시 행이 남고, (b) 다른 사유 거절 시 안 남고,
# (c) 기록이 예외를 던져도 _notify_gate_denied가 호출되고 경로가 정상
# 진행되는지 확인한다. (c)가 가장 중요하다.
# ---------------------------------------------------------------------------


def _decision(consensus: float = 0.7435):
    from services.agent_chat.models import TradeDecision, DecisionAction

    return TradeDecision(
        action=DecisionAction.BUY,
        confidence=0.6,
        consensus_level=consensus,
        entry_price=10_000.0,
        stop_loss=9_400.0,
        take_profit=11_000.0,
        rationale="test",
    )


def _session(ticker: str):
    from services.agent_chat.models import ChatSession

    return ChatSession(ticker=ticker, stock_name="테스트종목")


def _coordinator_with_one_incumbent():
    """실제 max_positions 거절 상황을 흉내낸다 -- 이미 보유 중인 포지션
    하나가 self._position_manager에 잡혀 있는 ChatCoordinator."""
    from services.agent_chat.coordinator import ChatCoordinator
    from services.agent_chat.position_manager import MonitoredPosition

    coord = ChatCoordinator()
    pm = MagicMock()
    pm.get_all_positions.return_value = [
        MonitoredPosition(
            ticker="004370", stock_name="incumbent",
            quantity=10, avg_price=1000, current_price=1046,
            stop_loss=940, take_profit=1100,
        ),
    ]
    coord._position_manager = pm
    return coord


@pytest.mark.asyncio
async def test_max_positions_denial_records_slot_contest(isolated_storage_service):
    """배선 (a): gate.check == "max_positions" 거절이면 행이 남는다."""
    from services.autonomy import GateDecision

    coord = _coordinator_with_one_incumbent()
    gate = GateDecision(allowed=False, reason="portfolio full (5/5)", check="max_positions")
    notifier = MagicMock(is_ready=False)

    with patch("services.agent_chat.coordinator.check_autonomy", AsyncMock(return_value=gate)), \
         patch("services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)):
        await coord._handle_decision("251970", _decision(0.7435), _session("251970"))

    rows = await isolated_storage_service.get_slot_contests()
    assert len(rows) == 1
    assert rows[0]["challenger_ticker"] == "251970"
    assert rows[0]["challenger_consensus"] == pytest.approx(0.7435)
    incumbents = json.loads(rows[0]["incumbents_json"])
    assert len(incumbents) == 1
    assert incumbents[0]["ticker"] == "004370"
    assert incumbents[0]["unrealized_pnl_pct"] == pytest.approx(4.6)


@pytest.mark.asyncio
async def test_other_denial_reason_does_not_record(isolated_storage_service):
    """배선 (b): max_positions이 아닌 사유(예: daily_loss_breaker)는 슬롯
    경합이 아니므로 기록되지 않는다."""
    from services.autonomy import GateDecision

    coord = _coordinator_with_one_incumbent()
    gate = GateDecision(
        allowed=False, reason="daily loss breaker tripped", check="daily_loss_breaker"
    )
    notifier = MagicMock(is_ready=False)

    with patch("services.agent_chat.coordinator.check_autonomy", AsyncMock(return_value=gate)), \
         patch("services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)):
        await coord._handle_decision("207940", _decision(0.7323), _session("207940"))

    rows = await isolated_storage_service.get_slot_contests()
    assert rows == []


@pytest.mark.asyncio
async def test_recording_failure_does_not_break_gate_denied_path():
    """무해성 (c, 가장 중요): 기록 내부(get_storage_service)가 폭발해도
    record_slot_contest 자신의 try/except가 삼키므로 `_notify_gate_denied`가
    여전히 호출되고 `_handle_decision`이 예외 없이 정상 종료돼야 한다.
    isolated_storage_service를 쓰지 않는다 -- get_storage_service 자체가
    mock되어 raise하므로 실제 storage 코드에 도달하지 않는다."""
    from services.autonomy import GateDecision

    coord = _coordinator_with_one_incumbent()
    gate = GateDecision(allowed=False, reason="portfolio full (5/5)", check="max_positions")
    notifier = MagicMock(is_ready=False)

    with patch("services.agent_chat.coordinator.check_autonomy", AsyncMock(return_value=gate)), \
         patch("services.agent_chat.slot_contest.get_storage_service",
               AsyncMock(side_effect=RuntimeError("storage exploded"))), \
         patch.object(coord, "_notify_gate_denied", AsyncMock()) as mock_notify, \
         patch("services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)):
        # 예외가 새어나오면 이 await 자체가 실패해 테스트가 죽는다.
        await coord._handle_decision("251970", _decision(), _session("251970"))

    mock_notify.assert_awaited_once()


def test_collect_incumbent_snapshot_never_raises_when_position_manager_broken():
    """_collect_incumbent_snapshot도 never-raise여야 한다(브리프 Step 6) --
    position_manager.get_all_positions()가 터져도 빈 리스트를 반환한다."""
    from services.agent_chat.coordinator import ChatCoordinator

    coord = ChatCoordinator()
    pm = MagicMock()
    pm.get_all_positions.side_effect = RuntimeError("boom")
    coord._position_manager = pm

    assert coord._collect_incumbent_snapshot() == []


def test_collect_incumbent_snapshot_empty_before_position_manager_started():
    """start() 이전(self._position_manager is None)에도 안전하게 빈 리스트."""
    from services.agent_chat.coordinator import ChatCoordinator

    coord = ChatCoordinator()
    assert coord._position_manager is None
    assert coord._collect_incumbent_snapshot() == []
