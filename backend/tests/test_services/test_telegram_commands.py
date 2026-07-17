"""TG-2: 조회 명령 4종 (services/telegram/commands.py).

Covers the task brief's Step 1 contract for each command:

  - a happy path with mocked sources -> reply text pins the command's core
    field(s) (모드/포지션 수/pending 수/리포트 날짜).
  - a source-failure path -> never raises, replies with a "데이터 없음"
    style fallback for the failed section instead.

Sources are injected at the `commands._fetch_*` boundary (the module's own
mock-injection seam, see its docstring) for the format/fallback tests, plus
a handful of "wiring" tests that monkeypatch the REAL underlying functions
(app.api.routes.settings._trading_mode_response,
app.dependencies.get_trading_coordinator, ...) to pin that each `_fetch_*`
helper actually reaches the source location the task brief/spec point at,
not just some internal mock boundary.

No real network/DB anywhere: `get_trading_coordinator`/`get_storage_service`
are always monkeypatched, matching this task's constraint (no real Kiwoom
singleton construction, no real SQLite). Update objects follow the repo's
established MagicMock/AsyncMock-tree convention (PTB objects are frozen) --
see test_telegram_receiver.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.telegram import commands

pytestmark = pytest.mark.asyncio


def _make_update():
    """A MagicMock tree standing in for a PTB Update -- mirrors
    test_telegram_receiver.py's `_make_update` (real Update/Message objects
    are frozen)."""
    chat = MagicMock()
    chat.id = 12345

    message = AsyncMock()

    update = MagicMock()
    update.effective_chat = chat
    update.effective_message = message
    update.message = message
    return update, message


async def _reply_text(message) -> str:
    message.reply_text.assert_awaited_once()
    return message.reply_text.await_args.args[0]


# -------------------------------------------
# /status
# -------------------------------------------


async def test_status_reports_core_fields_when_sources_succeed(monkeypatch):
    mode = SimpleNamespace(kiwoom="autonomous", coin="hitl", master_enabled=True)
    trading_status = SimpleNamespace(
        mode="autonomous", is_active=True, started_at=None,
        daily_trades=3, max_daily_trades=10, pending_alerts_count=2,
    )
    market_status = SimpleNamespace(
        market="KRX", name="Korea Exchange", is_open=True,
        message="장 운영 중", current_time="2026-07-17T10:00:00+09:00",
        next_open=None, next_close=None, countdown_seconds=100,
    )
    heartbeat = SimpleNamespace(
        is_running=True, active_discussions=1, total_sessions=5,
        check_interval_minutes=1, max_concurrent_discussions=3,
        last_check_at="2026-07-17T09:59:00+09:00",
    )

    monkeypatch.setattr(commands, "_fetch_trading_mode", AsyncMock(return_value=mode))
    monkeypatch.setattr(commands, "_fetch_trading_status", AsyncMock(return_value=trading_status))
    monkeypatch.setattr(commands, "_fetch_market_status", AsyncMock(return_value=market_status))
    monkeypatch.setattr(commands, "_fetch_chat_heartbeat", AsyncMock(return_value=heartbeat))

    update, message = _make_update()
    await commands.handle_status(update, MagicMock())

    text = await _reply_text(message)
    assert "모드" in text
    assert "autonomous" in text
    assert "hitl" in text
    assert "개장" in text
    assert "가동중" in text


async def test_status_falls_back_to_no_data_when_all_sources_fail(monkeypatch):
    monkeypatch.setattr(
        commands, "_fetch_trading_mode", AsyncMock(side_effect=RuntimeError("boom"))
    )
    monkeypatch.setattr(
        commands, "_fetch_trading_status", AsyncMock(side_effect=RuntimeError("boom"))
    )
    monkeypatch.setattr(
        commands, "_fetch_market_status", AsyncMock(side_effect=RuntimeError("boom"))
    )
    monkeypatch.setattr(
        commands, "_fetch_chat_heartbeat", AsyncMock(side_effect=RuntimeError("boom"))
    )

    update, message = _make_update()
    await commands.handle_status(update, MagicMock())  # must not raise

    text = await _reply_text(message)
    assert text.count(commands._NO_DATA) == 4


async def test_fetch_trading_mode_wires_to_settings_response_builder(monkeypatch):
    """Wiring pin: _fetch_trading_mode must actually call the real
    settings.py:125-133 response builder, not some other source."""
    import app.api.routes.settings as settings_routes

    sentinel = SimpleNamespace(kiwoom="hitl", coin="hitl", master_enabled=False)
    monkeypatch.setattr(
        settings_routes, "_trading_mode_response", AsyncMock(return_value=sentinel)
    )

    result = await commands._fetch_trading_mode()

    assert result is sentinel


async def test_fetch_trading_status_wires_to_trading_route_and_coordinator_dep(monkeypatch):
    """Wiring pin: _fetch_trading_status must resolve the coordinator via
    app.dependencies.get_trading_coordinator (not construct one itself) and
    pass it into trading.py's get_trading_status."""
    import app.api.routes.trading as trading_routes
    import app.dependencies as deps

    fake_coordinator = MagicMock()
    monkeypatch.setattr(deps, "get_trading_coordinator", AsyncMock(return_value=fake_coordinator))

    captured = {}

    async def _fake_get_trading_status(coordinator=None):
        captured["coordinator"] = coordinator
        return SimpleNamespace(
            mode="hitl", is_active=False, started_at=None,
            daily_trades=0, max_daily_trades=5, pending_alerts_count=0,
        )

    monkeypatch.setattr(trading_routes, "get_trading_status", _fake_get_trading_status)

    result = await commands._fetch_trading_status()

    assert captured["coordinator"] is fake_coordinator
    assert result.max_daily_trades == 5


