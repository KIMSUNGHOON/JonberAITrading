"""통지 광역화 최종 전체 브랜치 리뷰 Important 3: `_poll_tracked_fills`가
발견하는 지연 체결이 무통지였던 갭.

`_poll_tracked_fills`는 `record_trade_fill`을 직접 부르고
`_apply_sell_position_delta`로 정산한다 — `_record_fill_ledger`(체결 통지가
붙어 있는 진짜 초크포인트)를 전혀 거치지 않는다. 그 결과 placement 시점에
못 잡은 체결(예: LIMIT BUY가 3폴×0.5초 창을 넘겨 pending으로 등록됐다가
나중에 이 폴이 발견하는 경우, 또는 부분 체결된 방어 SELL의 잔량이 나중에
마저 체결되는 경우)은 전부 조용히 지나갔다. 자율 손절/익절도 지연 체결될
수 있어 실질적이다.

가산적으로 안전하다는 주장(브리프)을 검증한다: 이 폴은 매 틱 "새로 발견된
증분"(delta.new_fill_qty)만 다루므로, delta 단위 `_schedule_fill_notification`은
placement 시점 통지와 절대 겹치지 않는다 — 아래 idempotency 테스트가
동일 틱 재실행 시 재통지가 없음을 직접 고정한다.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.storage_service as ss
from services.kiwoom.models import FilledOrder
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import ManagedPosition
from services.trading.pending_order_tracker import TrackedOrder

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


class _FakeKiwoomClient:
    def __init__(self, filled_orders=None):
        self._filled_orders = filled_orders if filled_orders is not None else []
        self.calls = 0

    async def get_filled_orders(self, sell_tp="0", stex_tp="0", stk_cd=None, use_cache=True):
        self.calls += 1
        return list(self._filled_orders)


def _filled(ord_no, qty, price, buy_sell_tp="매수"):
    return FilledOrder(
        ord_no=ord_no,
        stk_cd="005930",
        stk_nm="삼성전자",
        ccld_qty=qty,
        ccld_uv=price,
        ccld_amt=qty * price,
        ccld_dt="",
        ccld_tm="",
        buy_sell_tp=buy_sell_tp,
    )


def _tracked_order(side, ord_no="ORD1", total=48, filled=0, **kw):
    base = dict(
        ord_no=ord_no,
        ticker="005930",
        stock_name="삼성전자",
        side=side,
        total_quantity=total,
        filled_quantity=filled,
        filled_amount=filled * 260_000,
        limit_price=260_000,
        trade_date=date.today().strftime("%Y%m%d"),
    )
    base.update(kw)
    return TrackedOrder(**base)


def _ready_notifier():
    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_trade_executed = AsyncMock(return_value=True)
    return notifier


async def test_delayed_buy_fill_notifies(temp_storage):
    """RED(회귀 전): 지연 체결된 BUY(LIMIT 주문이 placement 폴 창을 넘겨
    나중에 발견됨)가 이 폴에서 무통지였다."""
    coord = ExecutionCoordinator(
        kiwoom_client=_FakeKiwoomClient(filled_orders=[_filled("ORD1", 48, 260_000)])
    )
    coord.fill_tracker.register(_tracked_order(side="buy", ord_no="ORD1", total=48, filled=0))

    notifier = _ready_notifier()
    with patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)):
        await coord._poll_tracked_fills()
        await coord._drain_notify_tasks()

    notifier.send_trade_executed.assert_awaited_once()
    _, kwargs = notifier.send_trade_executed.call_args
    assert kwargs["ticker"] == "005930"
    assert kwargs["action"] == "BUY"
    assert kwargs["quantity"] == 48
    assert kwargs["price"] == 260_000


async def test_delayed_sell_fill_notifies_with_realized_pnl(temp_storage):
    """자율 손절/익절의 잔량이 지연 체결되는 경우 — 실현손익까지 실려야
    한다(진입가는 포지션이 정산으로 사라지기 전에 읽어야 한다)."""
    coord = ExecutionCoordinator(
        kiwoom_client=_FakeKiwoomClient(filled_orders=[_filled("ORD2", 10, 280_000, buy_sell_tp="매도")])
    )
    coord._add_position(
        ManagedPosition(
            ticker="005930", stock_name="삼성전자", quantity=10,
            avg_price=260_000, current_price=280_000,
        )
    )
    coord.fill_tracker.register(_tracked_order(side="sell", ord_no="ORD2", total=10, filled=0))

    notifier = _ready_notifier()
    with patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)):
        await coord._poll_tracked_fills()
        await coord._drain_notify_tasks()

    notifier.send_trade_executed.assert_awaited_once()
    _, kwargs = notifier.send_trade_executed.call_args
    assert kwargs["action"] == "SELL"
    assert kwargs["quantity"] == 10
    assert kwargs["price"] == 280_000
    assert kwargs["realized_pnl"] == pytest.approx((280_000 - 260_000) * 10)
    assert kwargs["realized_pnl_pct"] == pytest.approx((280_000 / 260_000 - 1) * 100)


async def test_poll_notify_is_not_duplicated_on_idempotent_rerun(temp_storage):
    """같은 스냅샷으로 같은 틱을 재실행해도(멱등) 재통지가 없어야 한다 —
    이 폴은 매번 '새로 발견된 증분'만 다루므로 자연히 중복이 없다는 브리프의
    주장을 직접 고정한다."""
    coord = ExecutionCoordinator(
        kiwoom_client=_FakeKiwoomClient(filled_orders=[_filled("ORD1", 48, 260_000)])
    )
    coord.fill_tracker.register(_tracked_order(side="buy", ord_no="ORD1", total=48, filled=0))

    notifier = _ready_notifier()
    with patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)):
        await coord._poll_tracked_fills()
        await coord._poll_tracked_fills()  # 동일 스냅샷 재폴 — 델타 없음
        await coord._drain_notify_tasks()

    notifier.send_trade_executed.assert_awaited_once()


async def test_delayed_partial_fill_marks_partial(temp_storage):
    """전체 요청량에 못 미치는 지연 체결은 "(부분)"로 정직하게 표시돼야
    한다."""
    coord = ExecutionCoordinator(
        kiwoom_client=_FakeKiwoomClient(filled_orders=[_filled("ORD3", 20, 260_000)])
    )
    coord.fill_tracker.register(_tracked_order(side="buy", ord_no="ORD3", total=48, filled=0))

    notifier = _ready_notifier()
    with patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)):
        await coord._poll_tracked_fills()
        await coord._drain_notify_tasks()

    _, kwargs = notifier.send_trade_executed.call_args
    assert kwargs["quantity"] == 20  # 이번 틱에 새로 발견된 증분만
    assert kwargs["partial"] is True


async def test_poll_fill_notify_respects_kill_switch(temp_storage, monkeypatch):
    """TELEGRAM_NOTIFY_FILL_ENABLED=False면 이 경로도 무통지 — 다른 체결
    통지 경로(_schedule_fill_notification)와 같은 킬스위치를 공유한다."""
    from services.telegram.config import TelegramConfig

    coord = ExecutionCoordinator(
        kiwoom_client=_FakeKiwoomClient(filled_orders=[_filled("ORD4", 48, 260_000)])
    )
    coord.fill_tracker.register(_tracked_order(side="buy", ord_no="ORD4", total=48, filled=0))

    off_config = TelegramConfig(TELEGRAM_NOTIFY_FILL_ENABLED=False)
    monkeypatch.setattr(
        "services.telegram.config.get_telegram_config", lambda: off_config
    )

    notifier = _ready_notifier()
    with patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)):
        await coord._poll_tracked_fills()
        await coord._drain_notify_tasks()

    notifier.send_trade_executed.assert_not_awaited()
