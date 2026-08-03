"""D 원장 회귀 방지 — 2026-08-03 라이브 장애의 헤드라인 약속을 직접 관측한다.

그날 12:50~13:14, LLM 백엔드가 전멸한 채로 토론이 "완료"됐고 중재자 결정이
0.2ms 만에 나왔다. 결과가 `NO_ACTION`/`HOLD`였던 건 설계가 막아서가 아니라
기본값이 우연히 보수적이었을 뿐이다. Task 4(commit `066dd21`/`cadd9d3`)는 그
경로를 끊었다고 **주장**한다 — `_run_analysis_round`가 분석 라운드에서 예외를
투표 전에 전파시키므로, `chat_room.start()`가 그것을 잡아 세션을 CANCELLED로
표시하고, `coordinator._run_discussion`(자율 감시 경로, 2026-08-03에 실제로
탄 경로)이 성공 경로에서만 `persist_session`을 부르니 원장에 아무것도 안
쌓인다는 것이다.

지금까지 이 약속은 제어 흐름에 대한 추론으로만 검증됐다(체인이 끊긴다 ->
그러니 원장도 비어 있을 것이다). 이 테스트는 추론이 아니라 관측이다:
LLM을 실제로 전멸시켜 `coordinator._run_discussion`을 실제로 태우고,
`decision_log.persist_session`이 실제로 쓰는 실 저장소
(`services.storage_service.StorageService`, tmp-file SQLite)를 열어
`agent_chat_decisions` 테이블에 행이 있는지 직접 센다. `persist_session`이나
`storage`를 mock으로 대체하지 않는다 — mock이 "호출 안 됐다"고 말하는 것과,
실제 테이블에 행이 없는 것은 다른 주장이다.

**모더레이터 개시(`chat_room.py:222`)는 이 테스트의 표적이 아니다.** 그 호출은
`gather()` 밖의 직접 `await`라 원래부터 예외가 그대로 전파된다(Task 4 리뷰가
"손대지 말 것"으로 확정, `progress.md` 참고). 이 테스트가 정말 표적으로 삼는
것은 `_run_analysis_round`가 **4개 분석 에이전트 전원 실패**를 감지해 던지는
`raise failures[0]`(chat_room.py:257, 066dd21) 그 자체다 — 그래서 모더레이터의
LLM은 정상으로 두고, discussion_order의 4개 분석 에이전트만 전멸시킨다. 만약
모더레이터까지 실패하게 두면, 모더레이터의 (보호되지 않는) 예외가 먼저 터져
`raise failures[0]`을 절대 실행하지 않고도 테스트가 우연히 통과해 버려서
그 줄의 존재 여부를 구분하지 못한다.

이 테스트가 실제로 그 줄에 민감한지는 코드로 **수행해서** 확인했다(요청된
뮤테이션 테스트) — `raise failures[0]`을 지우고 돌리면:

    before (원본 코드):  1 passed  (행 0개, 세션 CANCELLED, persist_session 미호출)
    after  (raise 삭제):  1 failed (행 1개, action=NO_ACTION이 실제로 저장됨 —
                          정확히 2026-08-03과 같은 모양의 가짜 결정)

지운 뒤 `git checkout -- services/agent_chat/chat_room.py`로 즉시 원복하고
재확인했다(diff 없음, 원본 테스트 다시 통과). 아래 각주에도 관측값을 남긴다.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.llm.backends.base import LLMAllBackendsFailed
from services.agent_chat.chat_room import ChatRoom
from services.agent_chat.coordinator import ChatCoordinator
from services.agent_chat.models import AgentType, MarketContext, SessionStatus
from services.storage_service import StorageService


def _make_context() -> MarketContext:
    return MarketContext(
        ticker="005930",
        stock_name="삼성전자",
        current_price=72500,
        price_change_pct=0.69,
        indicators={"rsi": 35.0, "macd": 150.0, "macd_signal": 120.0},
    )


def _failing_llm() -> MagicMock:
    """4개 분석 에이전트(technical/fundamental/sentiment/risk)에 심을 LLM —
    구조화 투표 경로(`generate_structured`)와 일반 경로(`generate`) 둘 다
    라우터가 완전히 죽었을 때 실제로 던지는 예외로 실패한다."""
    llm = MagicMock(name="failing_llm")
    llm.generate = AsyncMock(
        side_effect=LLMAllBackendsFailed("no available backend for task 'general'")
    )
    llm.generate_structured = AsyncMock(
        side_effect=LLMAllBackendsFailed("no available backend for task 'general'")
    )
    return llm


def _working_llm() -> MagicMock:
    """모더레이터에 심을 LLM — 개시(analyze)와 최종 결정(make_decision)만
    `_call_llm`을 쓰고(announce_voting/announce_decision은 템플릿이라 LLM을
    아예 안 부른다), 최종 action은 응답 문자열이 아니라 투표 집계로 정해지므로
    (moderator_agent.py `_parse_decision`의 `vote_to_action` 주석 참고) 내용은
    임의의 정상 문자열이면 충분하다."""
    llm = MagicMock(name="working_llm")
    llm.generate = AsyncMock(return_value="토론을 시작합니다.")
    return llm


def _wire_total_analyst_outage(room: ChatRoom) -> None:
    for agent_type in room.discussion_order:  # technical/fundamental/sentiment/risk
        room.agents[agent_type].llm = _failing_llm()
    room.agents[AgentType.MODERATOR].llm = _working_llm()


@pytest.mark.asyncio
async def test_total_analyst_llm_outage_persists_no_decision_row(tmp_path):
    context = _make_context()
    room = ChatRoom(ticker="005930", stock_name="삼성전자", context=context)
    _wire_total_analyst_outage(room)

    coordinator = ChatCoordinator()
    storage = StorageService(db_path=str(tmp_path / "ledger.db"))

    with patch(
        "services.agent_chat.decision_log.get_storage_service",
        AsyncMock(return_value=storage),
    ), patch(
        "services.agent_chat.coordinator._alert_llm_failure", AsyncMock()
    ):
        # 2026-08-03에 실제로 탄 경로: 자율 감시 루프의 백그라운드 태스크.
        # 무인 운용을 죽이면 안 되므로 여기서 raise하지 않는다(계약대로).
        await coordinator._run_discussion("005930", room)

    # 관측 지점 — 실 SQLite 파일을 직접 열어 원장 테이블을 센다. mock 호출
    # 카운트가 아니라 실제로 쓰였을 자리에 행이 있는지를 본다.
    rows = await storage.get_agent_chat_decisions(ticker="005930")
    assert rows == [], (
        f"LLM 전멸 상황인데 agent_chat_decisions에 {len(rows)}건이 쌓였다: {rows}"
    )

    # 보조 확인(핵심 주장은 위 실 DB 카운트) — 세션은 CANCELLED로 정직하게
    # 끝나 있어야 한다. "판단 불가"와 "가짜 DECIDED"가 구분된다는 D의 나머지
    # 절반.
    assert room.session.status == SessionStatus.CANCELLED
    assert room.session.decision is None


@pytest.mark.asyncio
async def test_total_analyst_llm_outage_never_reaches_storage_write(tmp_path):
    """위 테스트를 실제 DB 파일이 아니라 저장 계층의 쓰기 메서드 호출 자체로도
    이중 확인한다 — 실 `StorageService` 인스턴스를 그대로 쓰되 그 위에 스파이를
    씌운다(대체 mock이 아니라 실 구현을 감싸는 wraps라서, "행 0개"라는 관측을
    무력화하지 않는다)."""
    context = _make_context()
    room = ChatRoom(ticker="000660", stock_name="SK하이닉스", context=context)
    _wire_total_analyst_outage(room)

    coordinator = ChatCoordinator()
    storage = StorageService(db_path=str(tmp_path / "ledger2.db"))

    with patch(
        "services.agent_chat.decision_log.get_storage_service",
        AsyncMock(return_value=storage),
    ), patch(
        "services.agent_chat.coordinator._alert_llm_failure", AsyncMock()
    ), patch.object(
        storage, "save_agent_chat_decision", wraps=storage.save_agent_chat_decision
    ) as spy_save:
        await coordinator._run_discussion("000660", room)

    spy_save.assert_not_called()