async def test_fetch_market_status_wires_to_trading_route(monkeypatch):
    import app.api.routes.trading as trading_routes

    sentinel = SimpleNamespace(is_open=False, message="휴장")
    fake = AsyncMock(return_value=sentinel)
    monkeypatch.setattr(trading_routes, "get_market_status", fake)

    result = await commands._fetch_market_status()

    fake.assert_awaited_once_with(market="krx")
    assert result is sentinel


async def test_fetch_chat_heartbeat_wires_to_agent_chat_route(monkeypatch):
    import app.api.routes.agent_chat as agent_chat_routes

    sentinel = SimpleNamespace(is_running=False, active_discussions=0, last_check_at=None)
    monkeypatch.setattr(
        agent_chat_routes, "get_coordinator_status", AsyncMock(return_value=sentinel)
    )

    result = await commands._fetch_chat_heartbeat()

    assert result is sentinel


# -------------------------------------------
# /positions
# -------------------------------------------


def _operations(holding=None, awaiting=None):
    return SimpleNamespace(holding=holding, awaiting=awaiting)


async def test_positions_reports_position_count_when_source_succeeds(monkeypatch):
    holdings = [
        SimpleNamespace(
            ticker="005930", name="삼성전자", quantity=10,
            avg_price=70000.0, current_price=71000.0,
            pnl=10000.0, pnl_pct=1.43, stop_loss=None, take_profit=None,
        ),
        SimpleNamespace(
            ticker="000660", name="SK하이닉스", quantity=5,
            avg_price=200000.0, current_price=190000.0,
            pnl=-50000.0, pnl_pct=-5.0, stop_loss=180000.0, take_profit=None,
        ),
    ]
    monkeypatch.setattr(
        commands, "_fetch_operations", AsyncMock(return_value=_operations(holding=holdings))
    )

    update, message = _make_update()
    await commands.handle_positions(update, MagicMock())

    text = await _reply_text(message)
    assert "2건" in text
    assert "삼성전자" in text
    assert "SK하이닉스" in text


async def test_positions_falls_back_to_no_data_when_holdings_section_failed(monkeypatch):
    # /operations degrades a failed section to None (errors dict), never a
    # raised exception -- mirror that shape here.
    monkeypatch.setattr(
        commands, "_fetch_operations", AsyncMock(return_value=_operations(holding=None))
    )

    update, message = _make_update()
    await commands.handle_positions(update, MagicMock())  # must not raise

    text = await _reply_text(message)
    assert commands._NO_DATA in text


async def test_positions_falls_back_to_no_data_when_fetch_raises(monkeypatch):
    monkeypatch.setattr(
        commands, "_fetch_operations", AsyncMock(side_effect=RuntimeError("kiwoom down"))
    )

    update, message = _make_update()
    await commands.handle_positions(update, MagicMock())  # must not raise

    text = await _reply_text(message)
    assert commands._NO_DATA in text


async def test_positions_reports_zero_holdings_distinctly_from_no_data(monkeypatch):
    monkeypatch.setattr(
        commands, "_fetch_operations", AsyncMock(return_value=_operations(holding=[]))
    )

    update, message = _make_update()
    await commands.handle_positions(update, MagicMock())

    text = await _reply_text(message)
    assert "0건" in text
    assert commands._NO_DATA not in text


# -------------------------------------------
# /pending
# -------------------------------------------


