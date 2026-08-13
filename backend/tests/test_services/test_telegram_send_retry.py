"""`_send_message` 재시도 규칙 — 연결 실패만 재시도한다.

2026-08-13에 NetworkError 1건·TimedOut 1건으로 알림 2건이 유실됐다.
기존 코드는 "전송 여부가 불확실하다"는 이유로 둘 다 재시도하지 않았는데,
`httpx.ConnectError`는 연결이 성립한 적이 없으므로 중복 위험이 없다.

⚠️ PTB에서 BadRequest와 TimedOut은 **NetworkError의 하위 클래스**다.
isinstance로 판별하면 각각의 기존 처리를 삼켜버린다 — 정확한 타입 비교만
안전하다.
"""
import asyncio

import pytest
from unittest.mock import AsyncMock
from telegram.error import BadRequest, NetworkError, TimedOut

from services.telegram.config import TelegramConfig
from services.telegram.service import TelegramNotifier

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


def _notifier() -> TelegramNotifier:
    cfg = TelegramConfig(TELEGRAM_BOT_TOKEN="1:x", TELEGRAM_CHAT_ID="42", TELEGRAM_ENABLED=True)
    n = TelegramNotifier(config=cfg)
    n._bot = AsyncMock()
    n._initialized = True
    return n


def test_ptb_hierarchy_assumption_holds():
    """이 규칙은 PTB의 예외 계층에 의존한다 — 바뀌면 즉시 알아야 한다."""
    assert issubclass(BadRequest, NetworkError)
    assert issubclass(TimedOut, NetworkError)
    assert set(NetworkError.__subclasses__()) == {BadRequest, TimedOut}


@pytest.mark.asyncio
async def test_connect_failure_is_retried_and_can_succeed():
    n = _notifier()
    calls = {"n": 0}

    async def _send(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise NetworkError("httpx.ConnectError: All connection attempts failed")
        return None

    n._bot.send_message = AsyncMock(side_effect=_send)
    assert await n._send_message("hi", parse_mode=None) is True
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_timed_out_is_not_retried():
    """전송 여부가 불확실하다 — 재시도하면 중복 발송이 된다."""
    n = _notifier()
    n._bot.send_message = AsyncMock(side_effect=TimedOut())
    assert await n._send_message("hi", parse_mode=None) is False
    assert n._bot.send_message.await_count == 1


@pytest.mark.asyncio
async def test_bad_request_still_falls_back_to_plain():
    """기존 동작 회귀 방지 — Markdown 파싱 실패는 평문으로 다시 보낸다."""
    n = _notifier()
    calls = {"n": 0}

    async def _send(*a, **k):
        calls["n"] += 1
        if k.get("parse_mode"):
            raise BadRequest("can't parse entities")
        return None

    n._bot.send_message = AsyncMock(side_effect=_send)
    assert await n._send_message("hi", parse_mode="Markdown") is True


@pytest.mark.asyncio
async def test_multi_chunk_retry_progresses_and_never_resends_a_succeeded_chunk(monkeypatch):
    """다중 청크 메시지가 재시도 도중 또 실패하면, 다음 재시도는 마지막으로
    실패한 청크부터 재개해야 한다 — 이미 성공한 청크를 다시 보내면 중복
    발송 사고다.

    시나리오(리뷰에서 지적된 버그 재현): 3청크 메시지에서
      1) 청크0 성공, 청크1에서 NetworkError
      2) 1차 재시도: 청크1 성공, 청크2에서 다시 NetworkError
      3) 2차 재시도: 청크2부터 재개해야 한다(청크1을 또 보내면 안 됨)

    `_send_chunks`가 반환하는 진행 인덱스(`sent_index`)를 재시도 루프
    안에서 갱신하지 않으면 2)에서 실패한 지점이 버려지고 3)이 다시
    start_index=1로 재개돼 청크1이 두 번 발송된다.
    """
    n = _notifier()
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    CHUNK0, CHUNK1, CHUNK2 = "chunk-0-body", "chunk-1-body", "chunk-2-body"
    monkeypatch.setattr(n, "_split_message", lambda text, max_length=4000: [CHUNK0, CHUNK1, CHUNK2])

    call_counts: dict[str, int] = {}
    sent_log: list[str] = []

    async def _send(*a, **k):
        text = k["text"]
        call_counts[text] = call_counts.get(text, 0) + 1
        # 청크1·청크2는 각각 "그 청크로는 처음 도달했을 때"만 실패한다 —
        # 재전송(같은 청크의 두 번째 호출)은 항상 성공해, 버그가 있으면
        # 그 재전송이 실제로 일어나 sent_log에 중복이 남는다.
        if text in (CHUNK1, CHUNK2) and call_counts[text] == 1:
            raise NetworkError("httpx.ConnectError: All connection attempts failed")
        sent_log.append(text)
        return None

    n._bot.send_message = AsyncMock(side_effect=_send)

    assert await n._send_message("무시됨(모킹된 _split_message가 대체)", parse_mode=None) is True
    assert sent_log == [CHUNK0, CHUNK1, CHUNK2], (
        f"청크가 정확히 한 번씩만 발송돼야 한다 — 실제: {sent_log}"
    )


@pytest.mark.asyncio
async def test_network_error_then_bad_request_on_retry_falls_back_to_plain(monkeypatch):
    """2026-08-13 최종 브랜치 리뷰 Important 5 -- 재시도 중 실패 종류가
    NetworkError에서 BadRequest(Markdown 파싱 실패)로 바뀌면, 재시도
    루프가 `break`로 곧장 `return False`해 평문 폴백에 아예 도달하지
    못했다. 08-13 실측에서 `plain_fallback_ok`가 하루 25건 나온 상시
    경로인데, 그 경로가 NetworkError로 시작한 재시도 중에는 막혀 있었다.

    시나리오: 최초 전송이 NetworkError -> 재시도 1회차가 BadRequest로
    바뀜 -> `error`를 갱신해 기존 is_parse_error 분기로 낙하 -> 평문
    재전송이 성공해야 한다."""
    n = _notifier()
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    calls = {"n": 0}

    async def _send(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise NetworkError("httpx.ConnectError: All connection attempts failed")
        if calls["n"] == 2:
            raise BadRequest("can't parse entities")
        return None

    n._bot.send_message = AsyncMock(side_effect=_send)

    assert await n._send_message("hi", parse_mode="Markdown") is True
    assert calls["n"] == 3, "연결 재시도(2) 뒤 평문 폴백(3)까지 도달해야 한다"


@pytest.mark.asyncio
async def test_network_error_retries_exhausted_still_returns_false(monkeypatch):
    """회귀 가드 -- 두 번의 재시도가 전부 NetworkError로 끝나면(파싱
    실패로 전환되지 않으면) 여전히 소진으로 취급해 False를 돌려줘야
    한다(평문 폴백을 잘못 타면 안 된다 — parse_mode 없이 보낸 적이
    없으므로 중복 발송 걱정은 없지만, 애초에 이 경로는 '연결 자체가
    안 됐다'는 뜻이라 평문으로도 안 될 확률이 높다)."""
    n = _notifier()
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    n._bot.send_message = AsyncMock(
        side_effect=NetworkError("httpx.ConnectError: All connection attempts failed")
    )

    assert await n._send_message("hi", parse_mode="Markdown") is False
    assert n._bot.send_message.await_count == 3  # 최초 1 + 재시도 2
