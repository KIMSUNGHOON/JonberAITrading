"""라이브 외부 엔드포인트 가드 — 테스트가 실제 Telegram/Kiwoom에 붙지 못하게.

2026-08-12에 메인 체크아웃에서 전체 스위트를 돌리자 라이브 백엔드 로그에
이것이 18건 쌓였다:

    telegram_receiver_polling_error
      error='Conflict: terminated by other getUpdates request'

**테스트가 라이브 Telegram 봇의 폴링을 빼앗았다.** 장중이었다면 손절·익절
통지가 유실된다. Kiwoom도 같은 레이트리밋을 공유한다(개장 직후 ka10001
초과가 이미 상시로 난다).

`948e9ea`의 DB 가드는 파일만 막는다. 워크트리가 안전한 진짜 이유는 DB
부재가 아니라 **`.env` 부재 = 자격증명 부재**였다. 여기서는 자격증명을
건드리지 않고(설정 테스트를 깨뜨리지 않는다) **전송 계층에서 호스트를**
막는다. PTB 22.5와 Kiwoom 클라이언트가 둘 다 httpx를 쓰므로 한 지점이면 된다.

⚠️ 차단은 **명시된 라이브 호스트만** 한다. localhost/testserver/mock 서버는
그대로 통과해야 한다 — 무차별로 막으면 기존 스위트가 통째로 깨진다.
"""
import httpx
import pytest


@pytest.mark.asyncio
async def test_telegram_api_is_blocked():
    async with httpx.AsyncClient(timeout=5.0) as client:
        with pytest.raises(RuntimeError, match="라이브 엔드포인트"):
            await client.get("https://api.telegram.org/bot0:invalid/getMe")


@pytest.mark.asyncio
async def test_kiwoom_live_api_is_blocked():
    async with httpx.AsyncClient(timeout=5.0) as client:
        with pytest.raises(RuntimeError, match="라이브 엔드포인트"):
            await client.post("https://api.kiwoom.com/oauth2/token")


@pytest.mark.asyncio
async def test_kiwoom_mock_api_is_blocked():
    """모의투자 서버도 막는다 — `KIWOOM_IS_MOCK=true`는 **주문만** 모의고
    레이트리밋·세션은 실물과 같은 자원이다."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        with pytest.raises(RuntimeError, match="라이브 엔드포인트"):
            await client.post("https://mockapi.kiwoom.com/oauth2/token")


def test_sync_client_is_blocked_too():
    """PTB는 async지만 동기 httpx를 쓰는 코드도 있다. 한쪽만 막으면 샌다."""
    with httpx.Client(timeout=5.0) as client:
        with pytest.raises(RuntimeError, match="라이브 엔드포인트"):
            client.get("https://api.telegram.org/bot0:invalid/getMe")


@pytest.mark.asyncio
async def test_localhost_is_not_blocked():
    """가드가 무차별이면 TestClient·로컬 LLM·mock 서버가 전부 죽는다.

    연결 거부(ConnectError)는 정상이다 — 가드가 개입하지 않았다는 뜻이다.
    RuntimeError만 아니면 통과.
    """
    async with httpx.AsyncClient(timeout=2.0) as client:
        try:
            await client.get("http://127.0.0.1:59999/__nothing__")
        except RuntimeError:
            pytest.fail("가드가 localhost를 막았다 — 차단 목록이 너무 넓다")
        except Exception:
            pass  # ConnectError 등은 정상
