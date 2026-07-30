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

리뷰 후속 (전부 애초 브리프의 결함이지 구현 결함이 아니었음):
- Important 1: `source_status`가 문서화한 3번째 상태('미설정')를 자체적으로
  내지 않고 '조회 실패(미설정)'로만 중첩 출력했다 — "조회를 시도했는데
  실패했다: 설정 안 됨"으로 읽혀 자기모순. 이제 `unconfigured=True` 키워드
  인자가 겹치지 않는 '미설정'을 낸다.
- Important 2: `/pending` 한 반복 안에서 버튼 발송 실패(=429였을 수 있음)
  직후 텍스트 폴백이 간격 없이 붙어, 이 태스크가 막으려는 제로갭 쌍이 반복
  한 단계 아래에서 재현됐다. 폴백 앞에도 지연을 둔다.
- Minor 4: 동기 테스트가 모듈 전역 `pytest.mark.asyncio` 아래 있어
  PytestWarning이 났다 — 개별 마킹으로 정리(Important 3 = 0.4→1.0초는
  아래 상수 하나만 바꾸는 문제라 별도 테스트로 그 값만 고정한다).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.telegram import commands
from services.telegram.commands import _reply, source_status


def _make_update():
    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    return update


def _operations(awaiting=None):
    return SimpleNamespace(holding=None, awaiting=awaiting)


def _pending_item():
    return SimpleNamespace(
        session_id="abcd1234efgh", ticker="005930", name="삼성전자",
        proposal={"id": "prop-abcd1234efgh", "action": "BUY"},
        auto_approve_at="2026-07-17T10:05:00+09:00",
        actionable=True,
    )


@pytest.mark.asyncio
async def test_reply_truncates_over_limit_and_stays_single_call():
    """3,900자를 넘으면 절단한다 — 분할하지 않는다(기존 테스트 계약 유지)."""
    update = _make_update()
    long_text = "가" * 5000

    await _reply(update, long_text)

    update.effective_message.reply_text.assert_awaited_once()
    sent = update.effective_message.reply_text.await_args.args[0]
    assert len(sent) <= 3900
    assert "이하 생략" in sent


@pytest.mark.asyncio
async def test_reply_leaves_short_text_untouched():
    update = _make_update()
    await _reply(update, "짧은 응답")
    update.effective_message.reply_text.assert_awaited_once_with("짧은 응답")


@pytest.mark.asyncio
async def test_reply_truncates_at_line_boundary():
    """줄 중간을 자르지 않는다 — 현재 300자 하드컷이 '...breadth br'처럼 단어를 자른다."""
    update = _make_update()
    body = "\n".join(f"{i}번째 줄입니다" for i in range(1000))

    await _reply(update, body)

    sent = update.effective_message.reply_text.await_args.args[0]
    head = sent.split("\n…이하 생략")[0]
    assert head.endswith("줄입니다")


def test_source_status_distinguishes_three_states():
    """'데이터 없음' 단일 문자열 금지 — 세 상태가 서로 겹치지 않고 구별돼야
    한다. '미설정'은 '조회 실패(...)' 안에 중첩되면 안 된다(Important 1)
    — 중첩되면 "조회를 시도했는데 실패했다: 설정 안 됨"으로 읽혀
    자기모순이다."""
    assert source_status([], None) == "0건"
    assert source_status(None, "timeout") == "조회 실패(timeout)"
    assert source_status(None, None) == "조회 실패"
    assert source_status(None, unconfigured=True) == "미설정"
    assert source_status([1, 2], None) == "2건"

    unconfigured = source_status(None, unconfigured=True)
    assert "조회 실패" not in unconfigured
    assert "건" not in unconfigured


def test_pending_send_interval_is_one_second_not_point_four():
    """0.4초는 초당 ~2.5건 페이싱이라 텔레그램의 '초당 1건' 권고를 어긴다
    (Important 3) — 짧은 승인 대기열에서 429로 항목을 잃는 것보다 1초
    기다리는 편이 낫다."""
    assert commands._PENDING_SEND_INTERVAL == 1.0


@pytest.mark.asyncio
async def test_pending_delay_separates_the_fallback_send_from_the_button_send(monkeypatch):
    """버튼 발송이 실패(=429였을 수 있음)한 직후 텍스트 폴백을 간격 없이
    붙이면, 첫 발송이 막 스로틀된 바로 그 시점에 두 번째 발송이 나간다 —
    이 태스크가 막으려는 실패 모드가 반복 한 단계 아래에서 재현된다
    (Important 2). 폴백 앞에도 지연이 있어야 한다."""
    item = _pending_item()
    monkeypatch.setattr(
        commands, "_fetch_operations", AsyncMock(return_value=_operations(awaiting=[item]))
    )

    events = []

    async def fake_button(_item):
        events.append("button")
        return False

    async def fake_reply(_update, text):
        events.append(("reply", text))

    async def fake_sleep(seconds):
        events.append(("sleep", seconds))

    monkeypatch.setattr(commands, "_send_pending_button", fake_button)
    monkeypatch.setattr(commands, "_reply", fake_reply)
    monkeypatch.setattr(commands.asyncio, "sleep", fake_sleep)

    await commands.handle_pending(MagicMock(), MagicMock())

    assert events == [
        ("reply", "[승인 대기] 1건"),
        "button",
        ("sleep", 1.0),
        ("reply", commands._format_pending_line(item)),
        ("sleep", 1.0),
    ]
