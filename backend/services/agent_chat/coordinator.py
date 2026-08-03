"""
Chat Coordinator

Manages multiple chat rooms and coordinates with the trading system.
Handles watch list monitoring, opportunity detection, and trade execution.
"""

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Callable

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agents.llm.backends.base import LLMAllBackendsFailed
from services.agent_chat.models import (
    ChatSession,
    DecisionAction,
    MarketContext,
    SessionStatus,
    TradeDecision,
)
from services.agent_chat.chat_room import ChatRoom
from services.agent_chat.decision_log import persist_session
from services.autonomy import check_autonomy
from services.session_manager import (
    MarketType as SmMarketType,
    SessionStatus as SmSessionStatus,
    get_session_manager,
)
from services.storage_service import get_storage_service
from services.trading.market_hours import is_krx_open_cached
from services.trading.models import ActivityType

# -------------------------------------------
# Room-created hooks
# -------------------------------------------
# Lets outer layers (e.g. the WebSocket route) wire ChatRoom callbacks the
# moment a room is created — for BOTH the watch-list auto path and manual
# /discuss — without the coordinator importing route modules (no cycle).

_room_created_hooks: List[Callable] = []


def register_room_created_hook(hook: Callable) -> None:
    """Register a callable invoked with each newly created ChatRoom."""
    _room_created_hooks.append(hook)


def _fire_room_created(room: "ChatRoom") -> None:
    for hook in _room_created_hooks:
        try:
            hook(room)
        except Exception as e:
            logger.warning("room_created_hook_failed", error=str(e))


# -------------------------------------------
# Session-SSOT mirror (P4-2, session-ssot Phase P4)
# -------------------------------------------
# ChatSession lifecycle -> SessionManager (SM) mirroring. Additive: the
# discussion's own read/write paths (_session_history, _active_rooms,
# decision_log.persist_session) are completely unchanged by this -- it
# purely gives every discussion room a companion row in SM's
# analysis_sessions table (kind="discussion", filtered out of every
# analysis-only scan by P4-1's kind column) so a later phase can read
# discussions through the same SM surface analysis sessions already use.
#
# SM's SessionStatus enum keeps its existing 5 values (no new member for
# discussions): every non-terminal agent-chat status (INITIALIZING/
# ANALYZING/DISCUSSING/VOTING) maps to SM RUNNING, with the real phase
# carried in state["sub_status"] instead. DECIDED -> COMPLETED;
# CANCELLED/TIMEOUT -> CANCELLED.
_SM_TERMINAL_STATUS: Dict[SessionStatus, SmSessionStatus] = {
    SessionStatus.DECIDED: SmSessionStatus.COMPLETED,
    SessionStatus.CANCELLED: SmSessionStatus.CANCELLED,
    SessionStatus.TIMEOUT: SmSessionStatus.CANCELLED,
}


async def _register_sm_discussion(room: "ChatRoom") -> None:
    """Register a freshly-created discussion room with the SessionManager
    and wire lifecycle mirror callbacks onto it.

    Called once per room, between construction and the (task-scheduled or
    inline) `await room.start()` -- both room-construction call sites
    (_start_discussion for the watch-list auto path, start_manual_discussion
    for BOTH the background and wait=True manual paths) share this single
    choke point, so every discussion entry route ends up with a companion
    SM row and live mirror callbacks.

    Failure-harmless by design (same contract as decision_log.persist_session
    and the mirror_* helpers in services/session_manager.py): an SM outage
    must never break a discussion. create_session's own failure is caught
    and logged here; the mirror callbacks are still wired afterward so no
    call site needs special-casing, and each of THEIR SM calls is caught and
    logged too -- including the KeyError update_state/update_status raise
    fail-loud when a session_id isn't tracked (P2-1), which is exactly what
    happens on every subsequent event once create_session has failed.
    """
    session = room.session

    try:
        sm = await get_session_manager()
        await sm.create_session(
            session_id=session.id,
            market_type=SmMarketType.KIWOOM,
            ticker=room.ticker,
            display_name=room.stock_name or room.ticker,
            kind="discussion",
            stk_cd=room.ticker,
            stk_nm=room.stock_name,
            state={
                "sub_status": session.status.value,
                "chat_snapshot": session.model_dump(mode="json"),
            },
        )
    except Exception as e:
        logger.warning(
            "sm_discussion_register_failed",
            session_id=session.id,
            ticker=room.ticker,
            error=str(e),
        )

    async def _mirror_state(sub_status: str) -> None:
        """Push {sub_status, chat_snapshot} into SM state. chat_snapshot is
        a non-critical key (P2-1), so bursts of these during a fast-moving
        discussion coalesce into one SQLite write per ~1s instead of one per
        message/status event. The serialization boundary is always
        `ChatSession.model_dump(mode="json")` -- never the raw pydantic
        model or a partially-converted dict -- so SM's own SQLite layer
        (`json.dumps(state, default=str)`) always receives JSON-native
        values and its `default=str` fallback never has to (silently)
        mangle a datetime/numpy value.
        """
        try:
            sm = await get_session_manager()
            await sm.update_state(
                session.id,
                {
                    "sub_status": sub_status,
                    "chat_snapshot": session.model_dump(mode="json"),
                },
            )
        except Exception as e:
            logger.warning(
                "sm_discussion_state_mirror_failed",
                session_id=session.id,
                ticker=room.ticker,
                error=str(e),
            )

    async def _on_message(message) -> None:
        # Votes and the moderator's decision announcement arrive as chat
        # messages (message_type VOTE / DECISION) -- there is no separate
        # ChatRoom callback for them (mirrors how the WS route in
        # app/api/routes/agent_chat.py derives its 'vote'/'decision' frames
        # from this same on_message/on_status_change pair).
        await _mirror_state(session.status.value)

    async def _on_status_change(status: SessionStatus, sess: ChatSession) -> None:
        await _mirror_state(status.value)

        terminal = _SM_TERMINAL_STATUS.get(status)
        if terminal is not None:
            try:
                sm = await get_session_manager()
                await sm.update_status(session.id, terminal)
            except Exception as e:
                logger.warning(
                    "sm_discussion_status_mirror_failed",
                    session_id=session.id,
                    ticker=room.ticker,
                    status=terminal.value,
                    error=str(e),
                )

    room.on_message(_on_message)
    room.on_status_change(_on_status_change)


# -------------------------------------------
# Session-history read merge (P4-4, session-ssot Phase P4)
# -------------------------------------------
# get_session_history/get_session_by_id used to read exclusively from the
# coordinator's in-memory `_session_history` list (capped at 100, evaporates
# on restart). That list is retired -- both methods now read through the
# same two durable/live sources P4-2/P4-3 already write:
#   - SessionManager (SM, kind="discussion"): running discussions plus any
#     terminal one not yet past SM's TTL/restart-reload window (see
#     services/session_manager.py's COMPLETED_SESSION_TTL and
#     _load_active_sessions -- only RUNNING/AWAITING_APPROVAL rows survive a
#     restart, so SM alone is never a durable history source on its own).
#   - The agent_chat_decisions/agent_chat_transcripts ledger (decision_log.
#     persist_session, P4-3): permanent, survives restart, but only ever
#     gains a row once a discussion actually finishes.
# When both sources have a row for the same session id (the window right
# after a discussion finalizes, before SM's TTL evicts it), the SM row wins
# -- it is the fresher of the two (chat_snapshot is mirrored on every
# message/status event; the ledger row is written once, at finalize).


def _naive_utc(dt: Optional[datetime]) -> datetime:
    """Normalize a (possibly tz-aware) datetime to naive-UTC for cross-source
    sort-key comparison -- SM's AnalysisSession.created_at is tz-aware (UTC),
    while ChatSession's own started_at/created_at (datetime.now() default
    factory) and the ledger's parsed SQLite CURRENT_TIMESTAMP are naive.
    `None` sorts as the oldest possible value rather than raising."""
    if dt is None:
        return datetime.min
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_ledger_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Best-effort parse of a ledger row's `created_at` (SQLite
    CURRENT_TIMESTAMP text, e.g. "2026-07-16 09:00:00"). Returns None on any
    unparseable/missing value rather than raising -- a summary row with an
    unparseable timestamp still renders, it just sorts as oldest."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


# SM RUNNING/COMPLETED/CANCELLED -> agent-chat vocabulary fallback, used only
# when a discussion's SM row is missing state["sub_status"] (an SM row
# written before this mirror existed, or reconcile_stranded_sessions flipping
# a restart-orphaned RUNNING discussion straight to ERROR without touching
# state -- ERROR/AWAITING_APPROVAL have no discussion-native equivalent, so
# both fall back conservatively rather than inventing a new FE vocab word).
_SM_STATUS_TO_AGENT_CHAT_VOCAB: Dict[SmSessionStatus, str] = {
    SmSessionStatus.RUNNING: "discussing",
    SmSessionStatus.AWAITING_APPROVAL: "discussing",
    SmSessionStatus.COMPLETED: "decided",
    SmSessionStatus.CANCELLED: "cancelled",
    SmSessionStatus.ERROR: "cancelled",
}


