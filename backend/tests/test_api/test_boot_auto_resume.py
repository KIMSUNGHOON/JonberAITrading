"""재시작 안전 Task 4: lifespan 부팅 재개 블록.

_boot_auto_resume()은 절대 raise하지 않는다 — 방어 복원 실패가 서버
부팅 자체를 막아선 안 된다. 다만 무성 실패도 금지라, 실패는 로그와
Telegram 양쪽에 남는다.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import _boot_auto_resume

pytestmark = pytest.mark.asyncio


def _coordinators(trading_result=True, chat_result=True):
    trading = MagicMock()
    trading.resume_if_persisted = AsyncMock(return_value=trading_result)
    chat = MagicMock()
    chat.resume_if_persisted = AsyncMock(return_value=chat_result)
    return trading, chat


async def test_resumes_both_coordinators():
    trading, chat = _coordinators()
    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(return_value=trading)), \
         patch("services.agent_chat.coordinator.get_chat_coordinator",
               new=AsyncMock(return_value=chat)), \
         patch("app.main.settings") as s:
        s.BOOT_AUTO_RESUME_ENABLED = True
        await _boot_auto_resume()

    trading.resume_if_persisted.assert_awaited_once()
    chat.resume_if_persisted.assert_awaited_once()


async def test_killswitch_off_touches_nothing():
    trading, chat = _coordinators()
    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(return_value=trading)), \
         patch("services.agent_chat.coordinator.get_chat_coordinator",
               new=AsyncMock(return_value=chat)), \
         patch("app.main.settings") as s:
        s.BOOT_AUTO_RESUME_ENABLED = False
        await _boot_auto_resume()

    trading.resume_if_persisted.assert_not_awaited()
    chat.resume_if_persisted.assert_not_awaited()


async def test_exception_never_propagates_and_alerts():
    """트레이딩 재개가 터져도 부팅은 계속되고, 실패 사실이 Telegram으로
    나간다 — 방어를 못 켠 것은 조용히 넘어갈 일이 아니다."""
    trading = MagicMock()
    trading.resume_if_persisted = AsyncMock(side_effect=RuntimeError("kiwoom down"))
    chat = MagicMock()
    chat.resume_if_persisted = AsyncMock(return_value=False)

    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_system_status = AsyncMock()

    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(return_value=trading)), \
         patch("services.agent_chat.coordinator.get_chat_coordinator",
               new=AsyncMock(return_value=chat)), \
         patch("app.main.get_telegram_notifier",
               new=AsyncMock(return_value=notifier)), \
         patch("app.main.settings") as s:
        s.BOOT_AUTO_RESUME_ENABLED = True
        await _boot_auto_resume()  # raise하지 않아야 한다

    notifier.send_system_status.assert_awaited_once()


async def test_telegram_failure_does_not_propagate():
    """알림 전송까지 실패하는 이중 실패에서도 부팅은 계속된다.

    두 개를 검증한다: (1) 예외가 밖으로 새지 않는다, (2) Telegram 경로를
    실제로 **시도했다** — 시도조차 안 하고 조용히 넘어가면 이 테스트는
    통과하면서 무성 실패를 눈감아 준다.
    """
    trading = MagicMock()
    trading.resume_if_persisted = AsyncMock(side_effect=RuntimeError("boom"))
    chat = MagicMock()
    chat.resume_if_persisted = AsyncMock(return_value=False)
    notifier_factory = AsyncMock(side_effect=RuntimeError("telegram down"))

    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(return_value=trading)), \
         patch("services.agent_chat.coordinator.get_chat_coordinator",
               new=AsyncMock(return_value=chat)), \
         patch("app.main.get_telegram_notifier", new=notifier_factory), \
         patch("app.main.settings") as s:
        s.BOOT_AUTO_RESUME_ENABLED = True
        await _boot_auto_resume()  # raise하지 않아야 한다

    notifier_factory.assert_awaited_once()


async def test_timeout_does_not_block_boot():
    """start()가 키움 응답을 기다리며 영영 멈춰도 부팅은 진행된다."""
    async def _hang():
        await asyncio.sleep(3600)

    trading = MagicMock()
    trading.resume_if_persisted = _hang  # 코루틴 함수를 직접 붙인다
    chat = MagicMock()
    chat.resume_if_persisted = AsyncMock(return_value=False)

    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_system_status = AsyncMock()

    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(return_value=trading)), \
         patch("services.agent_chat.coordinator.get_chat_coordinator",
               new=AsyncMock(return_value=chat)), \
         patch("app.main.get_telegram_notifier",
               new=AsyncMock(return_value=notifier)), \
         patch("app.main.BOOT_AUTO_RESUME_TIMEOUT_S", 0.05), \
         patch("app.main.settings") as s:
        s.BOOT_AUTO_RESUME_ENABLED = True
        await asyncio.wait_for(_boot_auto_resume(), timeout=5)

    notifier.send_system_status.assert_awaited_once()
