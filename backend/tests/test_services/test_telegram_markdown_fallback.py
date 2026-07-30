"""통지 광역화 Task 1: Markdown 파싱 실패 시 평문 폴백.

이 레포는 Markdown 파싱 실패로 라이브 통지를 두 번 잃었고(51227ca의 daily_cap
밑줄), 세 번째가 진행 중이다 — _notify_decision이 'NO_ACTION'의 밑줄로 07-30
하루 18건+ 400 실패. _send_message가 그 400을 삼키고 False를 반환하는데
아무도 그 반환값을 보지 않아 무엇이 유실됐는지조차 알 수 없다.

폴백은 '한 번 더 보낸다'가 전부가 아니다 — 실패 사실이 로그에 남아야 다음
사고를 조기에 잡는다. 단 토큰은 절대 로그에 넣지 않는다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import BadRequest

from services.telegram.service import TelegramNotifier

pytestmark = pytest.mark.asyncio


def _make_service() -> TelegramNotifier:
    """발송 경로만 시험한다 — 실제 Bot 없이 _bot을 주입한다."""
    svc = TelegramNotifier()
    svc._initialized = True
    svc._bot = MagicMock()
    svc._bot.send_message = AsyncMock()
    svc._config = MagicMock()
    svc._config.TELEGRAM_CHAT_ID = "12345"
    return svc


async def test_markdown_parse_failure_falls_back_to_plain_text():
    """Markdown 400이 나면 parse_mode 없이 한 번 더 보낸다."""
    svc = _make_service()
    svc._bot.send_message = AsyncMock(
        side_effect=[BadRequest("Can't find end of the entity starting at byte offset 42"), None]
    )

    ok = await svc._send_message("결정: NO_ACTION 확정")

    assert ok is True
    assert svc._bot.send_message.await_count == 2
    first_kwargs = svc._bot.send_message.await_args_list[0].kwargs
    second_kwargs = svc._bot.send_message.await_args_list[1].kwargs
    assert first_kwargs["parse_mode"] == "Markdown"
    assert second_kwargs.get("parse_mode") is None
    assert second_kwargs["text"] == first_kwargs["text"]


async def test_plain_fallback_failure_returns_false():
    """폴백까지 실패하면 False — 조용한 성공으로 위장하지 않는다."""
    svc = _make_service()
    svc._bot.send_message = AsyncMock(side_effect=BadRequest("nope"))

    ok = await svc._send_message("결정: NO_ACTION 확정")

    assert ok is False
    assert svc._bot.send_message.await_count == 2


async def test_non_parse_error_does_not_retry():
    """파싱과 무관한 실패(네트워크 등)는 재시도하지 않는다 — 중복 발송 방지."""
    from telegram.error import TimedOut

    svc = _make_service()
    svc._bot.send_message = AsyncMock(side_effect=TimedOut())

    ok = await svc._send_message("정상 메시지")

    assert ok is False
    assert svc._bot.send_message.await_count == 1


async def test_failure_logs_context_without_secrets():
    """실패 로그에 parse_mode·본문 앞부분·실패 종류가 남고, 토큰은 없다."""
    svc = _make_service()
    svc._bot.send_message = AsyncMock(side_effect=BadRequest("Can't parse entities"))

    with patch("services.telegram.service.logger") as mock_logger:
        await svc._send_message("결정: NO_ACTION 확정")

    calls = [c for c in mock_logger.error.call_args_list]
    assert calls, "실패가 logger.error로 남아야 한다"
    joined = " ".join(str(c) for c in calls)
    assert "parse_mode" in joined
    assert "bot" not in joined.lower() or ":" not in joined  # 토큰 형태가 없어야 한다


async def test_md_escape_covers_all_legacy_markers():
    """_md_escape가 레거시 Markdown 4문자를 전부 막는다."""
    escaped = TelegramNotifier._md_escape("NO_ACTION *강조* `코드` [링크]")
    for ch in ("_", "*", "`", "["):
        assert f"\\{ch}" in escaped
