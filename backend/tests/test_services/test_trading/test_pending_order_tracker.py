"""PendingOrderTracker 단위 테스트 — 차분 멱등성이 핵심."""
from services.kiwoom.models import FilledOrder
from services.trading.pending_order_tracker import (
    PendingOrderTracker, TrackedOrder, TrackedOrderStatus,
)


def _fill(ord_no, qty, price):
    return FilledOrder(ord_no=ord_no, stk_cd="005930", stk_nm="삼성전자",
                       ccld_qty=qty, ccld_uv=price, ccld_amt=qty * price,
                       ccld_dt="", ccld_tm="130000", buy_sell_tp="1")


def _order(ord_no="0101535", total=48, **kw):
    base = dict(ord_no=ord_no, ticker="005930", stock_name="삼성전자", side="buy",
                total_quantity=total, limit_price=260000.0, stop_loss=246560.0,
                take_profit=289440.0, trade_date="20260713")
    base.update(kw)
    return TrackedOrder(**base)


def test_full_fill_emits_delta_and_marks_filled():
    t = PendingOrderTracker()
    t.register(_order())
    deltas = t.apply_fills([_fill("0101535", 48, 260000)])
    assert len(deltas) == 1
    assert deltas[0].new_fill_qty == 48 and deltas[0].avg_fill_price == 260000
    assert t.tracking() == []  # FILLED로 전이


def test_partial_then_rest_is_idempotent_diff():
    t = PendingOrderTracker()
    t.register(_order())
    d1 = t.apply_fills([_fill("0101535", 20, 260000)])
    assert d1[0].new_fill_qty == 20
    # ka10076 누적 스냅샷: 같은 20주가 다시 보여도 delta 없음
    assert t.apply_fills([_fill("0101535", 20, 260000)]) == []
    # 누적 48주 스냅샷 → 신규분 28주만
    d2 = t.apply_fills([_fill("0101535", 48, 260000)])
    assert d2[0].new_fill_qty == 28
    assert t.tracking() == []


def test_unrelated_fills_ignored():
    t = PendingOrderTracker()
    t.register(_order())
    assert t.apply_fills([_fill("9999999", 10, 100)]) == []
    assert len(t.tracking()) == 1


def test_expire_stale_by_date_and_all():
    t = PendingOrderTracker()
    t.register(_order(ord_no="A", trade_date="20260710"))
    t.register(_order(ord_no="B", trade_date="20260713"))
    expired = t.expire_stale(today="20260713")
    assert [o.ord_no for o in expired] == ["A"]
    assert [o.ord_no for o in t.tracking()] == ["B"]
    # 장마감: today=None 규약으로 전부 만료
    expired2 = t.expire_stale(today=None)
    assert [o.ord_no for o in expired2] == ["B"] and t.tracking() == []


def test_payload_round_trip():
    t = PendingOrderTracker()
    t.register(_order())
    t.apply_fills([_fill("0101535", 20, 260000)])
    restored = PendingOrderTracker.from_payload(t.to_payload())
    assert restored.tracking()[0].filled_quantity == 20
    assert restored.tracking()[0].stop_loss == 246560.0


def test_duplicate_register_ignored():
    t = PendingOrderTracker()
    t.register(_order()); t.register(_order())
    assert len(t.tracking()) == 1
