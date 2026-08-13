"""재시작 안전 Task 4: lifespan 부팅 재개 블록.

_boot_auto_resume()은 절대 raise하지 않는다 — 방어 복원 실패가 서버
부팅 자체를 막아선 안 된다. 다만 무성 실패도 금지라, 실패는 로그와
Telegram 양쪽에 남는다.
"""

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import _boot_auto_resume

pytestmark = pytest.mark.asyncio

# CRITICAL 1 회귀 가드: legacy Markdown이 이탤릭/볼드/코드 시작으로 읽는
# 문자들 중 하나라도 백슬래시 없이 남아 있으면 안 된다.
_UNESCAPED_MARKDOWN_RE = re.compile(r"(?<!\\)[_*`]")


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
    나간다 — 방어를 못 켠 것은 조용히 넘어갈 일이 아니다.

    에이전트챗의 resume도 반드시 시도됐어야 한다 — 트레이딩(키움) 장애가
    키움과 무관한 에이전트챗 감시까지 막아선 안 된다. 이 assertion이 없으면
    한쪽 실패가 다른 쪽 시도 자체를 막는 회귀가 조용히 통과한다.
    """
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

    trading.resume_if_persisted.assert_awaited_once()
    chat.resume_if_persisted.assert_awaited_once()
    notifier.send_system_status.assert_awaited_once()

    # 알림이 "무엇이" 실패했는지 밝혀야 한다 — 트레이딩만 뭉뚱그려 실패라고
    # 하면 운영자가 에이전트챗은 무사하다고 오인할 수 있다.
    message = notifier.send_system_status.await_args.args[1]
    assert "trading" in message
    assert "kiwoom down" in message


async def test_chat_failure_does_not_block_trading_resume():
    """반대 방향: 에이전트챗 재개가 터져도 트레이딩 재개는 그대로 성공해야
    한다 — 비대칭 실패 어느 쪽으로도 서로를 막지 않는다.

    알림 메시지도 실제로 실패한 쪽(agent_chat)만 가리켜야 한다 — 이미
    성공한 트레이딩의 복구 명령까지 같이 나오면 운영자가 정상인 트레이딩을
    괜히 재확인하게 된다.
    """
    trading = MagicMock()
    trading.resume_if_persisted = AsyncMock(return_value=True)
    chat = MagicMock()
    chat.resume_if_persisted = AsyncMock(side_effect=RuntimeError("chat db down"))

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

    trading.resume_if_persisted.assert_awaited_once()
    chat.resume_if_persisted.assert_awaited_once()
    notifier.send_system_status.assert_awaited_once()

    message = notifier.send_system_status.await_args.args[1]
    # CRITICAL 1: label은 TelegramNotifier._md_escape를 거치므로 "_"가
    # "\_"로 이스케이프된다 — 원문 그대로의 "agent_chat"은 더 이상 부분
    # 문자열로 나타나지 않는다(이스케이프 안 됐다면 Telegram이 이 밑줄을
    # 미종료 이탤릭으로 읽어 400을 뱉고 알림 자체가 조용히 유실됐다).
    # 그래도 운영자가 어느 코디네이터인지 식별할 수 있어야 한다는 요구는
    # 그대로 유지된다 — 이스케이프된 형태로 검증한다.
    assert "agent\\_chat" in message
    assert "chat db down" in message
    assert "/api/agent-chat/start" in message
    # 트레이딩은 성공했으니 트레이딩 복구 명령은 나오면 안 된다.
    assert "/api/trading/start" not in message


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

    # asyncio.TimeoutError는 str(e)가 보통 빈 문자열이라, 타입명이 같이
    # 안 남으면 알림이 "trading 실패() — ..."처럼 원인 없는 문구가 된다.
    message = notifier.send_system_status.await_args.args[1]
    assert "TimeoutError" in message


async def test_alert_has_no_unescaped_markdown_special_chars():
    """CRITICAL 1 회귀 가드.

    label/타입명/str(error) 어디든 이스케이프 안 된 "_"/"*"/"`"가 하나라도
    남아 있으면, legacy Markdown 파서가 그걸 미종료 이탤릭/볼드/코드
    시작으로 읽어 Telegram이 400을 뱉고 `_send_message`가 그 실패를 조용히
    삼킨다 — 방어가 안 켜졌다는 알림 자체가 유실된다. 다음에 누가 새
    라벨이나 예외 메시지를 넣어도 이 테스트가 잡아야 한다.
    """
    trading = MagicMock()
    trading.resume_if_persisted = AsyncMock(
        side_effect=RuntimeError(
            "no such table: app_settings [locked] `pragma_x` *retry*"
        )
    )
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
        await _boot_auto_resume()

    message = notifier.send_system_status.await_args.args[1]
    unescaped = _UNESCAPED_MARKDOWN_RE.findall(message)
    assert unescaped == [], f"unescaped markdown chars in alert: {unescaped!r} ({message!r})"
    # 이스케이프됐어도 운영자가 원인 문구는 여전히 식별할 수 있어야 한다
    # (이스케이프된 형태로: "_"는 "\_"가 된다).
    assert "app\\_settings" in message
    assert "pragma\\_x" in message


async def test_coordinator_acquisition_hang_is_covered_by_timeout():
    """MINOR 5 회귀 가드: get_coordinator() 자체가 멈춰도(예: 키움 싱글턴의
    모듈 전역 락 경합) wait_for 예산 안에서 커버돼야 한다 — 원래는
    get_coordinator()가 wait_for **밖**에서 await돼서, 락이 걸리면 예산과
    무관하게 부팅이 무한정 멈출 수 있었다."""
    async def _hang_get_coordinator():
        await asyncio.sleep(3600)

    chat = MagicMock()
    chat.resume_if_persisted = AsyncMock(return_value=False)

    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_system_status = AsyncMock()

    with patch("app.dependencies.get_trading_coordinator",
               new=_hang_get_coordinator), \
         patch("services.agent_chat.coordinator.get_chat_coordinator",
               new=AsyncMock(return_value=chat)), \
         patch("app.main.get_telegram_notifier",
               new=AsyncMock(return_value=notifier)), \
         patch("app.main.BOOT_AUTO_RESUME_TIMEOUT_S", 0.05), \
         patch("app.main.settings") as s:
        s.BOOT_AUTO_RESUME_ENABLED = True
        # 외부 wait_for(5s)가 안전망이다 — 고쳐지지 않았다면 이 자체가
        # asyncio.TimeoutError로 테스트를 실패시킨다(무한정 멈추는 대신).
        await asyncio.wait_for(_boot_auto_resume(), timeout=5)

    message = notifier.send_system_status.await_args.args[1]
    assert "trading" in message
    assert "TimeoutError" in message
