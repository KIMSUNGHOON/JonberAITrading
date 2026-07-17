"""EOD 원장 대사 백스톱 (E1-5).

E1-1~E1-4로 전 SELL 경로가 발주시 기록(`_apply_sell_fill`)+잔량 추적
(`pending_order_tracker`)+폴 델타 후처리(`_poll_tracked_fills`)를 갖췄지만,
이 셋은 모두 **추적 중인 주문**에만 작동한다. 프로세스가 주문 접수와 기록
사이에 죽었거나, 추적 등록 자체가 되지 않은 주문(예: 이 체계 이전 방식으로
낸 주문)은 어느 경로에도 잡히지 않고 원장(`kr_stock_trades`)에서 영구히
누락된다.

`reconcile_trade_ledger`는 그 틈을 메우는 마감 전수 대조다: 브로커의 당일
체결 스냅샷(ka10076 `get_filled_orders`)을 주문번호(`ord_no`)별로 누적
집계해, 원장의 같은 날 `order_id`별 누적 `executed_quantity`/`total_krw`와
diff한다. 부족분(브로커 누적 > 원장 누적)만 그 차액을 새 행으로 append한다
— 원장에 order_id가 아예 없는 주문도 이 diff에서 자연히 "전량 부족"으로
잡혀 신규 append된다.

**경계 (중요)**: 이 함수는 원장·실현손익 기록 전용이다. 로컬 포지션
수량(`ExecutionCoordinator._state.positions`)은 건드리지 않는다 — 포지션
정합은 기존 kt00004 기반 reconciler(`services/trading/reconciler.py`)의
소관이다. 시그니처가 `coordinator`가 아니라 `kiwoom`/`storage`만 받는 것도
이 경계를 강제한다: 포지션에 손댈 방법 자체가 없다.

**실현손익(sell) 처리**: 이 함수는 코디네이터의 `_state.positions`에 접근할
수 없으므로(시그니처에 coordinator가 없음) 진입가의 유일한 후보 소스는
원장 자신뿐이다 — 같은 종목의 가장 최근 `entry_or_exit="entry"` 행의
가격을 최선 추정 진입가로 사용해 `record_kr_realized_pnl`을 함께 기록한다.
그런 entry 행을 원장에서 전혀 찾을 수 없으면(포지션이 이 원장이 생기기
전에 열렸거나 이미 완전히 정리된 경우) 실현손익 기록은 건너뛴다 — E1-2가
`_apply_sell_position_delta`에서 확립한 "진입가 소스 없음 → 실현손익
스킵, 원장 기록은 계속" 컨벤션과 동일하다.

Never-raise by design (마감 스케줄러 틱을 절대 깨서는 안 됨, 다른 모든 EOD
스텝과 동일한 계약 — eod_snapshot/eod_orchestrator/strategy_orchestrator
참조): 브로커 조회 실패, 저장소 조회 실패, 개별 행 쓰기 실패 모두 로그만
남기고 진행하거나 빈 결과로 반환한다.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .trade_log import record_kr_realized_pnl_async, record_trade_fill_async

logger = logging.getLogger(__name__)

# get_kr_stock_trades에는 날짜 필터가 없어(P1-1 스키마 당시 트랜잭션 단건
# 조회 용도로만 설계됨) 넉넉한 최근 구간을 끌어와 파이썬에서 trade_date
# 접두사로 거른다 — eod_snapshot._count_win_loss_trades와 동일한 패턴.
# 마감 1회 배치 호출이라 핫패스 비용이 아니다.
_LEDGER_SCAN_LIMIT = 2000

# 진입가 최선 추정 조회 시 종목당 훑는 최근 행 수. 최근 것부터 오는
# get_kr_stock_trades 정렬을 그대로 신뢰해 첫 entry 행을 쓴다.
_ENTRY_LOOKUP_LIMIT = 50


def _derive_side(buy_sell_tp: str) -> tuple[str, str]:
    """ka10076 buy_sell_tp(소비자 계약: "1"=매수/"2"=매도)에서
    (side, entry_or_exit)를 파생한다. 알 수 없는 값은 sell/exit로 안전
    쪽으로 취급한다(매수를 놓치는 것보다 매도를 잘못 entry로 기록하지
    않는 편이 실현손익 오염 위험이 적다)."""
    if buy_sell_tp == "1":
        return "buy", "entry"
    return "sell", "exit"


async def _lookup_entry_price(storage: Any, stk_cd: str) -> Optional[float]:
    """종목의 가장 최근 entry(매수) 원장 행 가격을 최선 추정 진입가로
    반환. 없으면 None(호출자는 실현손익 기록을 스킵해야 한다)."""
    try:
        rows = await storage.get_kr_stock_trades(stk_cd=stk_cd, limit=_ENTRY_LOOKUP_LIMIT)
    except Exception as e:
        logger.warning(f"[LedgerReconcile] entry price lookup failed for {stk_cd}: {e}")
        return None

    for row in rows:
        if row.get("entry_or_exit") == "entry":
            price = row.get("price")
            if price is not None:
                return float(price)
    return None


async def reconcile_trade_ledger(kiwoom: Any, storage: Any, trade_date: str) -> dict:
    """ka10076 당일 체결 전수 vs 원장(kr_stock_trades) diff → 부족분 upsert.

    Args:
        kiwoom: `get_filled_orders(use_cache=False)`를 제공하는 브로커
            클라이언트(KiwoomClient 또는 테스트 더블).
        storage: StorageService — `get_kr_stock_trades` 조회.
        trade_date: "YYYY-MM-DD" (마감 엣지의 다른 스텝들과 동일한 포맷 —
            `write_daily_snapshot`/`run_eod_review`/`run_strategy_consensus`
            호출부의 `datetime.now().strftime("%Y-%m-%d")` 참조).

    Returns:
        `{"checked": N, "missing_orders": n, "upserted_qty": q}`.
        - checked: 이번 대조에서 살펴본 브로커 주문(ord_no) 수.
        - missing_orders: 원장 누적이 브로커 누적에 못 미쳐 새 행을 append한
          주문 수(부분 부족 + 완전 누락 모두 포함).
        - upserted_qty: append된 수량 합계.
        브로커 조회가 실패하면 전부 0인 결과를 반환한다(never-raise).
        원장이 이미 브로커 누적과 일치하면(정상 경로가 전부 잡았으면)
        missing_orders/upserted_qty는 0 — 즉 idempotent: 같은 스냅샷에 대해
        재실행해도 두 번째 실행은 diff=0이다(첫 실행이 쓴 행이 원장 누적에
        반영되므로).
    """
    result: dict[str, int] = {"checked": 0, "missing_orders": 0, "upserted_qty": 0}

    try:
        try:
            fills = await kiwoom.get_filled_orders(use_cache=False)
        except Exception as e:
            logger.warning(f"[LedgerReconcile] broker fill snapshot failed: {e}")
            return result

        # 브로커 스냅샷을 ord_no별로 누적 집계 (수량/금액/종목/방향).
        broker: dict[str, dict[str, Any]] = {}
        for fo in fills:
            ord_no = getattr(fo, "ord_no", None)
            if not ord_no:
                continue
            agg = broker.setdefault(
                ord_no,
                {
                    "qty": 0,
                    "amount": 0.0,
                    "stk_cd": fo.stk_cd,
                    "stk_nm": fo.stk_nm,
                    "buy_sell_tp": fo.buy_sell_tp,
                },
            )
            agg["qty"] += fo.ccld_qty
            agg["amount"] += fo.ccld_qty * fo.ccld_uv

        result["checked"] = len(broker)
        if not broker:
            return result

        try:
            ledger_rows = await storage.get_kr_stock_trades(limit=_LEDGER_SCAN_LIMIT)
        except Exception as e:
            logger.warning(f"[LedgerReconcile] ledger read failed: {e}")
            return result

        # 원장의 당일 행만, order_id가 있는 것만 order_id별로 누적 집계
        # (브리프 명세: SELECT order_id, SUM(executed_quantity) ... GROUP BY
        # order_id, WHERE는 trade_date — created_at은 KST datetime.now()로
        # 삽입되므로 문자열 접두사 매칭으로 필터한다, eod_snapshot과 동일
        # 컨벤션).
        ledger: dict[str, dict[str, float]] = {}
        for row in ledger_rows:
            order_id = row.get("order_id")
            if not order_id:
                continue
            created_at = str(row.get("created_at") or "")
            if not created_at.startswith(trade_date):
                continue
            entry = ledger.setdefault(order_id, {"qty": 0, "amount": 0.0})
            entry["qty"] += row.get("executed_quantity") or 0
            entry["amount"] += row.get("total_krw") or 0

        for ord_no, b in broker.items():
            ledger_entry = ledger.get(ord_no, {"qty": 0, "amount": 0.0})
            missing_qty = b["qty"] - ledger_entry["qty"]
            if missing_qty <= 0:
                # 원장이 이미 브로커 누적을 따라잡았다(정상 경로가 잡았거나,
                # 이전 대조 실행이 이미 채웠다) — idempotent no-op.
                continue

            missing_amount = b["amount"] - ledger_entry["amount"]
            avg_price = missing_amount / missing_qty if missing_qty else 0.0

            side, entry_or_exit = _derive_side(b["buy_sell_tp"])

            try:
                await record_trade_fill_async(
                    stk_cd=b["stk_cd"],
                    stk_nm=b["stk_nm"],
                    side=side,
                    order_type="limit",
                    price=avg_price,
                    quantity=missing_qty,
                    executed_quantity=missing_qty,
                    status="completed",
                    order_id=ord_no,
                    entry_or_exit=entry_or_exit,
                )
            except Exception as e:
                logger.warning(
                    f"[LedgerReconcile] ledger append failed for ord_no={ord_no}: {e}"
                )
                continue

            result["missing_orders"] += 1
            result["upserted_qty"] += missing_qty

            if side == "sell":
                entry_price = await _lookup_entry_price(storage, b["stk_cd"])
                if entry_price is not None:
                    try:
                        await record_kr_realized_pnl_async(
                            stk_cd=b["stk_cd"],
                            entry_price=entry_price,
                            exit_price=avg_price,
                            quantity=missing_qty,
                            realized_amount=(avg_price - entry_price) * missing_qty,
                        )
                    except Exception as e:
                        logger.warning(
                            f"[LedgerReconcile] realized P&L append failed for "
                            f"ord_no={ord_no}: {e}"
                        )
                else:
                    logger.info(
                        f"[LedgerReconcile] no entry-price source for "
                        f"{b['stk_cd']} (ord_no={ord_no}) — ledger row appended, "
                        "realized P&L skipped"
                    )

        return result
    except Exception as e:
        logger.warning(f"[LedgerReconcile] reconcile_trade_ledger failed: {e}")
        return result
