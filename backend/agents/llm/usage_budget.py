"""토론 1건에 걸리는 사용량 한도 대기 **예산**.

상한 300초의 근거는 **신선도**다 — 멈췄던 토론은 멈춘 시점의 가격·차트를 들고
있어서, 그보다 오래 기다렸다 재개하면 낡은 값으로 매매를 결정한다. 그런데
신선도는 *토론이 시작된* 시점부터 낡는 것이지 *각 LLM 호출이 시작된* 시점부터
낡는 게 아니다.

원래 구현은 상한을 `router.generate()` **호출 1건**에 붙였다. 토론 한 번은 LLM을
순차로 약 15회 부른다(모더레이터 개시 + 분석 4 + 토론 2라운드×(응답 4 + 요약) +
투표 안내 + 투표 4 + 최종 결정). 한도가 지속되면 그 대기가 누적돼 토론 하나가
한 시간을 넘기면서도 "5분 신선도"를 주장하게 된다. 게다가 그 대기는
`PositionManager._monitor_loop` 앞에 **인라인**으로 앉는다
(`_monitor_loop` → `_check_all_positions` → `_check_position` → `_handle_event`
→ `_trigger_discussion` → `start_manual_discussion(wait=True)` → `room.start()`,
전부 맨 await) — 즉 실 포지션 감시 자체가 그동안 멈춘다.

그래서 상한을 **토론 단위 예산**으로 옮긴다. `chat_room.start()`가 토론 시작
시점에 데드라인(`now + 300`)을 세우고, `router.generate()`는 자기 한도 대기를
남은 예산으로 clamp한다. 첫 호출이 예산을 다 쓰면 이후 호출들은 새 300초를
시작하지 않고 즉시 실패한다.

**미설정(ContextVar가 비어 있음) = 종전 그대로.** 스캐너·발굴 등 토론 밖의 모든
호출은 호출당 300초 상한을 그대로 쓴다.

**ContextVar를 `router.py`가 아니라 이 모듈에 두는 이유**: 예산을 세우는 쪽은
서비스 계층(`services/agent_chat/chat_room.py`)이고 읽는 쪽은 라우터다. 이
모듈은 표준 라이브러리 외에 아무것도 import하지 않으므로, 어느 쪽에서 가져가도
라우터 구성(설정 로드·백엔드 생성)을 함께 끌고 오지 않는다.

**시계**: 데드라인은 라우터가 쓰는 시계(`Router.now()`, 기본 `time.monotonic`)
위의 절대 시각이다. 라우터가 테스트용 시계를 주입받을 수 있으므로 예산을 세우는
쪽도 반드시 `Router.now()`에서 현재 시각을 읽어야 한다 — `time.monotonic()`을
따로 부르면 두 시계가 어긋나 예산이 즉시 만료되거나 영원히 만료되지 않는다.
"""
from contextvars import ContextVar, Token
from typing import Optional

import structlog

logger = structlog.get_logger()

# 감시 주기(1분)의 5배. 신선도에서 유도된 값이다 — 임의로 늘리지 마라.
USAGE_LIMIT_WAIT_SECONDS = 300

_deadline: ContextVar[Optional[float]] = ContextVar(
    "llm_usage_limit_deadline", default=None
)


def set_deadline(deadline: float) -> Token:
    """이 컨텍스트(그리고 여기서 파생될 태스크들)의 예산 데드라인을 세운다.

    `asyncio.gather`/`create_task`가 만드는 자식 태스크는 **생성 시점의
    컨텍스트를 복사**하므로, 토론 안에서 병렬로 도는 4개 분석 에이전트가
    같은 예산을 나눠 쓴다(자식이 다시 set해도 부모로는 새지 않는다).

    반환된 토큰은 반드시 `reset_deadline`에 `finally`로 돌려준다.
    """
    return _deadline.set(deadline)


def reset_deadline(token: Token) -> None:
    """예산을 토큰 이전 값으로 되돌린다. **절대 raise하지 않는다** — 이 호출은
    `finally`에서 일어나므로, 여기서 예외가 나면 토론 실패의 진짜 사유를
    덮어써 버린다."""
    try:
        _deadline.reset(token)
    except ValueError:
        # 토큰이 다른 컨텍스트에서 만들어졌다(정상 흐름에서는 일어나지 않는다).
        # 예산이 남아 새는 것만은 막는다.
        _deadline.set(None)
        logger.warning("llm_usage_budget_reset_foreign_token")


def get_deadline() -> Optional[float]:
    """현재 컨텍스트의 예산 데드라인. `None`이면 예산 없음(호출당 상한 사용)."""
    return _deadline.get()
