"""통지 광역화 Task 4: 상태 변경 명령의 per-user 검증.

발신자 검증은 이미 있다(receiver.py:117 _authorized, fail-closed). 재구현하지
않는다. 잔여 갭은 기준이 effective_chat.id뿐이라는 것 — TELEGRAM_CHAT_ID를
그룹(음수 id)으로 바꾸면 그룹원 전원이 /halt를 칠 수 있다.

/halt는 '신규 매수 차단'이 아니라 '자동 손절 무장해제'다. 게이트 2단계가
mode != autonomous면 거부하고(gate.py:279) PM의 전량청산이 바로 그 게이트를
통과해야 주문을 낸다. 오조작 비용이 비대칭이라 mutate만 한 겹 더 막는다.

미설정(TELEGRAM_ADMIN_USER_ID 없음)이면 현행 동작을 그대로 유지한다 —
새 설정을 강제하면 기존 운용이 갑자기 막힌다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import structlog.testing

from services.telegram import callbacks, commands, receiver
from services.telegram.config import TelegramConfig
from services.telegram.receiver import _user_allowed_for_mutate


def _update(user_id):
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    return update


def test_unset_admin_id_keeps_current_behavior():
    """미설정이면 통과 — 새 설정을 강제해 기존 운용을 막지 않는다."""
    cfg = MagicMock()
    cfg.TELEGRAM_ADMIN_USER_ID = None
    with patch("services.telegram.receiver.get_telegram_config", return_value=cfg):
        assert _user_allowed_for_mutate(_update(999)) is True


def test_matching_user_allowed():
    cfg = MagicMock()
    cfg.TELEGRAM_ADMIN_USER_ID = "6857067846"
    with patch("services.telegram.receiver.get_telegram_config", return_value=cfg):
        assert _user_allowed_for_mutate(_update(6857067846)) is True


def test_other_user_denied():
    cfg = MagicMock()
    cfg.TELEGRAM_ADMIN_USER_ID = "6857067846"
    with patch("services.telegram.receiver.get_telegram_config", return_value=cfg):
        assert _user_allowed_for_mutate(_update(111)) is False


def test_missing_user_denied_when_configured():
    """설정돼 있는데 발신자를 알 수 없으면 fail-closed."""
    cfg = MagicMock()
    cfg.TELEGRAM_ADMIN_USER_ID = "6857067846"
    update = MagicMock()
    update.effective_user = None
    with patch("services.telegram.receiver.get_telegram_config", return_value=cfg):
        assert _user_allowed_for_mutate(update) is False


# -------------------------------------------
# 리뷰 픽스(Critical): 위 4개는 _user_allowed_for_mutate를 단위로 검증할 뿐,
# 실제 프로덕션 배선(_wrap_command / _dispatch_callback)이 핸들러 실행 전에
# 실제로 끊어지는지는 증명하지 못한다는 리뷰 지적. test_telegram_receiver.py
# 의 test_help_handler_unauthorized_chat_silently_ignored_and_warns와 같은
# 모양으로 두 경로를 핀한다:
#   - /halt: 명령 자체가 상태를 바꾸므로 _wrap_command 레벨에서 막혀야 한다.
#   - /auto: 명령은 확인 버튼만 보내고, 실제 모드 플립은 그 버튼의 콜백
#     (auto_confirm:, callbacks.py)에서 일어난다 -- 그룹 채팅에서 admin이
#     아닌 사용자가 admin이 띄운 버튼을 눌러도 막혀야 하므로, 실제 디스패치
#     경로(receiver._dispatch_callback)로 검증한다.
# -------------------------------------------


def _tg_config(admin_user_id):
    return TelegramConfig(
        TELEGRAM_ENABLED=True,
        TELEGRAM_BOT_TOKEN="test-token",
        TELEGRAM_CHAT_ID="12345",
        TELEGRAM_ADMIN_USER_ID=admin_user_id,
    )


def _make_command_update(chat_id, user_id):
    """/halt 같은 명령 핸들러용 mock Update -- test_telegram_receiver.py의
    _make_update 관례를 따르되 effective_user도 채운다(실제 Update/Message는
    frozen이라 MagicMock 트리로 구성)."""
    chat = MagicMock()
    chat.id = chat_id
    user = MagicMock()
    user.id = user_id

    message = AsyncMock()

    update = MagicMock()
    update.effective_chat = chat
    update.effective_user = user
    update.effective_message = message
    update.message = message
    return update, message


async def test_wrap_command_blocks_non_admin_halt_in_authorized_chat(monkeypatch):
    """/halt는 확인 단계 없이 명령 자체가 실행부이므로 _wrap_command에서
    막혀야 한다: 인가된 chat이라도 admin이 아니면 핸들러 미실행+무응답+
    telegram_mutate_denied 경고."""
    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _tg_config("6857067846"))
    update, message = _make_command_update(12345, 111)
    handler_calls = []

    async def fake_halt(update, context):
        handler_calls.append(True)

    wrapped = receiver._wrap_command("halt", fake_halt)

    with structlog.testing.capture_logs() as logs:
        await wrapped(update, MagicMock())

    assert handler_calls == []
    message.reply_text.assert_not_called()
    denied = [log for log in logs if log.get("event") == "telegram_mutate_denied"]
    assert len(denied) == 1
    assert denied[0]["command"] == "halt"
    assert denied[0]["user_id"] == 111


async def test_wrap_command_allows_admin_halt_in_authorized_chat(monkeypatch):
    """대조군: admin이 인가된 chat에서 치면 여전히 핸들러까지 도달한다
    (관문이 admin 자신까지 막는 회귀가 없는지 확인)."""
    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _tg_config("6857067846"))
    update, _ = _make_command_update(12345, 6857067846)
    handler_calls = []

    async def fake_halt(update, context):
        handler_calls.append(True)

    wrapped = receiver._wrap_command("halt", fake_halt)

    await wrapped(update, MagicMock())

    assert handler_calls == [True]


def _make_callback_update(chat_id, user_id, data):
    """auto_confirm: 콜백 버튼 탭용 mock Update -- test_telegram_commands.py
    의 _make_callback_update 관례를 따르되 effective_user도 채운다."""
    chat = MagicMock()
    chat.id = chat_id
    user = MagicMock()
    user.id = user_id

    query = AsyncMock()
    query.data = data

    update = MagicMock()
    update.effective_chat = chat
    update.effective_user = user
    update.callback_query = query
    return update, query


async def test_dispatch_callback_blocks_non_admin_auto_confirm_tap(monkeypatch):
    """/auto의 실제 상태 변경(모드 플립)은 명령이 아니라 확인 버튼 콜백에서
    일어난다(commands.handle_auto는 버튼만 보낸다) -- 그룹에서 admin이
    /auto를 쳐서 버튼이 뜬 뒤, admin이 아닌 그룹원이 그 버튼을 눌러도 모드
    플립이 막혀야 한다. 단위 테스트가 아니라 실제 프로덕션 경로
    (receiver._dispatch_callback)로 검증 -- register_callback(...,
    mutate=True)로 표시가 실제로 배선됐는지까지 핀한다."""
    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _tg_config("6857067846"))
    nonce = commands._issue_auto_confirm_nonce()

    set_calls = []

    async def fake_set_mode():
        set_calls.append(True)

    monkeypatch.setattr(callbacks, "_set_kiwoom_autonomous", fake_set_mode)

    rearm_calls = []

    async def fake_rearm():
        rearm_calls.append(True)

    monkeypatch.setattr(callbacks, "_rearm_awaiting_approvals", fake_rearm)

    update, query = _make_callback_update(
        12345, 111, callbacks.AUTO_CONFIRM_CALLBACK_PREFIX + nonce
    )

    with structlog.testing.capture_logs() as logs:
        await receiver._dispatch_callback(update, MagicMock())

    query.answer.assert_not_awaited()
    query.edit_message_text.assert_not_awaited()
    assert set_calls == []
    assert rearm_calls == []
    denied = [log for log in logs if log.get("event") == "telegram_mutate_denied"]
    assert len(denied) == 1
    assert denied[0]["command"] == callbacks.AUTO_CONFIRM_CALLBACK_PREFIX
    assert denied[0]["user_id"] == 111


async def test_dispatch_callback_allows_admin_auto_confirm_tap(monkeypatch):
    """대조군: admin 본인이 확인 버튼을 누르면 여전히 통과해 모드 플립까지
    도달한다 (Critical 리뷰 이전의 기존 동작을 이 픽스가 깨지 않는지 확인)."""
    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _tg_config("6857067846"))
    nonce = commands._issue_auto_confirm_nonce()

    async def fake_set_mode():
        pass

    monkeypatch.setattr(callbacks, "_set_kiwoom_autonomous", fake_set_mode)

    rearm_calls = []

    async def fake_rearm():
        rearm_calls.append(True)

    monkeypatch.setattr(callbacks, "_rearm_awaiting_approvals", fake_rearm)

    update, query = _make_callback_update(
        12345, 6857067846, callbacks.AUTO_CONFIRM_CALLBACK_PREFIX + nonce
    )

    await receiver._dispatch_callback(update, MagicMock())

    query.answer.assert_awaited_once()
    assert rearm_calls == [True]
