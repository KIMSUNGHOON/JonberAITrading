"""Kiwoom 읽기 전용 스모크 (Paper-Proof Phase A2).

모의투자 서버(mockapi.kiwoom.com)에 대해 조회 계열 전 메서드를 실증한다.
주문 계열 메서드는 실행 전에 몽키패치로 봉쇄되어 어떤 경로로도 호출될 수
없다 — 이 스크립트는 어떤 주문도 내지 않는다.

실행 (backend/ 에서):
    python scripts/kiwoom_readonly_smoke.py [종목코드=005930]

Phase E(실전 전환) 때 is_mock=False 환경에서 그대로 재사용한다.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402

from services.kiwoom import KiwoomClient  # noqa: E402

ORDER_METHODS = [
    "place_buy_order",
    "place_sell_order",
    "modify_order",
    "cancel_order",
    "buy_market_order",
    "sell_market_order",
]


def _block_order_methods(client: KiwoomClient) -> None:
    """주문 메서드를 호출 즉시 RuntimeError로 봉쇄한다 (읽기 전용 하드가드)."""

    def _blocked(name):
        async def _raise(*args, **kwargs):
            raise RuntimeError(f"READ-ONLY SMOKE: order method '{name}' is blocked")

        return _raise

    for name in ORDER_METHODS:
        assert hasattr(client, name), f"unknown order method: {name}"
        setattr(client, name, _blocked(name))


async def main() -> int:
    stk_cd = sys.argv[1] if len(sys.argv) > 1 else "005930"

    from app.config import settings

    app_key = settings.KIWOOM_APP_KEY or ""
    secret = settings.KIWOOM_SECRET_KEY or ""
    is_mock = getattr(settings, "KIWOOM_IS_MOCK", True)
    if not (app_key and secret):
        print("FAIL: .env에 KIWOOM_APP_KEY/KIWOOM_SECRET_KEY가 없습니다")
        return 1

    client = KiwoomClient(app_key=app_key, secret_key=secret, is_mock=is_mock)
    _block_order_methods(client)
    print(f"server={client.base_url} is_mock={client.is_mock} ticker={stk_cd}")

    checks = [
        ("get_cash_balance", lambda: client.get_cash_balance()),
        ("get_account_balance", lambda: client.get_account_balance()),
        ("get_stock_info", lambda: client.get_stock_info(stk_cd)),
        ("get_orderbook", lambda: client.get_orderbook(stk_cd)),
        ("get_daily_chart", lambda: client.get_daily_chart(stk_cd)),
        ("get_pending_orders", lambda: client.get_pending_orders()),
        ("get_filled_orders", lambda: client.get_filled_orders()),
        ("get_current_price", lambda: client.get_current_price(stk_cd)),
    ]

    failures = 0
    for name, call in checks:
        try:
            result = await call()
        except ValidationError as e:
            failures += 1
            print(f"FAIL {name}: ValidationError — {e.errors()[:3]}")
        except Exception as e:
            failures += 1
            print(f"FAIL {name}: {type(e).__name__} — {e}")
        else:
            if isinstance(result, list):
                summary = f"{len(result)} rows"
            else:
                summary = type(result).__name__
            print(f"OK   {name}: {summary}")

    # 봉쇄 가드 자체 검증 — 주문 메서드가 정말 막혔는지 확인한다.
    try:
        await client.place_buy_order(stk_cd, 1, 0)
        print("FAIL guard: place_buy_order가 봉쇄되지 않았습니다!")
        failures += 1
    except RuntimeError as e:
        print(f"OK   guard: {e}")

    await client.close()
    print(f"\n{'PASS' if failures == 0 else 'FAIL'}: {len(checks) - failures}/{len(checks)} checks")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
