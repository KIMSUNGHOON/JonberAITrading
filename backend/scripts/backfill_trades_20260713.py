"""거래내역(/trades) 백필 — 2026-07-13 체결 4건 (P1-1 배포 이전 브로커 확인 체결).

P1-1 (commit 7b8dc13)이 kr_stock_trades 테이블 + 4개 체결 지점 기록을 추가했지만,
기록은 배포 시점부터만 쌓인다 — 그 이전(2026-07-13 11:18 KST경) 브로커에서 이미
확인된 체결 4건은 거래내역 탭에서 영구히 빈 값으로 보인다. 이 스크립트는 그 4건을
한 번만 직접 삽입한다 (조회 전용 실계정 접근 없음 — 값은 사용자가 브로커 화면에서
확인한 수치를 그대로 사용).

체결 내역 (브로커 확인):
- 000660 SK하이닉스 매수 19주 @1,909,000 (체결 19, 총액 36,271,000)
- 005930 삼성전자 매수 48주 @260,000 x3건 (각 체결 48, 총액 12,480,000)

멱등성: 결정론적 id(backfill-20260713-<종목코드>-<n>)로 삽입 전 존재 여부를 확인 —
이미 같은 id의 행이 있으면 건너뛴다. 여러 번 실행해도 안전하다.

실행 (backend/ 에서, 라이브 서버 재기동 불필요 — SQLite 파일에 직접 씀):
    python scripts/backfill_trades_20260713.py
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.storage_service import get_storage_service  # noqa: E402

CREATED_AT = datetime(2026, 7, 13, 11, 18, 0)

# 브로커 확인 체결 4건 — status/order_type은 trade_log.py의 정상 체결 지점
# (_execute_order / _apply_sell_fill / _poll_tracked_fills) 관례와 동일하게
# "completed"/"limit"을 사용한다 (executed_quantity >= quantity 인 완전 체결).
RECORDS: list[dict[str, Any]] = [
    {
        "id": "backfill-20260713-000660-1",
        "session_id": None,
        "stk_cd": "000660",
        "stk_nm": "SK하이닉스",
        "side": "buy",
        "order_type": "limit",
        "price": 1_909_000,
        "quantity": 19,
        "executed_quantity": 19,
        "fee": 0,
        "total_krw": 36_271_000,
        "status": "completed",
        "order_id": None,
        "created_at": CREATED_AT,
    },
    *(
        {
            "id": f"backfill-20260713-005930-{n}",
            "session_id": None,
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "side": "buy",
            "order_type": "limit",
            "price": 260_000,
            "quantity": 48,
            "executed_quantity": 48,
            "fee": 0,
            "total_krw": 12_480_000,
            "status": "completed",
            "order_id": None,
            "created_at": CREATED_AT,
        }
        for n in (1, 2, 3)
    ),
]


async def main() -> int:
    storage = await get_storage_service()

    inserted = 0
    skipped = 0
    for record in RECORDS:
        existing = await storage.get_kr_stock_trade(record["id"])
        if existing is not None:
            print(f"SKIP (already exists): {record['id']}")
            skipped += 1
            continue

        ok = await storage.add_kr_stock_trade(record)
        if ok:
            print(
                f"INSERTED: {record['id']} — {record['stk_cd']} {record['stk_nm']} "
                f"{record['side']} {record['executed_quantity']}주 @ {record['price']:,}"
            )
            inserted += 1
        else:
            print(f"FAILED to insert: {record['id']}")

    total = await storage.get_kr_stock_trades_count()
    print(f"\n완료: inserted={inserted} skipped={skipped} (테이블 전체 건수={total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
