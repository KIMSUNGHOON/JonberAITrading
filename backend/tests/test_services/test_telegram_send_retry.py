"""`_send_message` 재시도 규칙 — 연결 실패만 재시도한다.

2026-08-13에 NetworkError 1건·TimedOut 1건으로 알림 2건이 유실됐다.
기존 코드는 "전송 여부가 불확실하다"는 이유로 둘 다 재시도하지 않았는데,
`httpx.ConnectError`는 연결이 성립한 적이 없으므로 중복 위험이 없다.

⚠️ PTB에서 BadRequest와 TimedOut은 **NetworkError의 하위 클래스**다.
isinstance로 판별하면 각각의 기존 처리를 삼켜버린다 — 정확한 타입 비교만
안전하다.
"""
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
