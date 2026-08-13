"""Task 13: 종목 티커를 텔레그램 메시지에 노출할 때 `종목이름(티커번호)`
형식이어야 한다.

라이브 실측: 브로커는 이름을 주는데(`stk_nm='농심'`) 코디네이터 포지션에는
티커 코드가 stock_name으로 들어가 있었고, 실제 발송 메시지는
`*종목:* 058610 (058610)`처럼 이름 없이 코드만 중복 노출됐다.

`services/telegram/service.py`의 거래/포지션 알림 대부분이 `*종목:*
{stock_name} ({ticker})`처럼 값을 그대로 꽂아 넣었다 -- 형식은 이미
있었지만 이름이 비었을 때 중복을 막는 로직이 없었다. `stock_label()`로
통일하면 이름이 있으면 `이름(티커)`, 없거나 티커와 같으면 `종목 티커`로
접힌다.

이 파일은 대표적으로 몇 개 메시지(거래 제안·손절·워치리스트 등록)가
실제로 `stock_label`을 거치는지만 확인한다 -- 모든 send_* 메서드를
낱낱이 훑지 않는다(그건 코드 자체가 정적으로 보장한다: 10곳 전부 같은
치환을 받았다).
"""
from unittest.mock import AsyncMock

import pytest

from services.telegram.config import TelegramConfig
from services.telegram.service import TelegramNotifier

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("isolated_storage_service")]


def _notifier() -> TelegramNotifier:
    cfg = TelegramConfig(TELEGRAM_BOT_TOKEN="1:x", TELEGRAM_CHAT_ID="42", TELEGRAM_ENABLED=True)
    n = TelegramNotifier(config=cfg)
    n._bot = AsyncMock()
    n._initialized = True
    return n


def _sent_text(n: TelegramNotifier) -> str:
    return n._bot.send_message.call_args.kwargs["text"]


async def test_trade_proposal_shows_name_and_ticker_in_parens():
    n = _notifier()
    await n.send_trade_proposal(
        ticker="004370", stock_name="농심", action="BUY", entry_price=350_000,
    )
    text = _sent_text(n)
    assert "농심(004370)" in text
    assert " (004370)" not in text, "괄호 앞에 스페이스가 남아있으면 안 된다"


async def test_trade_proposal_missing_name_falls_back_without_duplicating_ticker():
    """이름을 못 구한 경우(라이브에서 관측된 바로 그 상태) — 티커가
    두 번 찍히면 안 된다(`058610 (058610)`류 중복 금지)."""
    n = _notifier()
    await n.send_trade_proposal(
        ticker="058610", stock_name="", action="BUY", entry_price=1_000,
    )
    text = _sent_text(n)
    assert "종목 058610" in text
    assert text.count("058610") == 1, "티커가 정확히 한 번만 나와야 한다"


async def test_trade_proposal_name_equal_to_ticker_falls_back_too():
    """coordinator가 이름 대신 티커를 stock_name에 넣었던 결함 상태를
    그대로 흉내낸다 — 여전히 중복 없이 폴백해야 한다."""
    n = _notifier()
    await n.send_trade_proposal(
        ticker="058610", stock_name="058610", action="BUY", entry_price=1_000,
    )
    text = _sent_text(n)
    assert "종목 058610" in text
    assert text.count("058610") == 1


async def test_stop_loss_triggered_shows_name_and_ticker():
    n = _notifier()
    await n.send_stop_loss_triggered(
        ticker="004370", stock_name="농심", trigger_price=340_000, stop_loss_price=345_000,
    )
    text = _sent_text(n)
    assert "농심(004370)" in text


async def test_watch_list_added_shows_name_and_ticker():
    n = _notifier()
    await n.send_watch_list_added(
        ticker="028670", stock_name="팬오션", signal="buy", confidence=0.8,
        current_price=5_000,
    )
    text = _sent_text(n)
    assert "팬오션(028670)" in text