def _summary_from_chat_session(session: ChatSession, sub_status: Optional[str]) -> dict:
    """The exact shape app/api/routes/agent_chat.py's `_session_to_summary`
    (pre-P4-4) built from a live ChatSession -- reproduced here since this is
    now the coordinator's own return contract (a ledger-only row has no full
    ChatSession to build one from without parsing its transcript JSON per
    list row -- see module docstring above). `sub_status` (when given) is
    SM's own agent-chat-vocabulary status field -- preferred over
    `session.status` itself per the brief (both are normally identical,
    mirrored together in the same write, but sub_status is the one source of
    truth this reader trusts)."""
    return {
        "id": session.id,
        "ticker": session.ticker,
        "stock_name": session.stock_name,
        "status": sub_status or session.status.value,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "total_messages": len(session.all_messages),
        "total_rounds": len(session.rounds),
        "consensus_level": session.consensus_level,
        "decision_action": session.decision.action.value if session.decision else None,
        "decision_confidence": session.decision.confidence if session.decision else None,
    }


def _summary_from_ledger_row(row: dict) -> dict:
    """Same shape from an agent_chat_decisions row. `started_at` is not a
    ledger column (only `trade_date`/`created_at` are), so it is always None
    here; `ended_at` falls back to the row's own `created_at` (persist_session
    writes it synchronously right after the session ends, so it is a close
    proxy). Pre-P4-3 rows have NULL total_messages/total_rounds -> 0 fallback
    (NULL-safety requirement)."""
    created_at = row.get("created_at")
    parsed = _parse_ledger_timestamp(created_at)
    return {
        "id": row.get("id"),
        "ticker": row.get("ticker"),
        "stock_name": row.get("stock_name"),
        "status": row.get("status"),
        "started_at": None,
        "ended_at": parsed.isoformat() if parsed else created_at,
        "total_messages": row.get("total_messages") or 0,
        "total_rounds": row.get("total_rounds") or 0,
        "consensus_level": row.get("consensus_level"),
        "decision_action": row.get("action"),
        "decision_confidence": row.get("confidence"),
    }


# -------------------------------------------
# Trade-outcome discriminator (P2 review gap, 2026-07-14)
# -------------------------------------------


def _trade_actually_resulted(trading_coord, ticker: str, allocation) -> bool:
    """Whether `allocation` (on_trade_approved's return value) represents a
    trade that genuinely executed or was queued — i.e. a real position or
    queue entry resulted — as opposed to TRADE_REJECTED (daily trade limit
    reached, or portfolio sizing to <=0 shares) or ORDER_FAILED (an order
    was placed but the broker filled 0 shares).

    AllocationPlan carries no explicit success/failure field: a queued
    trade always reports quantity=0 (but IS real — see the "Trade queued"
    rationale check below), while a genuinely-filled order and an
    ORDER_FAILED one share the identical quantity>0 shape (the field holds
    the requested/allocated size, not the broker's actual fill). For that
    last case we fall back to the activity log on_trade_approved writes
    synchronously before it returns, and look for the most recent entry for
    this ticker.
    """
    if allocation is None:
        return False

    rationale = getattr(allocation, "rationale", None) or ""
    if rationale.startswith("Trade queued"):
        return True

    quantity = getattr(allocation, "quantity", 0) or 0
    if quantity <= 0:
        return False

    try:
        recent = trading_coord.get_activity_log(limit=10)
    except Exception:
        return True

    for entry in reversed(list(recent or [])):
        if getattr(entry, "ticker", None) != ticker:
            continue
        activity_type = getattr(entry, "activity_type", None)
        return activity_type not in (ActivityType.ORDER_FAILED, "order_failed")

    # No matching log entry found (e.g. a coordinator stub in tests that
    # doesn't model the log) — the quantity>0 result is the best signal we
    # have, so treat it as resulted.
    return True


from services.agent_chat.position_manager import (
    PositionManager,
    get_position_manager,
)

logger = structlog.get_logger()


# LLM 장애 통지 래치 — 감시 주기가 1분이라 래치가 없으면 장애 지속 동안 매분 발송된다.
# 원인 문자열을 키로 1회만 보내고, 복구되면 `clear_llm_failure_latch()`가 지워
# 재발 시 다시 알린다 — reconciler의 원가 드리프트 래치와 같은 잠금/해제
# *패턴*을 따르되, 키는 ticker가 아니라 원인 문자열이다: 완료된 토론 하나가
# LLM 계층 전체의 복구 증거이므로 해제도 전역(clear)이어야 한다(reconciler는
# ticker별 discard가 맞다 — 거긴 종목마다 원가가 독립적으로 어긋나므로).
_LLM_FAILURE_NOTIFIED: set = set()

# 래치 크기 상한. 키를 안정화해도(아래 `_llm_failure_cause_key`) 예상 못 한 변동
# 요소가 남아 있을 수 있으므로 메모리 증가에는 **무조건적인** 상한을 둔다 — 이
# 집합은 best-effort 중복 억제 장치이지 영구 원장이 아니다.
_LLM_FAILURE_NOTIFIED_MAX = 64

_LLM_FAILURE_DIGITS_RE = re.compile(r"\d+")


def _llm_failure_cause_key(exc: Exception) -> str:
    """래치 키를 만든다. **알림 본문이 아니라** 중복 억제 전용이다.

    예전 키는 `str(exc)[:160]`이었다. 그 160자 안에 호출마다 달라지는 값이 하나만
    들어와도 dedup이 통째로 무력화돼 "장애가 지속되는 동안 실패한 토론마다,
    감시 주기(1분)마다 Telegram 1건"이 된다 — 메모리 증가보다 나쁜 실패 모드다.
    그런데 실제로 그 안에 들어오는 변동 요소가 셋이나 된다:

      - **대기 상한 숫자**: 토론 단위 예산(Task 8 Fix 1)이 붙으면서 300 고정이
        아니라 "그 시점에 남은 예산"(60/40/0...)이 된다.
      - **task 이름**: 토론 1건이 LLM을 약 15회 부르고 단계마다 task가 다르므로,
        어느 호출에서 터졌느냐에 따라 문자열이 바뀐다.
      - **CLI 원문 blob**: 한도 리셋 시각 등이 그대로 들어온다(Fix 3이 사유를
        더 잘 보존하게 만들었으므로 변동성은 오히려 커졌다).

    그래서 ①숫자를 전부 `#`로 정규화하고 ②앞 40자만 쓰고 ③예외 타입을 붙인다.
    40자면 라우터가 내는 세 가지 실패 **모양**은 그대로 갈린다
    ("usage limit outlasted ...", "no available backend ...",
    "all backends failed ...") — 성격이 다른 장애는 각자 자기 알림을 받는다.
    반대로 같은 전멸 장애 안에서 백엔드별 세부 사유가 다른 것들은 한 건으로
    합쳐진다. 이건 의도한 트레이드오프다: 운영자가 취할 조치가 동일하고, 알림
    **본문**에는 첫 사유의 전문(160자)이 그대로 실려 세부는 잃지 않는다.
    """
    normalized = _LLM_FAILURE_DIGITS_RE.sub("#", str(exc))
    return f"{type(exc).__name__}:{normalized[:40]}"


def clear_llm_failure_latch() -> None:
    """LLM 호출이 성공하면 호출해 래치를 푼다."""
    _LLM_FAILURE_NOTIFIED.clear()