def _pending_item():
    return SimpleNamespace(
        session_id="abcd1234efgh", ticker="005930", name="삼성전자",
        proposal={"id": "prop-abcd1234efgh", "action": "BUY"},
        auto_approve_at="2026-07-17T10:05:00+09:00",
        actionable=True,
    )


async def test_pending_reports_header_count_and_sends_a_button_per_item(monkeypatch):
    """TG-3 F3: /pending's reply becomes a header + one approve/reject
    inline-keyboard message per item (via `_send_pending_button`) instead of
    a single text block carrying every item's detail."""
    awaiting = [_pending_item()]
    monkeypatch.setattr(
        commands, "_fetch_operations", AsyncMock(return_value=_operations(awaiting=awaiting))
    )
    button_calls = []

    async def fake_button(item):
        button_calls.append(item)
        return True

    monkeypatch.setattr(commands, "_send_pending_button", fake_button)

    update, message = _make_update()
    await commands.handle_pending(update, MagicMock())

    # Header only -- per-item detail moved to the button message, not this
    # reply, and the send succeeded so no text fallback was needed.
    message.reply_text.assert_awaited_once()
    header = message.reply_text.await_args.args[0]
    assert "1건" in header
    assert button_calls == awaiting


async def test_pending_falls_back_to_text_line_when_button_send_fails(monkeypatch):
    awaiting = [_pending_item()]
    monkeypatch.setattr(
        commands, "_fetch_operations", AsyncMock(return_value=_operations(awaiting=awaiting))
    )
    monkeypatch.setattr(commands, "_send_pending_button", AsyncMock(return_value=False))

    update, message = _make_update()
    await commands.handle_pending(update, MagicMock())  # must not raise

    assert message.reply_text.await_count == 2  # header + per-item text fallback
    fallback_text = message.reply_text.await_args.args[0]
    assert "삼성전자" in fallback_text
    assert "BUY" in fallback_text


async def test_pending_reports_zero_pending_distinctly_from_no_data(monkeypatch):
    monkeypatch.setattr(
        commands, "_fetch_operations", AsyncMock(return_value=_operations(awaiting=[]))
    )

    update, message = _make_update()
    await commands.handle_pending(update, MagicMock())

    text = await _reply_text(message)
    assert "0건" in text
    assert commands._NO_DATA not in text


async def test_pending_falls_back_to_no_data_when_source_fails(monkeypatch):
    monkeypatch.setattr(
        commands, "_fetch_operations", AsyncMock(side_effect=RuntimeError("sm down"))
    )

    update, message = _make_update()
    await commands.handle_pending(update, MagicMock())  # must not raise

    text = await _reply_text(message)
    assert commands._NO_DATA in text


async def test_format_pending_line_is_reusable_for_tg3(monkeypatch):
    """Pin the standalone formatting function `_send_pending_button` reuses
    verbatim as its plain-text fallback caption."""
    item = SimpleNamespace(
        session_id="abcd1234efgh", ticker="005930", name="삼성전자",
        proposal={"action": "ADD"}, auto_approve_at="2026-07-17T10:05:00+09:00",
        actionable=True,
    )

    line = commands._format_pending_line(item)

    assert "abcd1234" in line
    assert "삼성전자" in line
    assert "ADD" in line


async def test_send_pending_button_wires_to_notifier_send_approval_request(monkeypatch):
    """Wiring pin: `_send_pending_button` must call the F1 notifier method
    with this item's session_id/proposal/auto_approve_at, market="kiwoom"
    (the only market /pending's source ever covers)."""
    item = _pending_item()
    fake_notifier = MagicMock()
    fake_notifier.send_approval_request = AsyncMock(return_value=True)
    monkeypatch.setattr(commands, "_fetch_notifier", AsyncMock(return_value=fake_notifier))

    result = await commands._send_pending_button(item)

    assert result is True
    fake_notifier.send_approval_request.assert_awaited_once_with(
        "abcd1234efgh", "kiwoom", item.proposal, item.auto_approve_at,
    )


async def test_send_pending_button_returns_false_on_exception(monkeypatch):
    item = _pending_item()

    async def boom():
        raise RuntimeError("bot down")

    monkeypatch.setattr(commands, "_fetch_notifier", boom)

    result = await commands._send_pending_button(item)

    assert result is False


