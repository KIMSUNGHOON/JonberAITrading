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

from unittest.mock import MagicMock, patch

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