async def _alert_llm_failure(ticker: str, exc: Exception) -> None:
    """LLM 장애로 토론이 실패했음을 운영자에게 알린다. Best-effort —
    통지 실패가 토론 경로를 더 망가뜨려선 안 된다.

    **claim-then-back-out**으로 래치를 관리한다: dedup 체크와 `add(cause)`를
    맞닿여 동기적으로 실행해(둘 사이에 `await`가 없다) 다른 코루틴이 끼어들
    틈을 없앤다 — 이게 TOCTOU를 막는 장치다. `LLMAllBackendsFailed`는 task와
    최종 에러로 키가 잡혀(agents/llm/router.py) 동시에 실패하는 여러 티커의
    토론이 **같은 cause 문자열**을 공유하므로, add를 발송 확인 뒤로 미루면
    두 코루틴이 나란히 dedup을 통과해 중복 발송된다(재현: 동일 cause로
    `_alert_llm_failure`를 `asyncio.gather`하면 확인 전에는 send_count=2).
    발송이 실제로 실패/미확인으로 끝나는 모든 경로(`is_ready` False,
    `sent` False, 예외)에서는 `discard(cause)`로 되돌려 Finding 1(발송
    미확인 시 영구 래치 금지)을 그대로 지킨다.

    **락을 쓰지 않는 이유**: `asyncio.Lock`으로 체크~발송~커밋 전체를
    감싸면 경쟁은 막지만, 이 함수는 토론 실패 예외 처리기 안에서
    await되므로 느리거나 멈춘 Telegram 요청 하나가 락을 쥔 채 다른 모든
    알림 시도를 그 뒤에 줄 세운다 — 장애 상황에서 알림 자체가 지연·정체될
    위험을 굳이 만드는 셈이다. claim-then-back-out은 블로킹 프리미티브
    없이 경쟁만 닫는다: 대가는 발송이 실제로 실패했을 때 동시 호출자가
    선점된 claim을 보고 그냥 반환한다는 것뿐 — 다음 감시 주기(1분 뒤)에
    재시도되므로 감내할 수 있다.

    **back-out은 `finally`에 둔다(취소 안전)**: `except Exception`은
    `asyncio.CancelledError`를 잡지 않는다(3.8부터 `BaseException`). 토론
    태스크가 `get_telegram_notifier()`나 `send_system_status()` 안에서
    await 중일 때 취소되면, 예전 구조에서는 claim만 남고 메시지는 안 나간
    채 그 사유가 영구히 래치돼(다음 성공 토론까지) 같은 장애가 통째로
    침묵했다. `finally`로 옮기면 취소·예외·조용한 실패 어느 경로든 claim이
    풀리고, 취소는 그대로 전파된다(삼키지 않는다).
    """
    reason = str(exc)[:160]                 # 본문·로그에 실리는 사유(전문에 가깝게)
    cause = _llm_failure_cause_key(exc)     # 래치 키(안정화된 축약)

    # 메모리 하드 상한. 키를 안정화했는데도 상한에 닿았다면 예상 못 한 변동
    # 요소가 남아 있다는 뜻이므로, 무한 증가 대신 래치를 비운다(그 대가는
    # 알림 1건 재발송뿐이다).
    if len(_LLM_FAILURE_NOTIFIED) >= _LLM_FAILURE_NOTIFIED_MAX:
        logger.warning("llm_failure_latch_overflow", size=len(_LLM_FAILURE_NOTIFIED))
        _LLM_FAILURE_NOTIFIED.clear()
    if cause in _LLM_FAILURE_NOTIFIED:
        return
    _LLM_FAILURE_NOTIFIED.add(cause)  # claim (동기, 위 dedup 체크와 맞닿아 있음)

    committed = False
    try:
        from services.telegram import get_telegram_notifier

        notifier = await get_telegram_notifier()
        if not notifier.is_ready:
            logger.warning("llm_failure_alert_notifier_not_ready", ticker=ticker, cause=reason)
            return
        sent = await notifier.send_system_status(
            "error",
            f"LLM 장애로 토론을 완료하지 못했습니다 ({ticker})\n"
            f"사유: {reason}\n"
            f"→ 매매 결정은 내려지지 않았습니다. 복구되면 다음 감시 주기에 재시도합니다.",
        )
        if sent:
            committed = True   # 발송이 **확인된** 유일한 경로 — 여기서만 래치를 유지한다
        else:
            # 예외 없이 실패한 경우(네트워크 순단 등) — 아래 finally가 claim을
            # 되돌려 다음 시도에서 재발송되지만, 이번 실패 자체는 로그로 남긴다.
            logger.warning("llm_failure_alert_not_sent", ticker=ticker, cause=reason)
    except Exception as e:  # noqa: BLE001 — 통지는 절대 경로를 깨뜨리지 않는다
        logger.warning("llm_failure_alert_failed", ticker=ticker, error=str(e))
    finally:
        # 취소(CancelledError)를 포함한 모든 미확인 종료 경로에서 claim을 되돌린다.
        # CancelledError는 여기서 잡히지 않으므로 그대로 전파된다.
        if not committed:
            _LLM_FAILURE_NOTIFIED.discard(cause)


