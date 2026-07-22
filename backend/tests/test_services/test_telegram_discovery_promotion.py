"""Discovery promotion Telegram notification
(`TelegramNotifier.send_discovery_promotion(trade_date, promoted, daily_cap_waiting)`).

One-way, concise, NO buttons/HITL notice fired when autonomous discovery
promotes stocks to the watchlist (arc: "Discovery promotion Telegram
notification", Task 1 -- this task adds the service method + format +
config gate only; Task 2 wires it into the pipeline).

Mirrors send_daily_summary's own test file
(test_telegram_daily_summary.py) exactly: a notifier built "ready"
(initialized + fake AsyncMock bot) without touching the network, gated on
a TELEGRAM_NOTIFY_* category flag, delegates to the existing
`_send_message`.
"""

from unittest.mock import AsyncMock

import pytest

from services.telegram.config import TelegramConfig
from services.telegram.service import TelegramNotifier

pytestmark = pytest.mark.asyncio


def _configured_notifier(notify_discovery: bool = True) -> TelegramNotifier:
    """A notifier that is 'ready' (initialized + fake bot) without touching
    the network -- mirrors how initialize() would leave it after a real
    successful connect, but deterministic for tests."""
    config = TelegramConfig(
        TELEGRAM_ENABLED=True,
        TELEGRAM_BOT_TOKEN="test-token",
        TELEGRAM_CHAT_ID="12345",
        TELEGRAM_NOTIFY_DISCOVERY=notify_discovery,
    )
    notifier = TelegramNotifier(config=config)
    notifier._initialized = True
    notifier._bot = AsyncMock()
    return notifier


# -------------------------------------------
# format correctness
# -------------------------------------------


async def test_discovery_promotion_format():
    notifier = _configured_notifier()
    promoted = [
        {"ticker": "044340", "name": "위닉스", "composite": 0.725, "strategy": "momentum", "target": 3850},
        {"ticker": "475150", "name": "SK이터닉스", "composite": 0.670, "strategy": "momentum", "target": 62000},
    ]

    result = await notifier.send_discovery_promotion(
        trade_date="2026-07-22", promoted=promoted, daily_cap_waiting=16
    )

    assert result is True
    notifier._bot.send_message.assert_called_once()
    msg = notifier._bot.send_message.call_args.kwargs["text"]

    assert "자율 발굴 승격 2종" in msg and "2026-07-22" in msg
    assert "위닉스 044340" in msg and "0.73" in msg and "momentum" in msg
    assert "SK이터닉스 475150" in msg and "0.67" in msg
    assert "16종 일일한도 대기" in msg and "개장 시 토론→투표" in msg


async def test_discovery_promotion_no_daily_cap_waiting_omits_that_clause():
    notifier = _configured_notifier()
    promoted = [
        {"ticker": "044340", "name": "위닉스", "composite": 0.725, "strategy": "momentum", "target": 3850},
    ]

    await notifier.send_discovery_promotion(trade_date="2026-07-22", promoted=promoted, daily_cap_waiting=0)

    msg = notifier._bot.send_message.call_args.kwargs["text"]
    assert "일일한도 대기" not in msg
    assert "개장 시 토론→투표" in msg


# -------------------------------------------
# empty promoted -> no-op (no send)
# -------------------------------------------


async def test_discovery_promotion_empty_no_send():
    notifier = _configured_notifier()

    result = await notifier.send_discovery_promotion(trade_date="2026-07-22", promoted=[], daily_cap_waiting=0)

    assert result is False
    notifier._bot.send_message.assert_not_called()


# -------------------------------------------
# gate off -> no-op (no send)
# -------------------------------------------


async def test_discovery_promotion_gate_off():
    notifier = _configured_notifier(notify_discovery=False)

    result = await notifier.send_discovery_promotion(
        trade_date="d",
        promoted=[{"ticker": "x", "name": "n", "composite": 0.5, "strategy": "s", "target": 1}],
        daily_cap_waiting=0,
    )

    assert result is False
    notifier._bot.send_message.assert_not_called()


# -------------------------------------------
# overflow -> caps at 10 + "외 M종"
# -------------------------------------------


async def test_discovery_promotion_overflow_caps_at_10():
    notifier = _configured_notifier()
    promoted = [
        {"ticker": f"{i:06d}", "name": f"n{i}", "composite": 0.5, "strategy": "momentum", "target": 100}
        for i in range(13)
    ]

    await notifier.send_discovery_promotion(trade_date="d", promoted=promoted, daily_cap_waiting=0)

    msg = notifier._bot.send_message.call_args.kwargs["text"]
    assert "외 3종" in msg
    # only the first 10 tickers rendered as individual lines
    assert "n0" in msg and "n9" in msg
    assert "n10" not in msg
