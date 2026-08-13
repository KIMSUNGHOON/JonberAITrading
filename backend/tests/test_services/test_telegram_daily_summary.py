"""E3-3: Telegram EOD daily-summary notification
(`TelegramNotifier.send_daily_summary(digest, narrative)`).

Reuses the digest E3-1 already assembles (services/trading/eod_digest.py::
build_eod_digest -- 5 keys: trade_date/watch/account/holdings/strategy/
regime) and the narrative E3-2 already generates
(narrate_eod_digest). This method never recomputes either -- it only
formats what it's handed:

  - narrative present -> narrative body + a compact key-figures header
    (account.total_equity/daily_realized_pnl).
  - narrative None (or blank) -> a DETERMINISTIC 4-block Markdown template
    (watch/account/holdings/strategy), each section independently
    degrading to a "no data" placeholder rather than raising or omitting
    the section (mirrors build_eod_digest's own failure-harmless
    contract).

Both paths funnel through the EXISTING `_send_message`/`_split_message`
4000-char chunking -- this test proves delegation (a long body causes
multiple `bot.send_message` calls) rather than re-testing chunking's own
internals (already exercised implicitly by every other send_* method).

Gate: TELEGRAM_NOTIFY_DAILY_SUMMARY (new, default True) short-circuits
before any formatting/send happens (mirrors every other TELEGRAM_NOTIFY_*
category gate). The `is_configured` master gate is exercised through the
pre-existing `_send_message` initialized/bot check -- no separate branch
to duplicate.
"""

from unittest.mock import AsyncMock

import pytest

from services.telegram.config import TelegramConfig
from services.telegram.service import TelegramNotifier

pytestmark = pytest.mark.asyncio


def _configured_notifier(notify_daily_summary: bool = True) -> TelegramNotifier:
    """A notifier that is 'ready' (initialized + fake bot) without touching
    the network -- mirrors how initialize() would leave it after a real
    successful connect, but deterministic for tests."""
    config = TelegramConfig(
        TELEGRAM_ENABLED=True,
        TELEGRAM_BOT_TOKEN="test-token",
        TELEGRAM_CHAT_ID="12345",
        TELEGRAM_NOTIFY_DAILY_SUMMARY=notify_daily_summary,
    )
    notifier = TelegramNotifier(config=config)
    notifier._initialized = True
    notifier._bot = AsyncMock()
    return notifier


def _unconfigured_notifier() -> TelegramNotifier:
    """Never initialized (mirrors a real deployment with no bot token) --
    exercises the master `is_configured` gate via the untouched
    `_send_message` initialized/bot check."""
    config = TelegramConfig(
        TELEGRAM_ENABLED=False,
        TELEGRAM_BOT_TOKEN=None,
        TELEGRAM_CHAT_ID=None,
    )
    return TelegramNotifier(config=config)


_DIGEST = {
    "trade_date": "2026-07-17",
    "watch": [
        {
            "ticker": "005930",
            "stock_name": "삼성전자",
            "signal": "buy",
            "confidence": 0.7,
            "current_price": 71000,
            "target_entry_price": 70000,
            "gap_pct": 1.43,
        }
    ],
    "account": {
        "deposit": 10_000_000,
        "total_equity": 52_000_000,
        "daily_realized_pnl": 350_000,
        "cumulative_return_pct": 4.2,
    },
    "holdings": [
        {
            "ticker": "000660",
            "stock_name": "SK하이닉스",
            "quantity": 10,
            "avg_price": 200_000,
            "current_price": 210_000,
            "unrealized_pnl": 100_000,
            "unrealized_pnl_pct": 5.0,
            "stop_loss": 190_000,
            "take_profit": 230_000,
        }
    ],
    "strategy": {
        "stance": "neutral",
        "rationale_excerpt": "변동성 확대 구간 — 신규 진입 축소 권고",
        "key_knobs": {
            "stop_loss_pct": -5.0,
            "take_profit_pct": 10.0,
            "max_position_pct": 20.0,
            "max_trade_notional_pct": 15.0,
        },
        "changed": True,
    },
    "regime": {
        "label": "risk_on",
        "index_kospi_chg_pct": 0.8,
        "index_kosdaq_chg_pct": 1.1,
    },
}

_EMPTY_DIGEST = {
    "trade_date": "2026-07-17",
    "watch": [],
    "account": {
        "deposit": None,
        "total_equity": None,
        "daily_realized_pnl": None,
        "cumulative_return_pct": None,
    },
    "holdings": [],
    "strategy": None,
    "regime": None,
}


# -------------------------------------------
# Gate: TELEGRAM_NOTIFY_DAILY_SUMMARY
# -------------------------------------------


async def test_gate_off_skips_send_entirely():
    notifier = _configured_notifier(notify_daily_summary=False)

    result = await notifier.send_daily_summary(_DIGEST, narrative="오늘 요약")

    assert result is False
    notifier._bot.send_message.assert_not_called()


# -------------------------------------------
# Master gate: is_configured (via the untouched _send_message check)
# -------------------------------------------


async def test_not_configured_skips_send():
    notifier = _unconfigured_notifier()

    result = await notifier.send_daily_summary(_DIGEST, narrative="오늘 요약")

    assert result is False


# -------------------------------------------
# narrative path
# -------------------------------------------


async def test_narrative_path_sends_narrative_body_with_key_figures():
    notifier = _configured_notifier()

    result = await notifier.send_daily_summary(_DIGEST, narrative="오늘은 순조로운 하루였습니다.")

    assert result is True
    notifier._bot.send_message.assert_called_once()
    sent_text = notifier._bot.send_message.call_args.kwargs["text"]
    assert "오늘은 순조로운 하루였습니다." in sent_text
    # Key figures header pulled from digest.account, not re-derived.
    assert "52,000,000" in sent_text
    assert "350,000" in sent_text
    # narrative path must NOT fall through to the deterministic template.
    assert "워치리스트" not in sent_text