class ChatCoordinator:
    """
    Coordinates agent chat discussions for trading decisions.

    Responsibilities:
    - Monitor watch list stocks for opportunities
    - Create and manage chat rooms for discussions
    - Execute approved trades
    - Track session history
    """

    # Phase4: 캘리브레이션 동적 가중 상수
    _MIN_CALIBRATION_SAMPLES = 5
    _WEIGHT_TILT_MIN = 0.5   # base 대비 하한 배수 (RISK 0.30→최소 0.15, 소거 불가)
    _WEIGHT_TILT_MAX = 1.5

    # 재시작 안전(2026-07-29): _running/check_interval/max_concurrent는 전부
    # 인메모리라 재시작이 생성자 기본값(1분 / 동시 3)으로 되돌렸다. 이
    # 세 개만 SQLite에 남겨 부팅 시 그대로 복원한다.
    _RUNTIME_KEY = "agent_chat:coordinator_state"

    def __init__(
        self,
        check_interval_minutes: int = 1,
        max_concurrent_discussions: int = 3,
        min_discussion_interval_minutes: int = 30,
    ):
        """
        Initialize chat coordinator.

        Args:
            check_interval_minutes: How often to check watch list (default
                1 minute / 60s — monitoring-cadence tuning, 2026-07-15. The
                check itself makes no Kiwoom call (reads stored/periodically
                refreshed watch prices); the discussion throttle
                (min_discussion_interval_minutes + max_concurrent_discussions)
                is the real rate limit, unchanged.
            max_concurrent_discussions: Max simultaneous discussions
            min_discussion_interval_minutes: Min time between discussions for same stock
        """
        self.check_interval = check_interval_minutes
        self.max_concurrent = max_concurrent_discussions
        self.min_interval = timedelta(minutes=min_discussion_interval_minutes)

        # Active chat rooms
        self._active_rooms: Dict[str, ChatRoom] = {}  # ticker -> room

        # P4-4 (session-ssot): the in-memory `_session_history` list was
        # retired -- get_session_history/get_session_by_id now read through
        # SM (kind="discussion") + the durable ledger instead (see the
        # module-level "Session-history read merge" section above).
        self._last_discussion: Dict[str, datetime] = {}  # ticker -> last discussion time

        # First-discussion guarantee: discovery-promoted watches carry
        # composite confidence (~0.65-0.73, below the 0.75 opportunity
        # threshold) and can gap away from target_entry_price at open; and
        # manually-added watches with no target_entry_price (proximity
        # branch has nothing to compare against, confidence is usually 0.5)
        # can likewise never trigger either _detect_opportunity branch
        # (proximity/confidence). Tracks tickers that have already had their
        # guaranteed first review so it fires exactly once per promotion/add
        # (per process — in-memory, re-review-on-restart is acceptable, no
        # persistence needed).
        self._first_reviewed: set[str] = set()

        # Scheduler for periodic checks
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._running = False
        # Loop-liveness heartbeat: set at the top of every executed tick, so a
        # scheduler whose job silently stopped firing (thread died, exception
        # loop, etc.) can be told apart from one that's genuinely idle —
        # `_running=True` alone can't distinguish "still ticking" from "dead".
        self._last_tick: Optional[datetime] = None

        # E2-1: market-gate last-known state, for the transition-only log
        # helper below (None = not yet observed this process).
        self._market_gate_closed: Optional[bool] = None

        # Callbacks
        self._on_decision_callbacks: List[Callable] = []
        self._on_session_complete_callbacks: List[Callable] = []

        # Position manager (will be initialized in start())
        self._position_manager: Optional[PositionManager] = None

        logger.info(
            "chat_coordinator_initialized",
            check_interval=check_interval_minutes,
            max_concurrent=max_concurrent_discussions,
        )

    def on_decision(self, callback: Callable) -> None:
        """Register callback for trading decisions."""
        self._on_decision_callbacks.append(callback)

    def on_session_complete(self, callback: Callable) -> None:
        """Register callback for completed sessions."""
        self._on_session_complete_callbacks.append(callback)

    async def start(self) -> None:
        """Start the coordinator with scheduled monitoring."""
        if self._running:
            logger.warning("chat_coordinator_already_running")
            return

        logger.info("chat_coordinator_starting")

        self._running = True
        try:
            self._scheduler = AsyncIOScheduler()

            # Initialize and start position manager
            self._position_manager = await get_position_manager()
            self._position_manager.set_chat_coordinator(self)
            await self._position_manager.start()

            # Sync positions from account
            await self._position_manager.sync_from_account()

            # Restore persisted stop levels (F3 Task 7) — must run AFTER the sync
            # above so it only ever restores stops onto tickers the broker still
            # confirms are held.
            await self._position_manager.restore_stop_overlay()

            # Schedule periodic watch list check
            self._scheduler.add_job(
                self._check_watch_list,
                'interval',
                minutes=self.check_interval,
                id='watch_list_check',
                next_run_time=datetime.now(),  # Run immediately
            )

            self._scheduler.start()
        except BaseException:
            # CRITICAL 2 (2026-07-29): _running was already flipped True above,
            # before every await that can hang or fail (position manager
            # start/sync, Kiwoom sync, stop-overlay restore). If any of them
            # raises -- or the boot path's wait_for times out and cancels this
            # coroutine mid-flight (CancelledError, a BaseException, not an
            # Exception) -- _running must NOT stay True: resume_if_persisted()
            # has no try/except of its own, so leaving it True means a later
            # manual POST /agent-chat/start hits `if self._running: return`
            # and reports HTTP 200 "started" while nothing actually restarted
            # (scheduler never started, stop overlay never restored). Roll
            # back and re-raise so the caller still sees the real failure.
            self._running = False
            raise

        logger.info(
            "chat_coordinator_started",
            check_interval=self.check_interval,
            positions_monitored=len(self._position_manager.get_all_positions()),
        )
        await self._persist_runtime_state()

    async def stop(self) -> None:
        """Stop the coordinator."""
        if not self._running:
            return

        logger.info("chat_coordinator_stopping")

        self._running = False

        # IMPORTANT 4 (2026-07-29): the persist below must run even if
        # shutdown/stop/cancel raises mid-body -- e.g. a half-started
        # coordinator (CRITICAL 2: _scheduler constructed but never
        # .start()ed) makes shutdown() raise SchedulerNotRunningError before
        # ever reaching the old unconditional persist call. Without the
        # `finally`, memory says _running=False but the persisted blob still
        # says running: True, and the next boot resurrects a coordinator the
        # operator explicitly stopped -- one that runs discussions, votes,
        # and autonomous BUY execution, not just a passive watcher.
        try:
            if self._scheduler:
                self._scheduler.shutdown(wait=False)
                self._scheduler = None

            # Stop position manager
            if self._position_manager:
                await self._position_manager.stop()

            # Cancel active rooms
            for ticker, room in list(self._active_rooms.items()):
                await room.cancel()

            self._active_rooms.clear()

            logger.info("chat_coordinator_stopped")
        finally:
            await self._persist_runtime_state()

    async def _persist_runtime_state(self) -> None:
        """running/check_interval/max_concurrent를 SQLite에 남긴다.

        Best-effort — 저장 실패가 start/stop을 깨뜨려선 안 된다(방어를
        켜는 것이 설정을 기록하는 것보다 중요하다)."""
        try:
            from services.storage_service import get_storage_service

            storage = await get_storage_service()
            await storage.set_app_setting(
                self._RUNTIME_KEY,
                json.dumps(
                    {
                        "running": self._running,
                        "check_interval": self.check_interval,
                        "max_concurrent": self.max_concurrent,
                    }
                ),
            )
        except Exception as e:
            logger.error("chat_coordinator_persist_failed", error=str(e))

    async def resume_if_persisted(self) -> bool:
        """부팅 시 호출 — 마지막으로 running이었으면 저장된 설정으로
        되살린다. 실제로 재개했으면 True, no-op이면 False.

        설정값은 검증한다: check_interval이 0이면 APScheduler가 매초 도는
        폭주가 되고, max_concurrent가 0이면 토론이 영영 안 열린다. 이상한
        값은 무시하고 현재 값(생성자 기본값)을 지킨다.

        예외는 삼키지 않는다 — 호출자(app.main._boot_auto_resume)가 잡아서
        로그와 Telegram에 남긴다."""
        from services.storage_service import get_storage_service

        storage = await get_storage_service()
        blob = await storage.get_app_setting(self._RUNTIME_KEY)
        if not blob:
            logger.info("chat_coordinator_boot_resume_skipped", reason="no_state")
            return False

        data = json.loads(blob) or {}
        if not data.get("running"):
            logger.info("chat_coordinator_boot_resume_skipped", reason="not_running")
            return False

        interval = data.get("check_interval")
        if isinstance(interval, int) and not isinstance(interval, bool) and interval > 0:
            self.check_interval = interval
        concurrent = data.get("max_concurrent")
        if isinstance(concurrent, int) and not isinstance(concurrent, bool) and concurrent > 0:
            self.max_concurrent = concurrent

        logger.info(
            "chat_coordinator_boot_resume",
            check_interval=self.check_interval,
            max_concurrent=self.max_concurrent,
        )
        await self.start()
        return True

    @property
    def position_manager(self) -> Optional[PositionManager]:
        """Get position manager instance."""
        return self._position_manager

    def _log_market_gate_once(self, closed: bool) -> None:
        """Log a market-gate state transition once (E2-1) — never every
        cycle. Small per-file helper (duplicated in position_manager.py by
        design — YAGNI, not worth a shared util for two call sites)."""
        if self._market_gate_closed == closed:
            return
        self._market_gate_closed = closed
        if closed:
            logger.info("market_gate_closed", component="chat_coordinator")
        else:
            logger.info("market_gate_reopened", component="chat_coordinator")

    async def _check_watch_list(self) -> None:
        """Check watch list for discussion opportunities."""
        # FIX NOW Minor (final review): the heartbeat must be set BEFORE the
        # E2 market-closed gate below, not after it — `_last_tick`'s own
        # field docstring promises "set at the top of every executed tick"
        # precisely so a genuinely-idle (market closed) loop can be told
        # apart from a dead one, but the gate used to `return` before this
        # line ever ran, so `_last_tick` froze the instant the market
        # closed and stayed frozen for the entire off-hours stretch — FE's
        # useLoopLiveness read that as a false "LOOP STALE" alarm all
        # night, every night, not just when the loop actually died. A
        # skipped (market-closed) cycle is still proof the scheduler is
        # alive, so it must tick too.
        self._last_tick = datetime.now()

        # E2: 장외에는 자동 토론/감시 사이클 전체를 쉬게 한다(완전 idle 결정).
        # 수동 /discuss와 trading coordinator의 마감 엣지 체인은 게이트 밖.
        if not is_krx_open_cached():
            self._log_market_gate_once(closed=True)
            return
        self._log_market_gate_once(closed=False)

        if not self._running:
            return

        logger.debug("checking_watch_list")

        try:
            # Get active watch list stocks
            watch_list = await self._get_watch_list()

            if not watch_list:
                logger.debug("watch_list_empty")
                return

            # Check each stock for opportunity
            opportunities = []
            for stock in watch_list:
                ticker = stock.get("ticker")
                if not ticker:
                    continue

                # Skip if already discussing
                if ticker in self._active_rooms:
                    continue

                # Skip if recently discussed
                if self._was_recently_discussed(ticker):
                    continue

                # Check if opportunity exists
                should_discuss = await self._detect_opportunity(stock)
                if should_discuss:
                    opportunities.append(stock)

            # Start discussions for opportunities (up to max concurrent)
            available_slots = self.max_concurrent - len(self._active_rooms)
            for stock in opportunities[:available_slots]:
                await self._start_discussion(stock)
                ticker = stock.get("ticker")
                # Mark on ACTUAL start (room present in _active_rooms), not
                # on detect -- so a slot-starved/stale-context skip leaves
                # the ticker eligible to retry the guaranteed review next tick.
                if (stock.get("signal") == "discovery" or stock.get("target_entry_price") is None) \
                        and ticker in self._active_rooms:
                    self._first_reviewed.add(ticker)

        except Exception as e:
            logger.error("watch_list_check_failed", error=str(e))

    async def _get_watch_list(self) -> List[dict]:
        """Get active watch list stocks from trading coordinator."""
        try:
            from app.dependencies import get_trading_coordinator
            trading_coord = await get_trading_coordinator()
            watch_items = trading_coord.get_watch_list()

            # trading_coord.get_watch_list() already filters to ACTIVE-only,
            # so no further status filter is needed here. A redundant
            # `w.status.value == "active"` check used to live in this
            # comprehension — it crashed with AttributeError once watch_list
            # persistence (P2 SSOT prep, 2026-07-14) started restoring entries
            # whose `status` field is a plain str (pydantic's
            # `use_enum_values=True` on WatchedStock converts it on
            # `model_validate`), silently emptying the whole list on every
            # tick after a restart.
            return [
                {
                    "ticker": w.ticker,
                    "stock_name": w.stock_name,
                    "signal": w.signal,
                    "confidence": w.confidence,
                    "current_price": w.current_price,
                    "target_entry_price": w.target_entry_price,
                    "stop_loss": w.stop_loss,
                    "take_profit": w.take_profit,
                }
                for w in watch_items
            ]
        except Exception as e:
            logger.warning("get_watch_list_failed", error=str(e))
            return []

    def _was_recently_discussed(self, ticker: str) -> bool:
        """Check if stock was discussed recently."""
        last_time = self._last_discussion.get(ticker)
        if not last_time:
            return False
        return datetime.now() - last_time < self.min_interval

    async def _detect_opportunity(self, stock: dict) -> bool:
        """
        Detect if a stock presents a trading opportunity.

        Criteria:
        - Price near target entry
        - Significant price movement
        - High confidence signal
        """
        ticker = stock.get("ticker")
        current_price = stock.get("current_price", 0)
        target_price = stock.get("target_entry_price")
        confidence = stock.get("confidence", 0)

        # Phase4: 활성 전략의 기회감지 임계 소비 (best-effort — 조회 실패/전략
        # 없음 = 기존 하드코딩 0.03/0.75로 진행, 거동 불변).
        proximity_pct = 0.03
        min_confidence = 0.75
        try:
            from app.dependencies import get_trading_coordinator

            strategy = (await get_trading_coordinator()).get_strategy()
            if strategy is not None:
                proximity_pct = strategy.entry_conditions.entry_proximity_pct
                min_confidence = strategy.entry_conditions.opportunity_min_confidence
        except Exception:
            pass  # best-effort — 기본 임계로 진행

        # Check if price is near target (within proximity_pct)
        if target_price and current_price:
            price_diff = abs(current_price - target_price) / target_price
            if price_diff <= proximity_pct:
                logger.info(
                    "opportunity_detected_target_reached",
                    ticker=ticker,
                    current=current_price,
                    target=target_price,
                )
                return True

        # Check for high confidence
        if confidence >= min_confidence:
            logger.info(
                "opportunity_detected_high_confidence",
                ticker=ticker,
                confidence=confidence,
            )
            return True

        # 첫 평가 보장: 발굴 승격(signal="discovery") 또는 진입타겟 없는 워치
        # (target=None → 근접 브랜치 영영 못 뜸)는 근접/확신 무관 최소 1회 토론.
        if (stock.get("signal") == "discovery" or target_price is None) \
                and ticker not in self._first_reviewed:
            logger.info("opportunity_detected_first_review", ticker=ticker,
                        reason="discovery" if stock.get("signal") == "discovery" else "no_target")
            return True

        return False

    async def _start_discussion(self, stock: dict) -> None:
        """Start a new discussion for a stock."""
        ticker = stock["ticker"]
        stock_name = stock.get("stock_name", ticker)

        logger.info(
            "starting_discussion",
            ticker=ticker,
            stock_name=stock_name,
        )

        try:
            # Fetch market context
            context = await self._fetch_market_context(ticker, stock_name)

            # A stale context means the real quote fetch failed — never
            # start agents debating/voting on invented numbers (CRITICAL
            # safety fix, 2026-07-14). Skip this cycle; _check_watch_list
            # will retry the ticker on its next pass (no discussion was
            # started, so it isn't throttled by _was_recently_discussed).
            if context.is_stale:
                logger.warning(
                    "discussion_skipped_stale_market_data",
                    ticker=ticker,
                )
                return

            # Create chat room
            room = ChatRoom(
                ticker=ticker,
                stock_name=stock_name,
                context=context,
                # E-3: 활성 전략의 consensus_threshold를 단일 소스(context)에서
                # 그대로 전달 — chat_room.py 기본값(0.75)은 전략 없음/조회
                # 실패 시에만 실제로 쓰인다(context.consensus_threshold도 그
                # 경우 0.75).
                consensus_threshold=context.consensus_threshold,
                agent_weights=await self._compute_agent_weights(),
            )

            # Register callbacks
            room.on_status_change(self._on_room_status_change)
            _fire_room_created(room)

            self._active_rooms[ticker] = room

            # P4-2 (session-ssot): register the room with SessionManager and
            # wire its lifecycle mirror callbacks -- must happen before
            # room.start() is ever awaited (inside _run_discussion below) so
            # no early message/status event can race an unregistered session.
            await _register_sm_discussion(room)

            # Start discussion in background
            asyncio.create_task(self._run_discussion(ticker, room))

        except Exception as e:
            logger.error(
                "start_discussion_failed",
                ticker=ticker,
                error=str(e),
            )

    async def _run_discussion(self, ticker: str, room: ChatRoom) -> None:
        """Run a discussion and handle the result."""
        try:
            session = await room.start()
            clear_llm_failure_latch()

            # Record last discussion time
            self._last_discussion[ticker] = datetime.now()

            # P4-4 (session-ssot): durable persistence only -- the in-memory
            # history list is retired (see module docstring above).
            await persist_session(session)

            # Handle decision
            if session.decision:
                await self._handle_decision(ticker, session.decision, session)

            # Notify callbacks
            for callback in self._on_session_complete_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(session)
                    else:
                        callback(session)
                except Exception as e:
                    logger.warning("session_complete_callback_failed", error=str(e))

        except Exception as e:
            logger.error(
                "discussion_failed",
                ticker=ticker,
                error=str(e),
            )
            # 이 경로는 자동 감시 루프의 백그라운드 태스크다 — 여기서 re-raise하면
            # 미처리 태스크 예외가 되어 무인 운용을 죽인다(2026-08-03과 같은
            # 모양). 계약대로 로그로 삼키되, LLM 전체 백엔드 소진은 운영자가
            # 몰라선 안 되므로 별도로 통지한다.
            if isinstance(e, LLMAllBackendsFailed):
                await _alert_llm_failure(ticker, e)
        finally:
            # Remove from active rooms
            self._active_rooms.pop(ticker, None)

    async def _on_room_status_change(
        self,
        status: SessionStatus,
        session: ChatSession,
    ) -> None:
        """Handle room status changes."""
        logger.info(
            "room_status_changed",
            ticker=session.ticker,
            status=status.value,
        )

    async def _handle_decision(
        self,
        ticker: str,
        decision: TradeDecision,
        session: ChatSession,
    ) -> None:
        """Handle a trading decision from the discussion."""
        logger.info(
            "handling_decision",
            ticker=ticker,
            action=decision.action.value,
            confidence=decision.confidence,
            consensus=decision.consensus_level,
        )

        # Notify decision callbacks
        for callback in self._on_decision_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(ticker, decision)
                else:
                    callback(ticker, decision)
            except Exception as e:
                logger.warning("decision_callback_failed", error=str(e))

        # Execute trade if action required — every coordinator execution must
        # pass the shared autonomy gate (R3): master env gate + trading_mode +
        # paper-only + daily-loss breaker + position/notional caps. Before R3
        # this path executed unconditionally once the coordinator was started.
        if decision.action in (
            DecisionAction.BUY,
            DecisionAction.SELL,
            DecisionAction.ADD,
            DecisionAction.REDUCE,
        ):
            gate = await check_autonomy(
                "kiwoom",
                action=decision.action.value,
                quantity=decision.quantity,
                entry_price=decision.entry_price,
            )
            if gate.allowed:
                await self._execute_trade(ticker, decision, session)
            else:
                logger.warning(
                    "coordinator_execution_gate_denied",
                    ticker=ticker,
                    action=decision.action.value,
                    check=gate.check,
                    reason=gate.reason,
                )
                await self._notify_gate_denied(ticker, decision, gate.reason)

        # Send Telegram notification
        await self._notify_decision(ticker, decision)

    async def _notify_gate_denied(
        self, ticker: str, decision: TradeDecision, reason: str
    ) -> None:
        """Best-effort Telegram notice when the autonomy gate blocks execution."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                await notifier.send_message(
                    f"🚫 자율 실행 게이트 거부 ({ticker} {decision.action.value}): {reason}"
                )
        except Exception as e:
            logger.warning("gate_denied_notify_failed", ticker=ticker, error=str(e))

    async def _execute_trade(
        self,
        ticker: str,
        decision: TradeDecision,
        session: ChatSession,
    ) -> None:
        """Execute the trading decision."""
        logger.info(
            "executing_trade",
            ticker=ticker,
            action=decision.action.value,
            quantity=decision.quantity,
        )

        try:
            from app.dependencies import get_trading_coordinator
            trading_coord = await get_trading_coordinator()

            # Map decision action to trade action
            action_map = {
                DecisionAction.BUY: "BUY",
                DecisionAction.SELL: "SELL",
                DecisionAction.ADD: "ADD",
                DecisionAction.REDUCE: "REDUCE",
            }
            action = action_map.get(decision.action)

            if action:
                # Execute via trading coordinator
                allocation = await trading_coord.on_trade_approved(
                    session_id=session.id,
                    ticker=ticker,
                    stock_name=None,  # Will be looked up
                    action=action,
                    entry_price=decision.entry_price,
                    stop_loss=decision.stop_loss,
                    take_profit=decision.take_profit,
                    risk_score=int((1 - decision.confidence) * 10),
                    quantity_override=decision.quantity,
                    # R3: mark as autonomy-originated so a QUEUED trade gets a
                    # fresh gate check at execution time.
                    autonomous=True,
                )

                # P2 SSOT prep (2026-07-14): this decision only ever comes
                # from a watch-list opportunity (_handle_decision's only
                # caller is the watch-list auto path — manual discussions
                # never execute). on_trade_approved does NOT go through
                # convert_watch_to_queue, so without this the watch entry
                # would stay ACTIVE and could be re-discussed/duplicate-
                # triggered on the next periodic (1-min) check. No-op if the ticker
                # isn't (or is no longer) an active watch entry.
                #
                # T2 review gap (2026-07-14): on_trade_approved has non-
                # exception outcomes where NO trade actually resulted — the
                # daily trade limit was hit, portfolio sizing came out to
                # <=0 shares, or the order was placed but the broker filled
                # 0 shares. Converting the watch entry in any of those cases
                # retires a real signal that was never acted on (the daily
                # limit resets tomorrow, sizing may succeed later, a broker
                # blip shouldn't kill a signal). Only flip it when the trade
                # genuinely executed or was queued.
                if _trade_actually_resulted(trading_coord, ticker, allocation):
                    trading_coord.mark_watch_converted(ticker)
                else:
                    logger.info(
                        "watch_not_converted_no_trade_resulted",
                        ticker=ticker,
                        rationale=getattr(allocation, "rationale", None),
                    )

                logger.info(
                    "trade_executed",
                    ticker=ticker,
                    action=action,
                )

        except Exception as e:
            logger.error(
                "trade_execution_failed",
                ticker=ticker,
                error=str(e),
            )

    async def _notify_decision(
        self,
        ticker: str,
        decision: TradeDecision,
    ) -> None:
        """Send Telegram notification for decision."""
        try:
            from services.telegram import get_telegram_notifier
            telegram = await get_telegram_notifier()

            if telegram.is_ready:
                action_emoji = {
                    DecisionAction.BUY: "🟢",
                    DecisionAction.SELL: "🔴",
                    DecisionAction.ADD: "🟢➕",
                    DecisionAction.REDUCE: "🔴➖",
                    DecisionAction.HOLD: "⏸️",
                    DecisionAction.WATCH: "👁",
                    DecisionAction.NO_ACTION: "⏹️",
                }

                emoji = action_emoji.get(decision.action, "📋")

                message = f"""{emoji} *Agent Group Chat 결정*

