"""통지 광역화 Task 5: 레지스트리 메타 + /help 2단 + setMyCommands.

현재 /help는 이름만 나열하고(docstring이 그렇게 적혀 있다), parse_mode 없이
'*사용 가능한 명령어*'를 보내 별표가 리터럴로 노출되며, sorted() 나열이라
/auto(자율 재개)가 조회 명령과 나란히 첫 줄에 뜬다.

별도 설명 dict를 두면 '등록됐지만 /help에 없는 명령'이 반드시 생기므로
레지스트리를 단일 출처로 만든다. 기존 호출부가 깨지지 않도록 새 인자는
전부 optional이다.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.telegram import receiver

pytestmark = pytest.mark.asyncio


async def _noop(update, context):
    return None


def _install(monkeypatch):
    """레지스트리를 격리한다 — 전역을 건드리면 다른 테스트가 오염된다."""
    monkeypatch.setattr(receiver, "_COMMAND_REGISTRY", {}, raising=False)
    monkeypatch.setattr(receiver, "_COMMAND_META", {}, raising=False)


def test_register_command_accepts_metadata(monkeypatch):
    _install(monkeypatch)
    receiver.register_command(
        "positions", _noop,
        summary="보유 종목·실효 손절 여유",
        group="지금 상태",
        risk="read",
        usage="/positions",
        detail="목적: 지금 손절까지 얼마 남았나",
        caution="손절이 엔진마다 다르면 둘 다 표시",
    )
    meta = receiver._COMMAND_META["positions"]
    assert meta.summary == "보유 종목·실효 손절 여유"
    assert meta.group == "지금 상태"
    assert meta.risk == "read"


def test_register_command_backward_compatible(monkeypatch):
    """기존 6개 호출부가 깨지면 안 된다 — 메타 없이도 등록된다."""
    _install(monkeypatch)
    receiver.register_command("legacy", _noop)
    assert "legacy" in receiver._COMMAND_REGISTRY
    assert receiver._COMMAND_META["legacy"].risk == "read"


async def test_help_groups_and_puts_mutate_last(monkeypatch):
    _install(monkeypatch)
    receiver.register_command("positions", _noop, summary="보유 종목", group="지금 상태")
    receiver.register_command("pnl", _noop, summary="실현손익", group="성과")
    receiver.register_command("auto", _noop, summary="자율 재개", group="상태를 바꿈", risk="mutate")

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()

    await receiver._handle_help(update, MagicMock())

    sent = update.effective_message.reply_text.await_args.args[0]
    assert "*" not in sent, "평문이어야 한다 — 별표가 리터럴로 노출되던 버그"
    assert sent.index("/positions") < sent.index("/auto"), "mutate는 맨 아래"
    assert "지금 상태" in sent and "성과" in sent


async def test_help_detail_for_single_command(monkeypatch):
    _install(monkeypatch)
    receiver.register_command(
        "positions", _noop, summary="보유 종목", group="지금 상태",
        usage="/positions", detail="목적: 지금 손절까지 얼마 남았나",
        caution="엔진마다 다르면 둘 다 표시",
    )
    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["positions"]

    await receiver._handle_help(update, context)

    sent = update.effective_message.reply_text.await_args.args[0]
    assert "목적: 지금 손절까지 얼마 남았나" in sent
    assert "엔진마다 다르면" in sent


async def test_help_unknown_command_suggests(monkeypatch):
    _install(monkeypatch)
    receiver.register_command("positions", _noop, summary="보유 종목", group="지금 상태")
    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["position"]

    await receiver._handle_help(update, context)

    sent = update.effective_message.reply_text.await_args.args[0]
    assert "positions" in sent


async def test_build_bot_commands_uses_summary(monkeypatch):
    """setMyCommands에 보낼 목록이 레지스트리 메타에서 나온다."""
    _install(monkeypatch)
    receiver.register_command("positions", _noop, summary="보유 종목·실효 손절 여유", group="지금 상태")
    receiver.register_command("nometa", _noop)

    cmds = receiver._build_bot_commands()
    by_name = {c.command: c.description for c in cmds}
    assert by_name["positions"] == "보유 종목·실효 손절 여유"
    assert by_name["nometa"]  # 빈 설명은 Telegram이 거부한다 — 폴백이 있어야 한다
