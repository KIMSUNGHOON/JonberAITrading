"""슬롯 만석 거절 기록 — 판정하지 않고 기록만 한다.

포트폴리오가 이미 5종목(max_positions)로 가득 차 있으면 자율 게이트는 새
BUY/ADD 기회를 지금 보유 중인 것과 비교조차 하지 않고 그대로 거절한다.
2026-08-04에 251970이 합의 0.7435/0.7434/0.7364로 3회, 08-05 새벽에 207940이
0.7323/0.7299로 2회 거절됐지만 원장 어디에도 흔적이 없다 — "교체했다면
나았을까"를 나중에 답할 데이터 자체가 없다.

교체(swap) 판정식이 언젠가 쓰인다면 비교 대상은 여기 남는 값들이다. 지금
기록해 두면 몇 주 뒤 소급 시뮬로 답할 수 있다. 지금 문턱을 정하는 것은
데이터 없이 정하는 것이다.

호출 지점은 services/agent_chat/coordinator.py의 게이트 거절 분기다
(services/autonomy/gate.py가 아니다 -- check_autonomy는 ticker도 decision도
받지 않아 그 시그니처로는 이 기록을 만들 수 없다).
"""
from __future__ import annotations

import json
import uuid
from datetime import date

import structlog

# Module-level import (not a local import inside the function) is
# deliberate: tests patch "services.agent_chat.slot_contest.
# get_storage_service" to simulate storage failure (see
# tests/test_services/test_agent_chat/test_slot_contest.py), and that only
# intercepts a name that lives in THIS module's own namespace at call time
# (same convention documented in tests/test_services/test_checkpoint_gc.py's
# `sm` fixture). A per-call "from services.storage_service import
# get_storage_service" inside the function body would re-resolve straight
# from services.storage_service every time and silently bypass the patch.
from services.storage_service import get_storage_service

logger = structlog.get_logger()


async def record_slot_contest(*, ticker: str, decision, incumbents: list[dict]) -> None:
    """Best-effort. 절대 raise하지 않는다 — 관측이 게이트 경로를 죽이면
    이 스펙 전체가 순손실이다."""
    try:
        storage = await get_storage_service()
        await storage.insert_slot_contest(
            id=str(uuid.uuid4()),
            trade_date=date.today().isoformat(),
            challenger_ticker=ticker,
            challenger_action=getattr(decision.action, "value", str(decision.action)),
            challenger_consensus=decision.consensus_level,
            challenger_confidence=decision.confidence,
            challenger_entry_price=decision.entry_price,
            challenger_stop_loss=decision.stop_loss,
            challenger_take_profit=decision.take_profit,
            incumbents_json=json.dumps(incumbents, ensure_ascii=False),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "slot_contest_record_failed",
            ticker=ticker, error=str(e), error_type=type(e).__name__,
        )