*종목:* {ticker}
*결정:* {decision.action.value}
*신뢰도:* {decision.confidence:.0%}
*합의 수준:* {decision.consensus_level:.0%}
"""

                if decision.action in (DecisionAction.BUY, DecisionAction.ADD):
                    message += f"""
*매수 계획:*
- 수량: {decision.quantity or 'TBD'}주
- 진입가: ₩{decision.entry_price:,}
- 손절가: ₩{decision.stop_loss:,}
- 익절가: ₩{decision.take_profit:,}
"""

                if decision.key_factors:
                    message += f"\n*핵심 요인:*\n"
                    for factor in decision.key_factors[:3]:
                        message += f"• {factor}\n"

                await telegram.send_message(message)

        except Exception as e:
            logger.warning("telegram_notification_failed", error=str(e))

    async def _build_strategy_context(
        self,
    ) -> tuple[Optional[str], Optional[dict], float]:
        """활성 TradingStrategy → (프롬프트 디렉티브, 퍼센트 노브, 합의 문턱).
        조회 실패/전략 없음 = (None, None, 0.75) — 절대 raise하지 않고, 토론을
        막지 않는다(is_stale 승격 금지). 세 번째 값(consensus_threshold)은
        항상 구체적인 float — ChatSession/chat_room.py의 기존 하드코딩
        0.75와 동일한 기본값이라 조회 실패 시에도 거동이 바뀌지 않는다
        (E-3, 진입 활성화)."""
        try:
            from app.dependencies import get_trading_coordinator
            from services.trading.strategy_consensus import clamp_knob

            strategy = (await get_trading_coordinator()).get_strategy()
            if strategy is None:
                return None, None, 0.75
            # Phase4 최종리뷰 Fix2: T2(strategy_apply)와 동일 KNOB_BOUNDS로
            # 클램프한 뒤 퍼센트로 변환 — 수동 PUT /strategy가 Pydantic 필드
            # 범위(예: stop_loss_pct 0.50)까지 허용해도, 이 소비 경로가
            # T2와 다른(무클램프) 수치를 에이전트에 주입하지 않도록 한다.
            knobs = {
                "stop_loss_pct": clamp_knob(
                    "stop_loss_pct", strategy.exit_conditions.stop_loss_pct
                ) * 100.0,
                "take_profit_pct": clamp_knob(
                    "take_profit_pct", strategy.exit_conditions.take_profit_pct
                ) * 100.0,
                "max_position_pct": clamp_knob(
                    "max_position_pct", strategy.position_sizing.max_position_pct
                ) * 100.0,
                "min_cash_ratio": clamp_knob(
                    "min_cash_ratio", strategy.position_sizing.min_cash_ratio
                ) * 100.0,
            }
            # E-3: 합의 문턱도 동일 KNOB_BOUNDS 방어 클램프(0.60-0.85) — 수동
            # PUT이 EntryConditions Field 범위(0.5-0.9)까지 허용해도 이 소비
            # 경로는 그보다 좁은 안전 레일 안에서만 세션에 주입한다.
            entry = strategy.entry_conditions
            consensus_threshold = clamp_knob(
                "consensus_threshold", entry.consensus_threshold
            )
            lines = [
                f"전략명: {strategy.name} / 성향: {strategy.risk_tolerance.value}"
                f" / 스타일: {strategy.trading_style.value}",
                f"사이징 지침: 종목당 최대 {knobs['max_position_pct']:.1f}%,"
                f" 최소 현금 {knobs['min_cash_ratio']:.1f}%",
                f"청산 지침: 손절 {knobs['stop_loss_pct']:.1f}%,"
                f" 익절 {knobs['take_profit_pct']:.1f}%",
                # E-3: entry_conditions를 "진입 기준(참고)" 섹션으로 주입 —
                # soft guidance(하드 게이트 아님): 어떤 코드도 이 값들로
                # 투표를 거부/강제하지 않는다. 4-에이전트 합의 문턱만
                # consensus_threshold를 통해 세션에 실제로 반영된다(별도 배선).
                f"진입 기준(참고, 하드 게이트 아님 — 참고용 가이드일 뿐 강제 아님):"
                f" 기술점수≥{entry.min_technical_score}, 펀더멘털≥{entry.min_fundamental_score},"
                f" 심리≥{entry.min_sentiment_score}, 리스크≤{entry.max_risk_score},"
                f" 합의문턱={consensus_threshold:.2f}",
            ]
            if strategy.system_prompt:
                lines.append(f"운용 원칙: {strategy.system_prompt[:400]}")
            if strategy.custom_instructions:
                lines.append(f"추가 지침: {strategy.custom_instructions[:400]}")
            return "\n".join(lines), knobs, consensus_threshold
        except Exception as e:
            logger.warning("strategy_context_build_failed", error=str(e))
            return None, None, 0.75

    async def _compute_agent_weights(self) -> Optional[dict]:
        """agent_calibration 최신 스냅샷 → 가중 틸트. 표본 부족/데이터 없음/
        실패 = None (기존 고정 가중과 완전 동일 거동 — 옵트인)."""
        try:
            from services.storage_service import get_storage_service
            from services.trading.strategy_panel import _latest_per_key

            storage = await get_storage_service()
            rows = _latest_per_key(await storage.get_agent_calibration(), "agent_type")
            from services.agent_chat.models import DEFAULT_AGENT_WEIGHTS

            weights: dict = {}
            tilted = False
            for agent_type, base in DEFAULT_AGENT_WEIGHTS.items():
                row = next(
                    (r for r in rows if r.get("agent_type") == agent_type.value), None
                )
                weight = base
                if (
                    row
                    and row.get("accuracy") is not None
                    and (row.get("decisions_scored") or 0) >= self._MIN_CALIBRATION_SAMPLES
                ):
                    weight = base * (0.5 + float(row["accuracy"]))
                    weight = max(base * self._WEIGHT_TILT_MIN,
                                 min(base * self._WEIGHT_TILT_MAX, weight))
                    if weight != base:
                        tilted = True
                weights[agent_type.value] = round(weight, 4)
            return weights if tilted else None
        except Exception as e:
            logger.warning("agent_weights_compute_failed", error=str(e))
            return None

    async def _fetch_market_context(
        self,
        ticker: str,
        stock_name: str,
    ) -> MarketContext:
        """Fetch market data for discussion context."""
        logger.info(
            "fetching_market_context",
            ticker=ticker,
        )

        try:
            import pandas as pd

            from agents.tools.kr_market_data import (
                get_kr_stock_info,
                get_kr_daily_chart,
                calculate_kr_technical_indicators,
            )
            from app.core.kiwoom_singleton import get_shared_kiwoom_client_async

            # Fetch stock info. get_kr_stock_info now returns None on a real
            # fetch failure instead of a fabricated random-mock price
            # (CRITICAL safety fix, 2026-07-14) — a None here means we have
            # no real quote to debate/vote on, so return a stale-marked
            # context immediately rather than building a discussion context
            # on invented numbers.
            stock_info = await get_kr_stock_info(ticker)
            if stock_info is None:
                logger.error(
                    "market_context_stock_info_unavailable",
                    ticker=ticker,
                )
                return MarketContext(
                    ticker=ticker,
                    stock_name=stock_name,
                    current_price=0,
                    price_change_pct=0,
                    is_stale=True,
                )

            # Fetch chart data
            chart_df = await get_kr_daily_chart(ticker)
            if chart_df is None:
                logger.warning(
                    "market_context_chart_unavailable",
                    ticker=ticker,
                )
                chart_df = pd.DataFrame()

            # Calculate indicators
            if not chart_df.empty:
                indicators = calculate_kr_technical_indicators(chart_df)
                chart_data = [
                    {
                        "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
                        "open": int(row["open"]),
                        "high": int(row["high"]),
                        "low": int(row["low"]),
                        "close": int(row["close"]),
                        "volume": int(row["volume"]),
                    }
                    for idx, row in chart_df.iterrows()
                ]
            else:
                indicators = {}
                chart_data = []

            # Fetch portfolio info
            has_position = False
            position_quantity = None
            position_avg_price = None
            position_pnl_pct = None
            available_cash = None
            total_portfolio = None

            try:
                client = await get_shared_kiwoom_client_async()
                account = await client.get_account_balance()

                available_cash = account.d2_ord_psbl_amt
                total_portfolio = account.evlu_amt + account.d2_ord_psbl_amt

                for holding in account.holdings:
                    if holding.stk_cd == ticker:
                        has_position = True
                        position_quantity = holding.hldg_qty
                        position_avg_price = holding.avg_buy_prc
                        position_pnl_pct = holding.evlu_pfls_rt
                        break
            except Exception as e:
                logger.warning("portfolio_fetch_failed", error=str(e))
                # H1/M1 fail-closed: Kiwoom 계좌조회 실패 시 fail-open(has_position=
                # False, available_cash=None)하면 보유종목이 미보유로 오판돼 중복 신규
                # BUY가 나가고(vote_to_action BUY), 정상 합의가 quantity=None으로
                # 폐기된다. ExecutionCoordinator의 권위 in-memory 상태로 폴백한다.
                try:
                    from app.dependencies import get_trading_coordinator
                    trading_coord = await get_trading_coordinator()
                    for p in trading_coord._state.positions:
                        if p.ticker == ticker:
                            has_position = True
                            position_quantity = p.quantity
                            position_avg_price = p.avg_price
                            position_pnl_pct = p.unrealized_pnl_pct
                            break
                    acct = trading_coord._state.account
                    if available_cash is None:
                        available_cash = acct.available_cash
                    if total_portfolio is None:
                        total_portfolio = acct.total_equity
                    logger.info(
                        "market_context_account_fallback",
                        ticker=ticker, has_position=has_position,
                        source="coordinator_state",
                    )
                except Exception as e2:
                    # 폴백도 실패(사실상 in-memory라 불가). available_cash=None 유지
                    # → 게이트가 quantity 불명으로 BUY 거부(fail-closed 자연 성립).
                    logger.warning("market_context_fallback_failed", error=str(e2))

            # Fetch news sentiment
            news_sentiment = None
            news_count = 0
            try:
                from app.dependencies import get_news_service
                news_service = await get_news_service()
                if news_service.providers:
                    result = await news_service.search_stock_news(
                        stock_code=ticker,
                        stock_name=stock_name,
                        count=50,
                    )
                    news_count = len(result.articles)

                    if news_count > 0:
                        # Price-momentum proxy — this is the DEGRADE path
                        # only (편향② 근본 원인: technical agent already
                        # exposes price_change_pct directly, so echoing it
                        # here as "sentiment" makes the two agents vote in
                        # lockstep). Real sentiment comes from
                        # NewsSentimentAnalyzer below; this stays the
                        # fail-closed fallback for analyzer exception/
                        # timeout/not-configured.
                        change = stock_info.get("prdy_ctrt", 0)
                        if change > 2:
                            news_sentiment = "positive"
                        elif change < -2:
                            news_sentiment = "negative"
                        else:
                            news_sentiment = "neutral"

                        try:
                            from agents.llm_provider import get_llm_provider
                            from services.news.sentiment import NewsSentimentAnalyzer

                            analyzer = NewsSentimentAnalyzer(get_llm_provider())
                            sentiment_result = await asyncio.wait_for(
                                analyzer.analyze(
                                    articles=result.articles[:5],
                                    stock_name=stock_name,
                                    stock_code=ticker,
                                ),
                                timeout=20.0,
                            )
                            if sentiment_result.is_fallback:
                                # analyzer swallowed its own LLM exception
                                # and returned a neutral-looking result
                                # instead of raising (services/news/
                                # sentiment.py analyze() except-block) — the
                                # most common failure mode. Without this
                                # check that neutral silently overwrote the
                                # price-momentum proxy above and the
                                # news_sentiment_fallback log never fired
                                # (리뷰 Important). Re-raise to reuse the
                                # existing fallback path below.
                                raise RuntimeError(
                                    "news_sentiment_analyzer_internal_fallback"
                                )
                            news_sentiment = sentiment_result.sentiment
                        except Exception as sentiment_error:
                            logger.warning(
                                "news_sentiment_fallback",
                                ticker=ticker,
                                error=str(sentiment_error),
                            )
            except Exception as e:
                logger.warning("news_fetch_failed", error=str(e))

            # Phase4: best-effort active-strategy context. Never raises and
            # never promotes is_stale — a strategy fetch failure must not
            # block the debate (see _build_strategy_context docstring).
            strategy_directive, strategy_knobs, consensus_threshold = (
                await self._build_strategy_context()
            )

            # US 신호 T4: US AI 크로스마켓 신호(AI밸류체인 종목 + 당일 캐시
            # 존재 시에만; off/결측/비-AI밸류체인이면 None — 주입 안 함).
            # never-raise: 실패는 로그만, 토론을 막지 않는다.
            us_market_context = None
            try:
                from services.discovery.ai_valuechain import is_ai_valuechain, valuechain_signal_type
                from services.trading.us_market_data import get_cached_us_ai_signal, get_subsignal
                if is_ai_valuechain(ticker):
                    _us = await get_cached_us_ai_signal()
                    _sub = get_subsignal(_us, valuechain_signal_type(ticker))
                    if _sub is not None and _sub.get("signal") is not None:
                        _comp = _sub.get("components", {})
                        _parts = ", ".join(f"{k} {v:+.1f}%" for k, v in _comp.items())
                        _dir = "강세" if _sub["signal"] > 0 else ("약세" if _sub["signal"] < 0 else "중립")
                        _label = "메모리/HBM" if valuechain_signal_type(ticker) == "memory" else "AI가속기"
                        us_market_context = (
                            f"간밤 미 {_label} {_dir}({_parts}). 이 종목은 해당 미 공급망을 "
                            f"선행 추종 경향이나 확정 신호 아님 — 자체 밸류에이션·수급·뉴스가 우선."
                        )
            except Exception as e:
                logger.warning("us_market_context_build_failed", ticker=ticker, error=str(e))

            # C2(유동성 인지): 리스크 에이전트 프롬프트에 주입할 유동성 한 줄.
            # adtv는 위에서 이미 가져온 chart_df(최신 일봉, get_kr_daily_chart)를
            # 그대로 재사용해 T2 adtv_median(순수 함수)으로 계산한다 — 별도
            # 네트워크 호출 없음, T3/T6와 동일한 kiwoom get_daily_chart_df 스키마.
            #
            # position_notional:
            # - 기존 보유 포지션이 있으면 실제 평가금액(수량 x 현재가).
            # - 신규 후보(미보유)는 이 토론 시점엔 사이징이 아직 결정되지
            #   않았지만, "지어내는" 값이 아니다 — T3 발굴 게이트가 이미
            #   "신규 포지션 = 계좌의 4%"를 가정해 이 종목의 유동성 자격을
            #   판정했다(scanner.py._resolve_min_adtv:
            #   required_min_adtv(equity * 0.04)). 이 리뷰에서 지적된
            #   대로 그 확립된 가정을 그대로 재사용한다 — 0.04가 바뀌면
            #   이쪽도 같이 바꿔야 한다(아직 공유 상수가 아님, scanner.py와
            #   동일한 상황).
            # - total_portfolio를 못 구하거나 0 이하면 None(빈 문자열).
            #
            # never-raise: 실패해도 로그만 남기고 빈 문자열로 진행한다.
            _liq_note = ""
            try:
                from services.discovery.liquidity import adtv_median
                from services.agent_chat.liquidity_note import build_liquidity_note

                _adtv = adtv_median(chart_df)
                _is_new_entry = not (has_position and position_quantity)
                if not _is_new_entry:
                    _position_notional = position_quantity * stock_info.get("cur_prc", 0)
                elif total_portfolio and total_portfolio > 0:
                    _position_notional = total_portfolio * 0.04
                else:
                    _position_notional = None
                _liq_note = build_liquidity_note(
                    _adtv, _position_notional, is_new_entry=_is_new_entry
                )
            except Exception as e:
                logger.warning("liquidity_note_failed", ticker=ticker, error=str(e))

            # ka10001 mrkt_tot_amt 단위=억원 (scanner.py:852-856과 동일 근거,
            # 라이브 실측 2026-07-18: 005930 -> 14,908,010억 ≈ 1,490조).
            # 무보정이면 fundamental_agent 표시가 왜곡돼 LLM이 "데이터
            # 오류"를 매수 보류 근거로 오용한다(편향③) — 원 단위로 환산.
            mrkt_tot_amt = stock_info.get("mrkt_tot_amt")
            market_cap = (
                float(mrkt_tot_amt) * 100_000_000
                if mrkt_tot_amt is not None
                else None
            )

            return MarketContext(
                ticker=ticker,
                stock_name=stock_name or stock_info.get("stk_nm", ticker),
                current_price=stock_info.get("cur_prc", 0),
                price_change_pct=stock_info.get("prdy_ctrt", 0),
                chart_data=chart_data,
                indicators=indicators,
                per=stock_info.get("per"),
                pbr=stock_info.get("pbr"),
                eps=stock_info.get("eps"),
                market_cap=market_cap,
                news_sentiment=news_sentiment,
                news_count=news_count,
                has_position=has_position,
                position_quantity=position_quantity,
                position_avg_price=position_avg_price,
                position_pnl_pct=position_pnl_pct,
                available_cash=available_cash,
                total_portfolio_value=total_portfolio,
                strategy_directive=strategy_directive,
                strategy_knobs=strategy_knobs,
                consensus_threshold=consensus_threshold,
                us_market_context=us_market_context,
                liquidity_context=_liq_note,
            )

        except Exception as e:
            logger.error(
                "market_context_fetch_failed",
                ticker=ticker,
                error=str(e),
            )
            # Return minimal context, marked stale so callers refuse to vote
            # on it (CRITICAL safety fix, 2026-07-14).
            return MarketContext(
                ticker=ticker,
                stock_name=stock_name,
                current_price=0,
                price_change_pct=0,
                is_stale=True,
            )

    # -------------------------------------------
    # Manual Discussion API
    # -------------------------------------------

    async def start_manual_discussion(
        self,
        ticker: str,
        stock_name: str,
        wait: bool = False,
    ) -> ChatSession:
        """
        Start a manual discussion for a stock (not from watch list).

        By default the discussion runs as a BACKGROUND task and the (still-
        running) ChatSession is returned immediately, so clients can subscribe
        to the session WebSocket and stream the debate live. With wait=True
        the call blocks until the debate completes and returns the DECIDED
        session (raising on failure) — the contract PositionManager depends on
        to read session.decision. Either way the manual path never executes
        the decision itself (_handle_decision is the watch-list auto path's
        job) — callers decide what to do with it.

        Args:
            ticker: Stock ticker
            stock_name: Stock name
            wait: Block until the discussion completes (old synchronous contract)

        Returns:
            The ChatSession (completed if wait=True, else running)
        """
        logger.info(
            "starting_manual_discussion",
            ticker=ticker,
            stock_name=stock_name,
        )

        # Check if already discussing
        if ticker in self._active_rooms:
            raise ValueError(f"Discussion already in progress for {ticker}")

        # Fetch context
        context = await self._fetch_market_context(ticker, stock_name)

        # A stale context means the real quote fetch failed — refuse to
        # start a discussion that would debate/vote on invented numbers
        # (CRITICAL safety fix, 2026-07-14). The API route maps ValueError
        # to 409; PositionManager._trigger_discussion (wait=True caller)
        # already catches generic Exception and logs, leaving the position
        # monitored with its last-known stops — a safe degrade either way.
        if context.is_stale:
            logger.warning(
                "manual_discussion_skipped_stale_market_data",
                ticker=ticker,
            )
            raise ValueError(
                f"시세 데이터 조회 실패로 {ticker} 토론을 시작할 수 없습니다 (stale market data)"
            )

        # Create the room
        room = ChatRoom(
            ticker=ticker,
            stock_name=stock_name,
            context=context,
            # E-3: 자동 경로(_start_discussion)와 동일하게 context 단일
            # 소스에서 consensus_threshold 전달.
            consensus_threshold=context.consensus_threshold,
            agent_weights=await self._compute_agent_weights(),
        )
        _fire_room_created(room)

        self._active_rooms[ticker] = room

        # P4-2 (session-ssot): single choke point for BOTH manual entry
        # paths below (wait=True inline await and the wait=False background
        # task) -- must happen before room.start() is ever awaited.
        await _register_sm_discussion(room)

        if wait:
            # Old synchronous contract: return the completed session, raise on
            # failure (the caller's discussion budget must not be consumed by
            # failures).
            try:
                session = await room.start()
                clear_llm_failure_latch()
                await persist_session(session)
                self._last_discussion[ticker] = datetime.now()
                return session
            except LLMAllBackendsFailed as e:
                # 사이트 B. 이 경로에는 원래 except가 없었다 — "예외가 HTTP
                # 호출자에게 그대로 간다"는 전제였는데, 실제 호출자 목록을 세어
                # 보면 틀렸다: `app/api/routes/agent_chat.py:320`은 `wait`를 넘기지
                # 않아 백그라운드 경로(사이트 C)로 가고, 프로덕션에서 wait=True로
                # 부르는 곳은 `position_manager.py:1232` 하나뿐인데 그 핸들러는
                # 로그 한 줄만 남긴다. 그래서 익절·손절임박·큰손실·전략재평가
                # 토론이 LLM 장애로 죽으면 **실 포지션에 가장 가까운 경로**에서
                # 운영자에게 아무것도 가지 않았다.
                #
                # 사이트 A/C와 달리 여기서는 삼키지 않는다 — 이 경로의 계약은
                # 전파다(호출자가 session.decision을 읽는다). 알리고 다시 던진다.
                await _alert_llm_failure(ticker, e)
                raise
            finally:
                self._active_rooms.pop(ticker, None)

        asyncio.create_task(self._run_manual_discussion(ticker, room))

        return room.session

    async def _run_manual_discussion(self, ticker: str, room: ChatRoom) -> None:
        """Run a manually-started discussion in the background.

        Mirrors the old synchronous post-completion steps (history + last-
        discussion timestamp). Deliberately does NOT call _handle_decision:
        that is the watch-list auto path's job — the manual path must never
        place orders (live trading FROZEN).
        """
        try:
            session = await room.start()
            clear_llm_failure_latch()

            await persist_session(session)
            self._last_discussion[ticker] = datetime.now()

        except Exception as e:
            logger.error(
                "manual_discussion_failed",
                ticker=ticker,
                error=str(e),
            )
            # The session id was already handed out by /discuss — persisting
            # it here (P4-4: the ledger, not the retired in-memory history,
            # is what makes it queryable) keeps the (CANCELLED) session from
            # dangling as a permanent 404.
            await persist_session(room.session)
            # LLM 전체 백엔드 소진은 여기서도 삼켜야 한다(위 persist_session이
            # 세션 dangling 404를 막는 복구 로직이라 re-raise로 우회할 수 없다) —
            # 대신 운영자에게 별도로 알린다.
            if isinstance(e, LLMAllBackendsFailed):
                await _alert_llm_failure(ticker, e)
        finally:
            self._active_rooms.pop(ticker, None)

    def get_active_discussions(self) -> List[dict]:
        """Get list of active discussions."""
        return [
            {
                "ticker": ticker,
                "stock_name": room.stock_name,
                "session_id": room.session.id,
                "status": room.session.status.value,
                "started_at": room.session.started_at.isoformat() if room.session.started_at else None,
            }
            for ticker, room in self._active_rooms.items()
        ]

    async def get_session_history(
        self,
        limit: int = 20,
        ticker: Optional[str] = None,
    ) -> List[dict]:
        """Session history: SM (kind="discussion") merged with the durable
        ledger, deduped by id (SM wins -- see the module-level "Session-
        history read merge" section above), sorted ascending by start/
        created time and truncated to the most recent `limit` -- the exact
        `[-limit:]` semantics the retired `_session_history` list had,
        applied to the merged pool instead of an in-memory list. Returns a
        list of summary dicts (the shape app/api/routes/agent_chat.py's
        `_session_to_summary` used to build from a ChatSession) rather than
        ChatSession objects: a ledger-only row has no full ChatSession to
        build one from without parsing its transcript JSON per list row.
        Failure-harmless per source: an SM or ledger outage degrades to
        whatever the other source has, never a raise (routes never 500)."""
        summaries: Dict[str, dict] = {}
        sort_keys: Dict[str, datetime] = {}
        sm_discussion_count = 0

        try:
            sm = await get_session_manager()
            sm_sessions = await sm.get_all_sessions(kind="discussion")
            sm_discussion_count = len(sm_sessions)
            for sm_session in sm_sessions.values():
                if ticker and sm_session.ticker != ticker:
                    continue
                snapshot = (sm_session.state or {}).get("chat_snapshot")
                if not snapshot:
                    continue
                try:
                    chat_session = ChatSession.model_validate(snapshot)
                except Exception as e:
                    logger.warning(
                        "session_history_sm_snapshot_invalid",
                        session_id=sm_session.session_id,
                        error=str(e),
                    )
                    continue
                sub_status = (sm_session.state or {}).get(
                    "sub_status"
                ) or _SM_STATUS_TO_AGENT_CHAT_VOCAB.get(sm_session.status)
                summaries[chat_session.id] = _summary_from_chat_session(chat_session, sub_status)
                sort_keys[chat_session.id] = _naive_utc(
                    chat_session.started_at or chat_session.created_at
                )
        except Exception as e:
            logger.warning("session_history_sm_read_failed", error=str(e))

        try:
            storage = await get_storage_service()
            # Bounded fetch (existing DESC+LIMIT contract) -- buffered by the
            # SM row count so dedup collapsing an SM/ledger overlap never
            # starves the merged pool below `limit` distinct sessions.
            rows = await storage.get_agent_chat_decisions(
                ticker=ticker, limit=limit + sm_discussion_count
            )
            for row in rows:
                row_id = row.get("id")
                if not row_id or row_id in summaries:
                    continue  # SM row wins on dedup
                summaries[row_id] = _summary_from_ledger_row(row)
                sort_keys[row_id] = _naive_utc(_parse_ledger_timestamp(row.get("created_at")))
        except Exception as e:
            logger.warning("session_history_ledger_read_failed", error=str(e))

        ordered_ids = sorted(summaries.keys(), key=lambda sid: sort_keys.get(sid, datetime.min))
        return [summaries[sid] for sid in ordered_ids][-limit:]

    async def get_session_by_id(self, session_id: str) -> Optional[ChatSession]:
        """Get a specific session by ID -- three-tier fallback: (1) a live
        room in _active_rooms (freshest, exact object identity), (2) SM's
        kind="discussion" row (covers running discussions plus any terminal
        one still within SM's TTL/reload window), (3) the durable ledger
        transcript (P4-3) for everything else. Returns None (never raises)
        when no tier has it or a source errors -- callers 404, not 500."""
        for room in self._active_rooms.values():
            if room.session.id == session_id:
                return room.session

        try:
            sm = await get_session_manager()
            sm_session = await sm.get_session(session_id)
            if sm_session is not None and sm_session.kind == "discussion":
                snapshot = (sm_session.state or {}).get("chat_snapshot")
                if snapshot:
                    try:
                        return ChatSession.model_validate(snapshot)
                    except Exception as e:
                        logger.warning(
                            "session_by_id_sm_snapshot_invalid",
                            session_id=session_id,
                            error=str(e),
                        )
        except Exception as e:
            logger.warning(
                "session_by_id_sm_read_failed", session_id=session_id, error=str(e)
            )

        try:
            storage = await get_storage_service()
            transcript_json = await storage.get_agent_chat_transcript(session_id)
            if transcript_json:
                try:
                    return ChatSession.model_validate(json.loads(transcript_json))
                except Exception as e:
                    logger.warning(
                        "session_by_id_ledger_transcript_invalid",
                        session_id=session_id,
                        error=str(e),
                    )
        except Exception as e:
            logger.warning(
                "session_by_id_ledger_read_failed", session_id=session_id, error=str(e)
            )

        return None

    async def count_total_sessions(self) -> int:
        """Durable total-session count for /status's `total_sessions` field
        (P4-4: replaces the retired in-memory `_session_history`'s len() --
        the ledger is the sole, permanent source now). Failure-harmless: an
        outage degrades to 0 rather than a 500."""
        try:
            storage = await get_storage_service()
            return await storage.count_agent_chat_decisions()
        except Exception as e:
            logger.warning("count_total_sessions_failed", error=str(e))
            return 0


# -------------------------------------------
# Singleton Instance
# -------------------------------------------

_chat_coordinator: Optional[ChatCoordinator] = None


async def get_chat_coordinator() -> ChatCoordinator:
    """Get or create singleton chat coordinator."""
    global _chat_coordinator
    if _chat_coordinator is None:
        _chat_coordinator = ChatCoordinator()
    return _chat_coordinator


def get_chat_coordinator_sync() -> ChatCoordinator:
    """Get chat coordinator synchronously."""
    global _chat_coordinator
    if _chat_coordinator is None:
        _chat_coordinator = ChatCoordinator()
    return _chat_coordinator
