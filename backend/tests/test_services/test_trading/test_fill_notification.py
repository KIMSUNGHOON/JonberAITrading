"""통지 광역화 Task 6: 체결 통지.

07-24 자율 손절과 07-27 익절(+350,033원 +9.62%)이 폰 통지 없이 지나갔다.
발송 메서드는 있는데 호출처가 0건이었다.

_record_fill_ledger는 BUY/SELL 초크포인트가 공유하는 지점이라(docstring이
그렇게 명시한다) 여기 하나면 자율·HITL·PM 방어청산이 전부 덮인다.

두 함정:
1) 동기 함수라 await가 안 된다 → create_task + 강참조. 강참조를 안 두면
   GC가 태스크를 수거해 통지가 조용히 사라진다.
2) 첫 줄이 `if not self._persistence_active: return`이다 → 통지는 그 게이트
   **앞**에 둔다. 체결됐으면 원장 기록 여부와 무관하게 알려야 한다.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import OrderRequest, OrderResult, OrderSide

pytestmark = pytest.mark.asyncio


def _coord() -> ExecutionCoordinator:
    return ExecutionCoordinator(kiwoom_client=None)


def _order(side=OrderSide.SELL):
    return OrderRequest(
        ticker="094840", stock_name="슈프리마에이치큐", side=side,
        quantity=1315, price=13550,
    )


def _result(filled=1315, avg=13550):
    r = MagicMock(spec=OrderResult)
    r.parts = None
    r.filled_quantity = filled
    r.requested_quantity = 1315
    r.avg_price = avg
    r.order_id = "ord-1"
    return r


async def test_sell_fill_notifies_with_realized_pnl():
    coord = _coord()
    coord._persistence_active = True
    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_trade_executed = AsyncMock(return_value=True)

    with patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)), \
         patch("services.trading.coordinator.record_trade_fill"):
        coord._record_fill_ledger(
            _order(), _result(), side="sell", entry_or_exit="exit",
            realized_pnl=350033.0, realized_pnl_pct=9.62,
        )
        await coord._drain_notify_tasks()

    notifier.send_trade_executed.assert_awaited_once()
    kwargs = notifier.send_trade_executed.await_args.kwargs
    assert kwargs["realized_pnl"] == 350033.0
    assert kwargs["realized_pnl_pct"] == 9.62


async def test_buy_fill_notifies_without_pnl():
    coord = _coord()
    coord._persistence_active = True
    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_trade_executed = AsyncMock(return_value=True)

    with patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)), \
         patch("services.trading.coordinator.record_trade_fill"):
        coord._record_fill_ledger(
            _order(OrderSide.BUY), _result(), side="buy", entry_or_exit="entry"
        )
        await coord._drain_notify_tasks()

    kwargs = notifier.send_trade_executed.await_args.kwargs
    assert kwargs.get("realized_pnl") is None


async def test_notifies_even_when_persistence_inactive():
    """체결 사실이 원장 기록 여부에 종속되면 안 된다."""
    coord = _coord()
    coord._persistence_active = False
    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_trade_executed = AsyncMock(return_value=True)

    with patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)), \
         patch("services.trading.coordinator.record_trade_fill") as rec:
        coord._record_fill_ledger(_order(), _result(), side="sell", entry_or_exit="exit")
        await coord._drain_notify_tasks()

    notifier.send_trade_executed.assert_awaited_once()
    rec.assert_not_called()  # 원장은 게이트대로 안 쓴다


async def test_partial_fill_is_flagged():
    coord = _coord()
    coord._persistence_active = True
    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_trade_executed = AsyncMock(return_value=True)

    with patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)), \
         patch("services.trading.coordinator.record_trade_fill"):
        coord._record_fill_ledger(
            _order(), _result(filled=500), side="sell", entry_or_exit="exit"
        )
        await coord._drain_notify_tasks()

    assert notifier.send_trade_executed.await_args.kwargs["partial"] is True


async def test_notification_failure_never_breaks_ledger(caplog):
    """통지가 터져도 원장 쓰기는 정상 완료된다.

    리뷰 Important 2: `_drain_notify_tasks`는 태스크 예외를 bare
    `except Exception: pass`로 삼키고, `record_trade_fill`은 태스크가
    스케줄되기 전에 이미 동기로 끝난다 — 그래서 원래 이 테스트는
    `_notify_fill` 내부에서 무슨 예외가 나든(예: structlog kwargs를
    stdlib logger에 넣어 TypeError) 통과했다. `_notify_fill`을 직접
    await해 예외가 새지 않는지, 그리고 caplog로 실제 로그가 남는지까지
    확인한다.
    """
    coord = _coord()
    coord._persistence_active = True

    with patch("services.telegram.get_telegram_notifier",
               new=AsyncMock(side_effect=RuntimeError("telegram down"))), \
         patch("services.trading.coordinator.record_trade_fill") as rec:
        coord._record_fill_ledger(_order(), _result(), side="sell", entry_or_exit="exit")
        rec.assert_called_once()  # 원장 쓰기는 통지 스케줄과 무관하게 이미 끝났다

        with caplog.at_level(logging.ERROR):
            # raise 없이 반환되면 never-raise 계약은 지켜진 것 — 예외가
            # 새면 이 await 자체가 테스트를 실패시킨다.
            await coord._notify_fill(_order(), _result(), side="sell")

        # _record_fill_ledger가 스케줄해둔 태스크(위)도 같은 mock으로
        # 실패하므로, 여기서 마저 비워 "Task exception was never retrieved"
        # 경고 없이 정리한다.
        await coord._drain_notify_tasks()

    assert "fill_notification_failed" in caplog.text


async def test_killswitch_off_suppresses_notification():
    coord = _coord()
    coord._persistence_active = True
    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_trade_executed = AsyncMock(return_value=True)

    cfg = MagicMock()
    cfg.TELEGRAM_NOTIFY_FILL_ENABLED = False

    with patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)), \
         patch("services.trading.coordinator.record_trade_fill"), \
         patch("services.telegram.config.get_telegram_config", return_value=cfg):
        coord._record_fill_ledger(_order(), _result(), side="sell", entry_or_exit="exit")
        await coord._drain_notify_tasks()

    notifier.send_trade_executed.assert_not_awaited()
