"""통지 광역화 Task 3: 수신부 하드닝.

세 가지를 막는다.
1) 4,096자 초과 — 넘기면 데이터가 통째로 사라지고 '오류: Message is too long'
   한 줄만 온다. 분할이 아니라 절단을 택한 이유는 폰에서 3연속 메시지가 읽히지
   않고, 청크 연속 발송이 초당 1건 권고를 넘겨 429를 유발하며, 그 429를
   _send_message가 조용히 삼키기 때문이다. 게다가 분할은 기존 테스트 약 20곳의
   assert_awaited_once 계약을 깬다.
2) 빈값/실패/미설정 구별 불가 — 현재 _format_positions(None)과 holding=null이
   바이트 동일하다.
3) 연속 발송 429 — /pending이 지연 없이 항목마다 별도 메시지를 보낸다.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.telegram.commands import _reply, source_status

pytestmark = pytest.mark.asyncio


def _make_update():
    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    return update


async def test_reply_truncates_over_limit_and_stays_single_call():
    """3,900자를 넘으면 절단한다 — 분할하지 않는다(기존 테스트 계약 유지)."""
    update = _make_update()
    long_text = "가" * 5000

    await _reply(update, long_text)

    update.effective_message.reply_text.assert_awaited_once()
    sent = update.effective_message.reply_text.await_args.args[0]
    assert len(sent) <= 3900
    assert "이하 생략" in sent


async def test_reply_leaves_short_text_untouched():
    update = _make_update()
    await _reply(update, "짧은 응답")
    update.effective_message.reply_text.assert_awaited_once_with("짧은 응답")


async def test_reply_truncates_at_line_boundary():
    """줄 중간을 자르지 않는다 — 현재 300자 하드컷이 '...breadth br'처럼 단어를 자른다."""
    update = _make_update()
    body = "\n".join(f"{i}번째 줄입니다" for i in range(1000))

    await _reply(update, body)

    sent = update.effective_message.reply_text.await_args.args[0]
    head = sent.split("\n…이하 생략")[0]
    assert head.endswith("줄입니다")


def test_source_status_distinguishes_three_states():
    """'데이터 없음' 단일 문자열 금지 — 세 상태가 구별돼야 한다."""
    assert source_status([], None) == "0건"
    assert source_status(None, "timeout") == "조회 실패(timeout)"
    assert source_status(None, None) == "조회 실패"
    assert source_status(None, "미설정") == "조회 실패(미설정)"
    assert source_status([1, 2], None) == "2건"
