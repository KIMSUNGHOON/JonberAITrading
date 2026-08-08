"""순 실현손익(net) 일회성 백필 스크립트 (2026-08-08).

배경
----
`kr_realized_pnl.realized_amount`는 (exit_price - entry_price) * qty 순수
**gross**였다 — 수수료도 증권거래세도 빠져 있다. 그 gross가 그대로
`agent_chat_decisions.outcome_realized_pnl`로 백필되고, 거기서
`services/trading/calibration.py`의 에이전트 정오답 채점 → 전략 재가중으로
흘러갔다. **비용을 못 넘긴 거래가 "승리"로 학습됐다.**

기록 경로(`trade_log.record_kr_realized_pnl_async`)는 같은 커밋에서
봉합됐지만 그건 배포 이후 행에만 적용된다. 이미 쌓인 행들은 이 스크립트가
같은 모델로 한 번 채운다.

실측(2026-08-08 라이브 DB, 매칭 거래 25행): 1건이 부호를 뒤집는다.

    005930 삼성전자 2026-07-22  entry 273,027  exit 273,420  qty 56
      gross  +22,008
      비용    41,336  (매수수수료 3,058 + 매도수수료 3,062 + 거래세 35,216)
      net    -19,328   ← 승리로 집계되던 것이 실제로는 손실

비용 기준
--------
앱 자체 모델(`services/trading/cost_model.compute_fill_cost` — 편도 수수료
2bp + 매도 증권거래세 23bp = 왕복 0.27%)을 쓴다. 모의 브로커는 실제로 왕복
0.90%(수수료 편도 35bp)를 물리지만 그건 **모의 서버 고유 요율**이고 실전
키움(왕복 ~0.19~0.23%)의 4.7배다. 캘리브레이션이 학습해야 하는 것은
실전에서 일반화되는 문턱이므로 모의의 가혹한 요율이 아니라 실전에 가까운
모델을 쓴다. `cost_source` 컬럼이 어느 쪽으로 계산됐는지 남기므로
(`model` = 정상 기록 경로, `model_backfill` = 이 스크립트), 나중에 브로커가
체결 단위 수수료를 주면 그 값으로 갈아탈 수 있다.

`realized_amount`(gross)는 **절대 건드리지 않는다** — 두 단위가 나란히
남아야 한다.

왜 initialize()가 아니라 스크립트인가
------------------------------------
이 리포에서 스키마 변경(DDL)은 `storage_service.initialize()`의
`_ensure_columns`가, 값 변경(DML)은 `backend/scripts/backfill_*.py`가
맡는다 — 선례 2건(`backfill_realized_pnl.py`, `backfill_trades_20260713.py`)
이 전부 스크립트이고 `_ensure_columns`는 그 독스트링에서 "ADD COLUMN은
기존 행을 상수로만 채울 수 있다"고 한계를 명시하면서도 뒤따르는 UPDATE를
붙이지 않았다. 게다가 이 백필은 학습 원장(`agent_chat_decisions`)까지
쓴다 — 프로세스가 뜰 때마다 저수준 스토리지 생성자에서 조용히 실행될
성질의 작업이 아니다.

멱등성 (2중 방어)
----------------
1. 후보 선정이 `net_amount IS NULL`인 행만 잡는다 — 두 번째 실행은 후보 0.
2. 결정 백필은 **이번 실행에서 실제로 채운 행**의 결정만 대상으로 한다 —
   후보가 0이면 결정 백필도 0이라, 그 사이 런타임이 갱신한 결정 값을
   재실행이 되돌리는 일이 없다.

부분체결 슬라이스 처리
--------------------
한 `entry_decision_id`에 여러 행이 달리는 것이 라이브의 정상 형태다
(049070은 6행). 런타임의 `update_decision_outcome`은 덮어쓰기라 **마지막
체결이 이긴다**. 백필도 같은 규칙(exit_at → created_at → id 순 최댓값)을
써서, gross를 net으로 바꾸는 것 이상의 의미 변화가 생기지 않게 한다.

사용법 (backend/ 에서):
    # dry-run (기본, 아무것도 쓰지 않음 — ALTER조차 하지 않는다)
    python scripts/backfill_net_realized_pnl.py

    # 실제 적용
    python scripts/backfill_net_realized_pnl.py --apply

    # 커스텀 DB 경로 (테스트/검증용)
    python scripts/backfill_net_realized_pnl.py --db-path /path/to/storage.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.trading.cost_model import compute_fill_cost  # noqa: E402
from services.trading.eod_snapshot import (  # noqa: E402
    _BACKFILL_STK_CD_SENTINEL as SENTINEL_STK_CD,
)

# -------------------------------------------
# Constants
# -------------------------------------------

# storage_service.py의 kr_realized_pnl.cost_source가 구분하는 두 값 중
# 이 스크립트 쪽(정상 기록 경로는 'model').
COST_SOURCE_BACKFILL = "model_backfill"

# busy_timeout (ms) -- backfill_realized_pnl.py와 동일한 방어적 관례.
BUSY_TIMEOUT_MS = 5000

_BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = _BACKEND_DIR / "data" / "storage.db"

# storage_service.py의 _ensure_columns("kr_realized_pnl", ...)와 동일해야
# 한다 -- 라이브 DB는 앱이 재기동하기 전까지 이 컬럼들이 없을 수 있고,
# 그때도 이 스크립트만으로 백필이 완결돼야 한다.
_COST_COLUMNS: dict[str, str] = {
    "fee": "INTEGER DEFAULT 0",
    "tax": "INTEGER DEFAULT 0",
    "net_amount": "REAL",
    "cost_source": "TEXT",
}


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return conn


# -------------------------------------------
# Plan dataclasses
# -------------------------------------------


@dataclass
class CostBackfillRow:
    id: str
    stk_cd: str
    entry_decision_id: Optional[str]
    gross: float
    fee: int
    tax: int
    net_amount: float


@dataclass
class CostBackfillPlan:
    rows: list[CostBackfillRow] = field(default_factory=list)
    # (decision_id, net_amount) -- 이번 실행에서 채운 행이 속한 결정만.
    decision_updates: list[tuple[str, float]] = field(default_factory=list)
    skipped_sentinel: int = 0
    already_net: int = 0
    skipped_no_amount: int = 0
    updated_rows: int = 0
    updated_decisions: int = 0


# -------------------------------------------
# 1) 읽기 (읽기 전용 -- dry-run에서도 스키마를 건드리지 않는다)
# -------------------------------------------


def read_all_rows(db_path: str) -> list[dict[str, Any]]:
    """kr_realized_pnl 전 행을 dict로 읽는다.

    비용 컬럼(fee/tax/net_amount/cost_source)이 아직 없는 DB(=앱 재기동
    전의 라이브)에서도 동작해야 하므로 `SELECT *` 후 없는 키는 None으로
    정규화한다. 절대 쓰지 않는다 -- ALTER도 CREATE도 하지 않는다(그건
    apply 경로의 몫).
    """
    if not os.path.exists(db_path):
        return []

    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        try:
            cur = conn.execute("SELECT * FROM kr_realized_pnl")
        except sqlite3.OperationalError:
            return []  # 테이블 없음
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    for row in rows:
        for col in _COST_COLUMNS:
            row.setdefault(col, None)
    return rows


# -------------------------------------------
# 2) 순수 함수: 행 -> 백필 계획 (DB 접근 없음)
# -------------------------------------------


def _sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    """런타임의 "마지막 체결이 이긴다"를 재현하는 정렬 키."""
    return (
        str(row.get("exit_at") or ""),
        str(row.get("created_at") or ""),
        str(row.get("id") or ""),
    )


def compute_cost_backfill_plan(
    rows: Sequence[dict[str, Any]],
) -> CostBackfillPlan:
    """`net_amount`가 비어 있는 매칭 거래 행들의 fee/tax/net을 계산한다.

    순수 함수 -- DB/네트워크 접근 없음.

    - `stk_cd == 'ALL'`(계좌 전체 백필 집계 행)은 제외한다. 그건 매칭된
      거래가 아니다 -- 단가/수량이 아예 없고, eod_snapshot/eod_review도
      같은 센티널로 걸러낸다.
    - `net_amount`가 이미 있는 행은 건드리지 않는다(멱등성 1차 방어).
    - 결정 백필 값은 그 결정의 **모든** 행(이번에 채운 행 + 이미 net이 있던
      행) 중 가장 늦은 체결의 net이다 -- 런타임 덮어쓰기 순서와 같다.
    """
    plan = CostBackfillPlan()

    tradeable: list[dict[str, Any]] = []
    for row in rows:
        if row.get("stk_cd") == SENTINEL_STK_CD:
            plan.skipped_sentinel += 1
            continue
        tradeable.append(row)

    # net을 알 수 있는(=계산했거나 이미 있는) 값을 행 id별로 모은다.
    net_by_row_id: dict[str, float] = {}
    touched_decisions: set[str] = set()

    for row in tradeable:
        gross = row.get("realized_amount")
        existing_net = row.get("net_amount")

        if existing_net is not None:
            plan.already_net += 1
            net_by_row_id[str(row.get("id"))] = float(existing_net)
            continue

        if gross is None:
            plan.skipped_no_amount += 1
            continue

        entry_fee, _ = compute_fill_cost(
            "buy", row.get("entry_price") or 0.0, row.get("quantity") or 0
        )
        exit_fee, exit_tax = compute_fill_cost(
            "sell", row.get("exit_price") or 0.0, row.get("quantity") or 0
        )
        fee = entry_fee + exit_fee
        net = float(gross) - fee - exit_tax

        plan.rows.append(
            CostBackfillRow(
                id=str(row.get("id")),
                stk_cd=str(row.get("stk_cd")),
                entry_decision_id=row.get("entry_decision_id"),
                gross=float(gross),
                fee=fee,
                tax=exit_tax,
                net_amount=net,
            )
        )
        net_by_row_id[str(row.get("id"))] = net
        if row.get("entry_decision_id"):
            touched_decisions.add(str(row["entry_decision_id"]))

    # 결정별 승자 = 가장 늦은 체결 (런타임 last-write-wins 재현).
    for decision_id in sorted(touched_decisions):
        siblings = [
            r
            for r in tradeable
            if r.get("entry_decision_id") == decision_id
            and str(r.get("id")) in net_by_row_id
        ]
        if not siblings:
            continue
        winner = max(siblings, key=_sort_key)
        plan.decision_updates.append(
            (decision_id, net_by_row_id[str(winner.get("id"))])
        )

    return plan


# -------------------------------------------
# 3) 적용 (--apply 시에만 호출)
# -------------------------------------------


def _ensure_cost_columns(conn: sqlite3.Connection) -> None:
    """비용 컬럼 4개를 없으면 추가한다(storage_service._ensure_columns의
    스크립트 측 거울). 쓰기 경로에서만 호출된다 -- dry-run은 스키마를
    건드리지 않는다."""
    existing = {
        r[1] for r in conn.execute("PRAGMA table_info(kr_realized_pnl)")
    }
    for name, col_type in _COST_COLUMNS.items():
        if name not in existing:
            conn.execute(
                f"ALTER TABLE kr_realized_pnl ADD COLUMN {name} {col_type}"
            )


def apply_cost_backfill(db_path: str, plan: CostBackfillPlan) -> None:
    """계획을 DB에 적용하고 `plan.updated_*` 카운터를 채운다.

    원장 UPDATE는 `net_amount IS NULL`을 WHERE에 다시 걸어(계획 수립 이후
    다른 프로세스가 채웠을 가능성) 이중으로 멱등하다. 결정 UPDATE는
    `plan.decision_updates`에만 의존하는데, 그 목록은 이번 실행에서 실제로
    채운 행이 있는 결정만 담으므로 재실행 시 자동으로 비어 있다.
    """
    if not plan.rows and not plan.decision_updates:
        return

    conn = _connect(db_path)
    try:
        _ensure_cost_columns(conn)

        for r in plan.rows:
            cur = conn.execute(
                """
                UPDATE kr_realized_pnl
                SET fee = ?, tax = ?, net_amount = ?, cost_source = ?
                WHERE id = ? AND net_amount IS NULL
                """,
                (r.fee, r.tax, r.net_amount, COST_SOURCE_BACKFILL, r.id),
            )
            plan.updated_rows += cur.rowcount

        for decision_id, net in plan.decision_updates:
            try:
                cur = conn.execute(
                    "UPDATE agent_chat_decisions SET outcome_realized_pnl = ? "
                    "WHERE id = ?",
                    (net, decision_id),
                )
            except sqlite3.OperationalError as e:
                # agent_chat_decisions가 없는 DB(테스트 픽스처/신규 파일)
                # 에서도 원장 백필은 완결돼야 한다.
                print(f"  [WARN] 결정 백필 스킵 ({decision_id}): {e}")
                break
            plan.updated_decisions += cur.rowcount

        conn.commit()
    finally:
        conn.close()


# -------------------------------------------
# Orchestration
# -------------------------------------------


def run_backfill(db_path: str, apply: bool = False) -> CostBackfillPlan:
    """dry-run 보고, 또는 --apply 시 실제 적용까지 하고 리포트를 출력한다."""
    print("=" * 70)
    print(
        "순 실현손익(net) 백필" + (" -- APPLY 모드" if apply else " -- DRY RUN")
    )
    print("=" * 70)
    print(f"DB: {db_path}")
    print()

    rows = read_all_rows(db_path)
    plan = compute_cost_backfill_plan(rows)

    print(
        f"전체 행: {len(rows)}  후보: {len(plan.rows)}  "
        f"이미 net 있음(skip): {plan.already_net}  "
        f"센티널 'ALL'(skip): {plan.skipped_sentinel}  "
        f"금액 없음(skip): {plan.skipped_no_amount}"
    )
    flipped = [r for r in plan.rows if (r.gross > 0) != (r.net_amount > 0)]
    for r in plan.rows:
        flag = "  <== 부호 반전" if r in flipped else ""
        print(
            f"  [{r.stk_cd}] gross={r.gross:+,.0f} "
            f"fee={r.fee:,} tax={r.tax:,} -> net={r.net_amount:+,.0f}{flag}"
        )
    print(f"부호가 뒤집히는 행: {len(flipped)}")
    print(f"결정 outcome 재백필 대상: {len(plan.decision_updates)}")

    if apply:
        apply_cost_backfill(db_path, plan)
        print(
            f"  -> 원장 {plan.updated_rows}행, "
            f"결정 {plan.updated_decisions}행 갱신됨"
        )
        print("\n백필 완료.")
    else:
        print(
            "\ndry-run입니다 -- 아무것도 기록되지 않았습니다. "
            "--apply를 추가하면 실제로 적용합니다."
        )

    return plan


# -------------------------------------------
# CLI
# -------------------------------------------


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="kr_realized_pnl 순 실현손익 백필 (dry-run 기본)"
    )
    parser.add_argument(
        "--apply", action="store_true", help="실제로 적용 (기본은 dry-run)"
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="kr_realized_pnl이 있는 storage.db 경로",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    run_backfill(db_path=args.db_path, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
