"""`TelegramNotifier.send_document` — HTML 리포트 첨부 발송."""
import pytest
from unittest.mock import AsyncMock

from services.telegram.config import TelegramConfig
from services.telegram.service import TelegramNotifier

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


def _notifier(**overrides) -> TelegramNotifier:
    cfg = TelegramConfig(
        TELEGRAM_BOT_TOKEN="1:x", TELEGRAM_CHAT_ID="42", TELEGRAM_ENABLED=True, **overrides
    )
    n = TelegramNotifier(config=cfg)
    n._bot = AsyncMock()
    n._initialized = True
    return n


@pytest.mark.asyncio
async def test_sends_document_with_filename_and_caption():
    n = _notifier()
    ok = await n.send_document(b"<html>x</html>", "premarket-2026-08-13.html", "장전 리포트")
    assert ok is True
    n._bot.send_document.assert_awaited_once()
    kwargs = n._bot.send_document.await_args.kwargs
    assert kwargs["chat_id"] == "42"
    assert kwargs["filename"] == "premarket-2026-08-13.html"
    assert kwargs["caption"] == "장전 리포트"


@pytest.mark.asyncio
async def test_gate_off_does_not_send():
    n = _notifier(TELEGRAM_REPORT_HTML_ENABLED=False)
    assert await n.send_document(b"x", "a.html") is False
    n._bot.send_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_uninitialised_bot_returns_false():
    n = _notifier()
    n._initialized = False
    assert await n.send_document(b"x", "a.html") is False


@pytest.mark.asyncio
async def test_send_failure_is_swallowed():
    """전송 실패가 예외로 새어나가면 EOD 체인이 죽는다."""
    n = _notifier()
    n._bot.send_document = AsyncMock(side_effect=RuntimeError("boom"))
    assert await n.send_document(b"x", "a.html") is False
