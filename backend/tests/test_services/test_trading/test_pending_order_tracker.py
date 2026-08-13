"""PendingOrderTracker 단위 테스트 — 차분 멱등성이 핵심."""
from datetime import date, timedelta

from services.kiwoom.models import FilledOrder
from services.trading.pending_order_tracker import (
    PendingOrderTracker, TrackedOrder, TrackedOrderStatus,
)


def _fill(ord_no, qty, price, stk_cd="005930"):
    return FilledOrder(ord_no=ord_no, stk_cd=stk_cd, stk_nm="삼성전자",
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


# -------------------------------------------
# F3 review fixes (M1a/M1b/M2)
# -------------------------------------------


def test_apply_fills_requires_matching_ticker():
    """M1a: 브로커 ord_no는 일자 간 재사용될 수 있다 — ord_no가 같아도 종목이
    다르면 절대 매칭하지 않는다(다른 종목 체결이 이 주문의 diff를 오염)."""
    t = PendingOrderTracker()
    t.register(_order())  # ticker 005930
    deltas = t.apply_fills([_fill("0101535", 48, 260000, stk_cd="000660")])
    assert deltas == []
    assert len(t.tracking()) == 1
    assert t.tracking()[0].filled_quantity == 0


def test_apply_fills_sums_only_matching_ticker_rows():
    """M1a guard: 같은 ord_no 아래 섞인 다른 종목 행은 합산에서 제외."""
    t = PendingOrderTracker()
    t.register(_order())
    deltas = t.apply_fills([
        _fill("0101535", 20, 260000, stk_cd="005930"),
        _fill("0101535", 99, 1_000_000, stk_cd="000660"),  # 오염 행
    ])
    assert len(deltas) == 1
    assert deltas[0].new_fill_qty == 20
    assert deltas[0].avg_fill_price == 260000


def test_register_replaces_terminal_entry():
    """M1b: TERMINAL(FILLED/EXPIRED/CANCELLED) 엔트리는 새 주문 등록을 조용히
    삼키지 않는다 — 같은 ord_no의 신규 주문으로 교체된다."""
    t = PendingOrderTracker()
    t.register(_order(total=48))
    t.apply_fills([_fill("0101535", 48, 260000)])  # → FILLED (terminal)
    assert t.tracking() == []

    t.register(_order(total=30))  # 재사용된 ord_no의 신규 주문
    tracking = t.tracking()
    assert len(tracking) == 1
    assert tracking[0].total_quantity == 30
    assert tracking[0].filled_quantity == 0


def test_register_still_ignores_duplicate_while_tracking():
    """M1b guard: TRACKING 중 재등록은 여전히 무시(첫 등록 승리) —
    filled_quantity/filled_amount 리셋으로 diff가 깨지면 안 된다."""
    t = PendingOrderTracker()
    t.register(_order(total=48))
    t.apply_fills([_fill("0101535", 20, 260000)])
    t.register(_order(total=48))  # 같은 ord_no, TRACKING 중
    assert t.tracking()[0].filled_quantity == 20


def test_to_payload_prunes_old_terminal_orders():
    """M2: blob 무한 성장 방지 — TRACKING은 항상 유지, TERMINAL은 당일
    trade_date만 유지(당일 FILLED는 리컨실러 스탑 유래 소스)."""
    today = date.today().strftime("%Y%m%d")
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")

    t = PendingOrderTracker()
    t.register(_order(ord_no="T1", trade_date=yesterday))  # TRACKING (날짜 무관 유지)
    t.register(_order(ord_no="F_TODAY", trade_date=today))
    t.apply_fills([_fill("F_TODAY", 48, 260000)])  # 당일 FILLED — 유지
    t.register(_order(ord_no="F_OLD", trade_date=yesterday))
    t.apply_fills([_fill("F_OLD", 48, 260000)])  # 전일 FILLED — 프루닝
    assert t._orders["F_TODAY"].status == TrackedOrderStatus.FILLED
    assert t._orders["F_OLD"].status == TrackedOrderStatus.FILLED

    payload_ords = {item["ord_no"] for item in t.to_payload()}
    assert payload_ords == {"T1", "F_TODAY"}