async def test_fetch_operations_wires_to_trading_route_and_coordinator_dep(monkeypatch):
    import app.api.routes.trading as trading_routes
    import app.dependencies as deps

    fake_coordinator = MagicMock()
    monkeypatch.setattr(deps, "get_trading_coordinator", AsyncMock(return_value=fake_coordinator))

    captured = {}

    async def _fake_get_operations(market="kiwoom", coordinator=None):
        captured["market"] = market
        captured["coordinator"] = coordinator
        return _operations(holding=[], awaiting=[])

    monkeypatch.setattr(trading_routes, "get_operations", _fake_get_operations)

    result = await commands._fetch_operations()

    assert captured["coordinator"] is fake_coordinator
    assert captured["market"] == "kiwoom"
    assert result.holding == []


# -------------------------------------------
# /report
# -------------------------------------------


async def test_report_includes_trade_date_when_source_succeeds(monkeypatch):
    import json

    row = {
        "trade_date": "2026-07-17",
        "report_json": json.dumps({
            "digest": {
                "trade_date": "2026-07-17",
                "watch": [],
                "account": {"deposit": 1, "total_equity": 2, "daily_realized_pnl": 3,
                             "cumulative_return_pct": 4.0},
                "holdings": [],
                "strategy": None,
            },
            "narrative": None,
        }),
    }
    monkeypatch.setattr(commands, "_fetch_latest_eod_review", AsyncMock(return_value=row))

    update, message = _make_update()
    await commands.handle_report(update, MagicMock())

    text = await _reply_text(message)
    assert "2026-07-17" in text


async def test_report_falls_back_to_no_data_when_no_rows(monkeypatch):
    monkeypatch.setattr(commands, "_fetch_latest_eod_review", AsyncMock(return_value=None))

    update, message = _make_update()
    await commands.handle_report(update, MagicMock())  # must not raise

    text = await _reply_text(message)
    assert commands._NO_DATA in text


async def test_report_falls_back_to_no_data_when_digest_missing(monkeypatch):
    import json

    row = {"trade_date": "2026-07-17", "report_json": json.dumps({"digest": None})}
    monkeypatch.setattr(commands, "_fetch_latest_eod_review", AsyncMock(return_value=row))

    update, message = _make_update()
    await commands.handle_report(update, MagicMock())

    text = await _reply_text(message)
    assert commands._NO_DATA in text


async def test_report_falls_back_to_no_data_when_report_json_malformed(monkeypatch):
    row = {"trade_date": "2026-07-17", "report_json": "{not-json"}
    monkeypatch.setattr(commands, "_fetch_latest_eod_review", AsyncMock(return_value=row))

    update, message = _make_update()
    await commands.handle_report(update, MagicMock())  # must not raise

    text = await _reply_text(message)
    assert commands._NO_DATA in text


async def test_report_falls_back_to_no_data_when_fetch_raises(monkeypatch):
    monkeypatch.setattr(
        commands, "_fetch_latest_eod_review", AsyncMock(side_effect=RuntimeError("db down"))
    )

    update, message = _make_update()
    await commands.handle_report(update, MagicMock())  # must not raise

    text = await _reply_text(message)
    assert commands._NO_DATA in text


async def test_report_uses_narrative_when_present(monkeypatch):
    import json

    row = {
        "trade_date": "2026-07-17",
        "report_json": json.dumps({
            "digest": {
                "trade_date": "2026-07-17",
                "account": {"total_equity": 100, "daily_realized_pnl": 5},
            },
            "narrative": "오늘은 순매수 우위였습니다.",
        }),
    }
    monkeypatch.setattr(commands, "_fetch_latest_eod_review", AsyncMock(return_value=row))

    update, message = _make_update()
    await commands.handle_report(update, MagicMock())

    text = await _reply_text(message)
    assert "오늘은 순매수 우위였습니다." in text


async def test_fetch_latest_eod_review_wires_to_storage_service(monkeypatch):
    import services.storage_service as storage_module

    fake_storage = MagicMock()
    fake_storage.get_eod_reviews = AsyncMock(return_value=[{"trade_date": "2026-07-17"}])
    monkeypatch.setattr(
        storage_module, "get_storage_service", AsyncMock(return_value=fake_storage)
    )

    result = await commands._fetch_latest_eod_review()

    fake_storage.get_eod_reviews.assert_awaited_once_with(limit=1)
    assert result == {"trade_date": "2026-07-17"}


async def test_fetch_latest_eod_review_returns_none_when_no_rows(monkeypatch):
    import services.storage_service as storage_module

    fake_storage = MagicMock()
    fake_storage.get_eod_reviews = AsyncMock(return_value=[])
    monkeypatch.setattr(
        storage_module, "get_storage_service", AsyncMock(return_value=fake_storage)
    )

    result = await commands._fetch_latest_eod_review()

    assert result is None