async def test_narrative_path_with_falsy_narrative_falls_back_to_template():
    """Empty-string narrative is falsy -- must be treated like None (LLM
    returned a blank response) and use the deterministic template, not send
    an empty narrative body."""
    notifier = _configured_notifier()

    result = await notifier.send_daily_summary(_DIGEST, narrative="")

    assert result is True
    sent_text = notifier._bot.send_message.call_args.kwargs["text"]
    assert "워치리스트" in sent_text


# -------------------------------------------
# deterministic template fallback (narrative=None)
# -------------------------------------------


async def test_template_fallback_renders_all_four_blocks():
    notifier = _configured_notifier()

    result = await notifier.send_daily_summary(_DIGEST, narrative=None)

    assert result is True
    sent_text = notifier._bot.send_message.call_args.kwargs["text"]

    # 4 blocks present.
    assert "워치리스트" in sent_text
    assert "계좌" in sent_text
    assert "보유" in sent_text
    assert "전략" in sent_text

    # Concrete values rendered, not placeholders.
    assert "삼성전자" in sent_text
    assert "SK하이닉스" in sent_text
    assert "52,000,000" in sent_text
    assert "neutral" in sent_text


async def test_template_fallback_none_sections_show_no_data_placeholders():
    notifier = _configured_notifier()

    result = await notifier.send_daily_summary(_EMPTY_DIGEST, narrative=None)

    assert result is True
    sent_text = notifier._bot.send_message.call_args.kwargs["text"]

    assert "데이터 없음" in sent_text  # watch and/or strategy section
    assert "보유 종목 없음" in sent_text  # empty holdings


async def test_template_fallback_missing_account_dict_does_not_raise():
    digest = dict(_EMPTY_DIGEST)
    digest["account"] = None

    result = await _configured_notifier().send_daily_summary(digest, narrative=None)

    assert result is True


# -------------------------------------------
# 4000-char split delegation
# -------------------------------------------


async def test_long_narrative_delegates_to_existing_split(monkeypatch):
    notifier = _configured_notifier()
    split_calls = []
    original_split = notifier._split_message

    def _spy_split(text, max_length=4000):
        split_calls.append(text)
        return original_split(text, max_length)

    monkeypatch.setattr(notifier, "_split_message", _spy_split)

    long_narrative = "가나다라마바사아자차카타파하. " * 400  # well over 4000 chars
    result = await notifier.send_daily_summary(_DIGEST, narrative=long_narrative)

    assert result is True
    assert len(split_calls) == 1  # send_daily_summary doesn't chunk itself...
    assert notifier._bot.send_message.call_count > 1  # ...but _send_message did.


# -------------------------------------------
# Minor (DS-5 review fix): optional discovery block in the deterministic
# fallback template -- digest.get("discovery") present -> append a
# 승격(promoted) 종목 요약; absent (every fixture above) -> output stays
# byte-for-byte the same as before this fix. Existing 4-block
# format/order must remain untouched either way.
# -------------------------------------------

_DISCOVERY_DIGEST = {
    **_DIGEST,
    "discovery": {
        "promoted": [
            {
                "ticker": "005930",
                "name": "삼성전자",
                "composite_score": 87.5,
                "top_strategy_tag": "momentum",
            },
            {
                "ticker": "000660",
                "name": "SK하이닉스",
                "composite_score": 81.2,
                "top_strategy_tag": "value",
            },
        ],
        "skip_counts": {"quality_filter": 12},
        "total_candidates": 20,
        "prev_day": {
            "trade_date": "2026-07-16",
            "candidate_count": 18,
            "fwd_1d_filled_count": 18,
            "avg_fwd_1d": 1.2,
        },
    },
}


async def test_template_fallback_with_discovery_includes_promoted_stocks():
    notifier = _configured_notifier()

    result = await notifier.send_daily_summary(_DISCOVERY_DIGEST, narrative=None)

    assert result is True
    sent_text = notifier._bot.send_message.call_args.kwargs["text"]

    assert "발굴" in sent_text
    assert "삼성전자" in sent_text
    assert "005930" in sent_text
    assert "87.5" in sent_text
    assert "SK하이닉스" in sent_text

    # Existing 4 blocks still present, same relative order.
    assert (
        sent_text.index("워치리스트")
        < sent_text.index("계좌")
        < sent_text.index("보유")
        < sent_text.index("전략")
        < sent_text.index("발굴")
    )


async def test_template_fallback_discovery_absent_output_unchanged():
    """digest에 "discovery" 키가 없으면(이 파일의 기존 모든 픽스처가 그렇듯)
    폴백 출력에 발굴 블록이 전혀 추가되지 않는다 -- 키 부재 안전."""
    notifier = _configured_notifier()
    assert "discovery" not in _DIGEST

    result = await notifier.send_daily_summary(_DIGEST, narrative=None)

    assert result is True
    sent_text = notifier._bot.send_message.call_args.kwargs["text"]
    assert "발굴" not in sent_text


async def test_template_fallback_discovery_present_but_empty_promoted_no_crash():
    notifier = _configured_notifier()
    digest = {**_DIGEST, "discovery": {"promoted": [], "skip_counts": {}, "total_candidates": 0, "prev_day": None}}

    result = await notifier.send_daily_summary(digest, narrative=None)

    assert result is True
    sent_text = notifier._bot.send_message.call_args.kwargs["text"]
    assert "발굴" in sent_text
    assert "승격 없음" in sent_text
