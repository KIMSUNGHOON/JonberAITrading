"""모의투자 성과 리포트 (Paper-Proof Phase D1).

Kiwoom 모의 계좌의 기간 실현손익(ka10074)과 현재 자산으로 운용 성과를
출력한다. 조회 전용 — 주문 없음.

실행 (backend/ 에서):
    python scripts/paper_performance_report.py [시작일 YYYYMMDD] [종료일] [--base 기준자산]

기본: 최근 14일. 기준 자산(--base)은 운용 개시 시점의 자산 — D3 운용 시작 시
이 스크립트를 1회 실행해 '현재 자산'을 기준값으로 기록해 둔다 (런북 참조).
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.kiwoom import KiwoomClient  # noqa: E402
from services.trading.paper_performance import build_performance_report  # noqa: E402

KST = timezone(timedelta(hours=9))


async def main() -> int:
    parser = argparse.ArgumentParser(description="모의투자 성과 리포트")
    parser.add_argument("strt_dt", nargs="?", default=None, help="시작일 YYYYMMDD")
    parser.add_argument("end_dt", nargs="?", default=None, help="종료일 YYYYMMDD")
    parser.add_argument("--base", type=int, default=None,
                        help="운용 시작 기준 자산 (원) — 누적 수익률 분모")
    args = parser.parse_args()

    end_dt = args.end_dt or datetime.now(KST).strftime("%Y%m%d")
    strt_dt = args.strt_dt or (
        datetime.now(KST) - timedelta(days=14)
    ).strftime("%Y%m%d")

    from app.config import settings

    app_key = settings.KIWOOM_APP_KEY or ""
    secret = settings.KIWOOM_SECRET_KEY or ""
    if not (app_key and secret):
        print("FAIL: .env에 KIWOOM_APP_KEY/KIWOOM_SECRET_KEY가 없습니다")
        return 1

    client = KiwoomClient(
        app_key=app_key, secret_key=secret,
        is_mock=getattr(settings, "KIWOOM_IS_MOCK", True),
    )
    try:
        pnl = await client.get_realized_pnl(strt_dt=strt_dt, end_dt=end_dt)
        balance = await client.get_account_balance()
        current_asset = balance.evlu_amt + balance.d2_ord_psbl_amt
        report = build_performance_report(
            pnl, current_asset=current_asset, base_asset=args.base
        )
        print(f"server={client.base_url} is_mock={client.is_mock}\n")
        print(report.render_text())
        if balance.holdings:
            print("-" * 46)
            print("보유 포지션:")
            for h in balance.holdings:
                print(
                    f"  {h.stk_cd} {h.stk_nm}  {h.hldg_qty}주 @ {h.avg_buy_prc:,} "
                    f"(현재 {h.cur_prc:,}, 손익 {h.evlu_pfls_amt:+,})"
                )
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
