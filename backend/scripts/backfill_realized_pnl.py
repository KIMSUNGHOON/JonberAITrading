"""과거 실현손익(ka10074) 백필 스크립트 (3대 잔여 이슈 E1-6, 선택·마지막).

배경: 과거 매도 114주는 ka10076(체결내역요청)이 당일 조회로만 제한되어
소급 불가하다 -- 정확한 체결 시각·단가를 알 수 없으므로 개별 매매를
entry/exit로 매칭하는 "원장 행"(kr_realized_pnl의 정상 매매 경로가 쓰는
형태)은 만들지 않는다. 대신 **실현손익 금액만**을 ka10074(일자별
실현손익요청, `get_realized_pnl` -- 기간 조회 지원, Phase B1 `2a3eaca`
전례)로 조회해 kr_realized_pnl에 백필한다.

⚠️ dry-run이 기본이다. `--apply`를 명시적으로 넘겨야만 실제 upsert가
실행된다. 이 스크립트는 작성/테스트 시점(E1-6 태스크)에 실 DB
(backend/data/storage.db)에도, 실 Kiwoom 서버에도 단 한 번도 실행되지
않았다 -- dry-run조차 실 DB/실 서버 대상으로 실행하지 않았다(테스트는 전부
tmp DB + mock kiwoom). 실행은 사용자의 명시적 승인을 받은 뒤 별도로 이뤄진다.

ka10074의 데이터 한계와 백필 행 설계
--------------------------------------
ka10074(일자별실현손익요청)는 계좌 전체의 **일자별 합계**만 제공하고
종목별(stk_cd) 세분화가 없다(Kiwoom-REST-API/kiwoom_docs/계좌.md
"일자별실현손익요청(ka10074)" 참고). 종목별 세분은 별도 TR인
ka10073(일자별종목별실현손익요청_기간)이 제공하지만, 입력에 stk_cd가
필수라 "기간 한 번에 전부 조회"가 목적인 이 백필과는 맞지 않고,
`get_realized_pnl`을 도입한 Phase B1 커밋(`2a3eaca`)이 이미 "ka10074가
기간을 지원해 ka10073은 불필요 -- YAGNI"라고 명시했다. 이 스크립트도 같은
전례를 따라 ka10074만 쓴다.

kr_realized_pnl.stk_cd는 NOT NULL이라 종목코드가 없는 이 데이터를 그대로
넣을 수 없다 -- 계좌 전체 집계를 나타내는 센티널 값
`BACKFILL_STK_CD_SENTINEL = "ALL"`을 쓴다(Kiwoom 실 종목코드는 항상 6자리
숫자라 절대 충돌하지 않는다). 스키마에 컬럼을 추가하지 않고(계약 4번
항목) 기존 컬럼만으로 백필 행을 정상 매매 행과 구분한다:

  - stk_cd = "ALL" (정상 매매 경로 `coordinator._apply_sell_fill` ->
    `record_kr_realized_pnl`은 항상 실제 6자리 종목코드를 쓴다)
  - entry_price / exit_price / quantity = NULL (정상 매매 경로는 항상 이
    값들을 채운다 -- ka10074에는 매매 단가/수량 정보 자체가 없다)
  - entry_decision_id / exit_decision_id = NULL (정상 매매 행이 이 값이
    NULL이 되는 경우가 있더라도, 위 stk_cd + price/quantity 조합과
    합쳐지면 백필 행은 유일하게 식별된다)
  - exit_at = "YYYY-MM-DD" (시각은 알 수 없음 -- 날짜만; 정상 매매 행의
    exit_at은 항상 "YYYY-MM-DD HH:MM:SS" 전체 타임스탬프)
  - realized_amount = 해당 일자의 sell_pnl(이미 net -- 근거는
    services/trading/paper_performance.py::build_performance_report의
    독스트링 참조, 수수료/세금 이중차감 방지와 동일 원리)
  - id = 결정론적 f"backfill-{YYYYMMDD}" + INSERT OR IGNORE. 재실행 안전의
    이중 방어: 1차는 아래 "이미 존재하는 (date, stk_cd) 조합 스킵" 로직,
    2차는 PK 충돌 시 무시(IGNORE) -- 둘 중 하나만 있어도 멱등하지만 둘 다
    있어 더 견고하다.

사용법 (backend/ 에서):
    # dry-run (기본, 아무것도 쓰지 않음) -- 대상 카운트/상세만 출력
    python scripts/backfill_realized_pnl.py --from 2026-06-01 --to 2026-07-01

    # 실제 upsert
    python scripts/backfill_realized_pnl.py --from 2026-06-01 --to 2026-07-01 --apply

    # 커스텀 DB 경로 (테스트/검증용)
    python scripts/backfill_realized_pnl.py --from ... --to ... --db-path /path/to/storage.db
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Set

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.kiwoom.models import DailyRealizedPnlRow  # noqa: E402

# -------------------------------------------
# Constants
# -------------------------------------------

# NOT NULL 종목코드 컬럼에 넣는 "계좌 전체 집계" 센티널. 실 종목코드는 항상
# 6자리 숫자라 절대 충돌하지 않는다 (모듈 독스트링 참조).
BACKFILL_STK_CD_SENTINEL = "ALL"
BACKFILL_ID_PREFIX = "backfill-"

# busy_timeout (ms) -- cleanup_session_stores.py와 동일한 방어적 관례.
BUSY_TIMEOUT_MS = 5000

_BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = _BACKEND_DIR / "data" / "storage.db"

# storage_service.py의 kr_realized_pnl CREATE TABLE과 동일해야 한다 --
# 어긋나면 이 스크립트의 INSERT가 실 DB에서 깨질 수 있다.
_KR_REALIZED_PNL_SCHEMA = """
    CREATE TABLE IF NOT EXISTS kr_realized_pnl (
        id TEXT PRIMARY KEY,
        stk_cd TEXT NOT NULL,
        entry_price REAL,
        exit_price REAL,
        quantity INTEGER,
        realized_amount REAL,
        entry_decision_id TEXT,
        exit_decision_id TEXT,
        holding_period_seconds INTEGER,
        entry_at TIMESTAMP,
        exit_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return conn


def _yyyymmdd_to_iso(dt: str) -> str:
    """'YYYYMMDD' -> 'YYYY-MM-DD'. 8자리 숫자가 아니면 원본을 그대로
    돌려준다(호출자가 방어적으로 처리 -- 크래시하지 않음)."""
    if isinstance(dt, str) and len(dt) == 8 and dt.isdigit():
        return f"{dt[0:4]}-{dt[4:6]}-{dt[6:8]}"
    return dt


def _iso_to_yyyymmdd(value: str) -> str:
    """'YYYY-MM-DD' -> 'YYYYMMDD' (Kiwoom API 입력 형식)."""
    return value.replace("-", "")


def _backfill_id(dt: str) -> str:
    return f"{BACKFILL_ID_PREFIX}{dt}"


# -------------------------------------------
# Report / plan dataclasses
# -------------------------------------------


@dataclass
class BackfillRow:
    id: str
    stk_cd: str
    realized_amount: float
    exit_at: str  # 'YYYY-MM-DD'
    source_dt: str  # 원본 'YYYYMMDD' (표시용)


@dataclass
class BackfillPlan:
    candidate_rows: List[BackfillRow] = field(default_factory=list)
    skipped_existing: List[str] = field(default_factory=list)  # 원본 'YYYYMMDD'
    skipped_unparseable: List[str] = field(default_factory=list)
    fetch_failed: bool = False
    fetch_error: Optional[str] = None
    inserted: int = 0


# -------------------------------------------
# 1) 기존 백필 행 조회 (읽기 전용 -- dry-run에서도 안전, 쓰기 없음)
# -------------------------------------------


def read_existing_backfill_dates(
    db_path: str, stk_cd: str = BACKFILL_STK_CD_SENTINEL
) -> Set[str]:
    """DB 안에 이미 존재하는 백필 행의 날짜(exit_at, 'YYYY-MM-DD') 집합.

    파일이 없거나 테이블이 아직 없으면 빈 집합을 돌려준다(never raises --
    최초 실행 시나리오는 정상 케이스다). 읽기 전용 -- 테이블을 생성하지
    않는다(dry-run이 DB에 어떤 부작용도 남기지 않아야 하므로, CREATE TABLE
    조차 여기서는 하지 않는다 -- 그건 upsert_backfill_rows의 몫).
    """
    if not os.path.exists(db_path):
        return set()

    conn = _connect(db_path)
    try:
        try:
            cur = conn.execute(
                "SELECT exit_at FROM kr_realized_pnl WHERE stk_cd = ?", (stk_cd,)
            )
            return {row[0] for row in cur.fetchall() if row[0]}
        except sqlite3.OperationalError:
            return set()  # 테이블 없음 -- 아직 아무것도 백필된 적 없음
    finally:
        conn.close()


# -------------------------------------------
# 2) 순수 함수: ka10074 일자별 실현손익 -> upsert 후보
# -------------------------------------------


def compute_backfill_plan(
    daily: Sequence[DailyRealizedPnlRow],
    existing_dates: Set[str],
) -> BackfillPlan:
    """ka10074 일자별 실현손익 행들 중 이미 백필된(stk_cd=ALL로 존재하는)
    날짜를 제외한 upsert 후보를 계산한다. 순수 함수 -- DB/네트워크 접근
    없음.

    dt가 'YYYYMMDD' 8자리 숫자로 파싱 불가능한 행은 건너뛴다(방어적 --
    브로커 응답이 스펙과 다르더라도 크래시하지 않는다).
    """
    plan = BackfillPlan()
    for d in daily:
        if not (isinstance(d.dt, str) and len(d.dt) == 8 and d.dt.isdigit()):
            plan.skipped_unparseable.append(str(d.dt))
            continue

        exit_at = _yyyymmdd_to_iso(d.dt)
        if exit_at in existing_dates:
            plan.skipped_existing.append(d.dt)
            continue

        plan.candidate_rows.append(
            BackfillRow(
                id=_backfill_id(d.dt),
                stk_cd=BACKFILL_STK_CD_SENTINEL,
                realized_amount=float(d.sell_pnl),
                exit_at=exit_at,
                source_dt=d.dt,
            )
        )
    return plan


# -------------------------------------------
# 3) upsert (--apply 시에만 호출)
# -------------------------------------------


def upsert_backfill_rows(db_path: str, rows: Sequence[BackfillRow]) -> int:
    """후보 행들을 kr_realized_pnl에 INSERT OR IGNORE.

    결정론적 id(f"backfill-{YYYYMMDD}") 덕분에 동일한 날짜를 다시 넣으려
    해도 PK 충돌로 조용히 무시된다 -- compute_backfill_plan의 사전 스킵과
    합쳐 재실행 안전의 이중 방어. 테이블이 없으면 여기서 생성한다(쓰기
    경로에서만 -- dry-run에서는 절대 호출되지 않는다).

    Returns:
        실제로 삽입된 행 수(이미 존재해 IGNORE된 행은 제외).
    """
    if not rows:
        return 0

    conn = _connect(db_path)
    inserted = 0
    try:
        conn.execute(_KR_REALIZED_PNL_SCHEMA)
        for r in rows:
            try:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO kr_realized_pnl
                    (id, stk_cd, entry_price, exit_price, quantity,
                     realized_amount, entry_decision_id, exit_decision_id,
                     holding_period_seconds, entry_at, exit_at)
                    VALUES (?, ?, NULL, NULL, NULL, ?, NULL, NULL, NULL, NULL, ?)
                    """,
                    (r.id, r.stk_cd, r.realized_amount, r.exit_at),
                )
                if cur.rowcount:
                    inserted += 1
            except sqlite3.Error as e:
                print(f"  [WARN] {r.exit_at} 삽입 실패: {e}")
        conn.commit()
    finally:
        conn.close()

    return inserted


# -------------------------------------------
# Orchestration (async -- ka10074 조회가 async이므로)
# -------------------------------------------


async def run_backfill(
    kiwoom_client,
    db_path: str,
    from_date: str,
    to_date: str,
    apply: bool = False,
) -> BackfillPlan:
    """1회 ka10074 기간 조회(from_date~to_date, 'YYYY-MM-DD') 후 dry-run
    보고, 또는 --apply 시 upsert까지 실행하고 콘솔에 리포트를 출력한다.

    조회 실패(네트워크/브로커 오류 등)는 절대 크래시하지 않는다 -- 경고를
    출력하고 이 기간 전체를 건너뛴 빈 플랜(fetch_failed=True)을 돌려준다
    ("조회 실패=해당 날짜(기간) skip"). ka10074는 기간을 한 번에 조회하는
    단일 호출(Phase B1 전례)이므로, 개별 날짜 단위 재시도는 하지 않는다 --
    실패하면 이 스크립트 실행 전체를 다시 돌리는 것이 올바른 재시도
    방법이다.
    """
    strt_dt = _iso_to_yyyymmdd(from_date)
    end_dt = _iso_to_yyyymmdd(to_date)

    print("=" * 70)
    print("실현손익 과거 백필 스크립트" + (" -- APPLY 모드" if apply else " -- DRY RUN"))
    print("=" * 70)
    print(f"기간: {from_date} ~ {to_date} (ka10074 strt_dt={strt_dt} end_dt={end_dt})")
    print(f"DB: {db_path}")
    print()

    try:
        pnl = await kiwoom_client.get_realized_pnl(strt_dt=strt_dt, end_dt=end_dt)
    except Exception as e:  # never crash -- see docstring
        print(f"[WARN] ka10074 조회 실패 -- 이 기간을 건너뜁니다: {e}")
        return BackfillPlan(fetch_failed=True, fetch_error=str(e))

    existing_dates = read_existing_backfill_dates(db_path)
    plan = compute_backfill_plan(pnl.daily, existing_dates)

    print(
        f"조회된 일자 수: {len(pnl.daily)}  기존 백필 보유 일자: {len(existing_dates)}"
    )
    print(
        f"신규 백필 후보: {len(plan.candidate_rows)}  "
        f"이미 존재(skip): {len(plan.skipped_existing)}  "
        f"파싱 불가(skip): {len(plan.skipped_unparseable)}"
    )
    for r in plan.candidate_rows:
        print(f"  [candidate] {r.exit_at}  realized_amount={r.realized_amount:+,.0f}")
    for dt in plan.skipped_existing:
        print(f"  [skip-existing] {_yyyymmdd_to_iso(dt)}")
    for dt in plan.skipped_unparseable:
        print(f"  [skip-unparseable] {dt!r}")

    if apply and plan.candidate_rows:
        plan.inserted = upsert_backfill_rows(db_path, plan.candidate_rows)
        print(f"  -> {plan.inserted}행 삽입됨")

    print()
    if not apply:
        print(
            "dry-run입니다 -- 아무것도 기록되지 않았습니다. "
            "--apply를 추가하면 실제 upsert를 실행합니다."
        )
    else:
        print("백필 완료.")

    return plan


# -------------------------------------------
# CLI
# -------------------------------------------


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="과거 실현손익(ka10074) 백필 스크립트 (dry-run 기본)"
    )
    parser.add_argument(
        "--from", dest="from_date", required=True, help="시작일 YYYY-MM-DD"
    )
    parser.add_argument(
        "--to", dest="to_date", required=True, help="종료일 YYYY-MM-DD"
    )
    parser.add_argument(
        "--apply", action="store_true", help="실제로 upsert 실행 (기본은 dry-run)"
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="kr_realized_pnl이 있는 storage.db 경로",
    )
    return parser.parse_args(argv)


async def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)

    from app.config import settings
    from services.kiwoom import KiwoomClient

    app_key = settings.KIWOOM_APP_KEY or ""
    secret = settings.KIWOOM_SECRET_KEY or ""
    if not (app_key and secret):
        print("FAIL: .env에 KIWOOM_APP_KEY/KIWOOM_SECRET_KEY가 없습니다")
        return 1

    client = KiwoomClient(
        app_key=app_key,
        secret_key=secret,
        is_mock=getattr(settings, "KIWOOM_IS_MOCK", True),
    )
    try:
        await run_backfill(
            kiwoom_client=client,
            db_path=args.db_path,
            from_date=args.from_date,
            to_date=args.to_date,
            apply=args.apply,
        )
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
