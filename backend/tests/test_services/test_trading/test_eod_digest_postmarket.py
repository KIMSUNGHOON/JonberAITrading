"""Task 7 (2026-08-13): postmarket 리포트 전용 수집기.

`build_eod_digest`의 반환 dict에는 fills/realized/strategy_revisions 키가
없다(실물 확인, task-7-report.md 참고) — 그래서 `coordinator.py`가
`build_eod_digest`와 별개로 이 세 함수를 storage에서 직접 호출한다. 이
파일은 그 세 함수 자체의 날짜 필터링·gross/net 선택·리비전 diff 로직을
검증한다(렌더 쪽 계약은 test_reports_postmarket.py가 이미 고정했다).
"""
import json
from datetime import datetime

import pytest

from services.trading.eod_digest import (
    _build_postmarket_fills,
    _build_postmarket_realized,
    _build_postmarket_revisions,
)

pytestmark = pytest.mark.asyncio


async def _seed_fill(storage, *, id_, stk_cd, side, price, qty, created_at,
                      entry_or_exit):
    await storage.add_kr_stock_trade({
        "id": id_, "session_id": None, "stk_cd": stk_cd, "stk_nm": None,
        "side": side, "order_type": "market", "price": price,
        "quantity": qty, "executed_quantity": qty, "fee": 100,
        "total_krw": price * qty, "status": "completed", "order_id": "o1",
        "created_at": created_at, "decision_id": None, "strategy_id": None,
        "entry_or_exit": entry_or_exit, "tax": 0, "cost_source": "model",
    })


async def test_fills_filters_to_trade_date_and_maps_fields(isolated_storage_service):
    storage = isolated_storage_service
    await _seed_fill(
        storage, id_="a", stk_cd="316140", side="sell", price=33106, qty=549,
        created_at=datetime(2026, 8, 13, 13, 25, 0), entry_or_exit="exit",
    )
    await _seed_fill(
        storage, id_="b", stk_cd="086790", side="buy", price=128200, qty=51,
        created_at=datetime(2026, 8, 12, 13, 37, 0), entry_or_exit="entry",
    )

    out = await _build_postmarket_fills(storage, "2026-08-13")

    assert len(out) == 1
    row = out[0]
    assert row["ticker"] == "316140"
    assert row["side"] == "SELL"
    assert row["quantity"] == 549
    assert row["price"] == 33106
    assert row["time"] == "13:25"
    assert row["reason"] == "청산"


async def test_fills_entry_side_has_no_fabricated_reason(isolated_storage_service):
    storage = isolated_storage_service
    await _seed_fill(
        storage, id_="c", stk_cd="086790", side="buy", price=128200, qty=51,
        created_at=datetime(2026, 8, 13, 13, 37, 0), entry_or_exit="entry",
    )
    out = await _build_postmarket_fills(storage, "2026-08-13")
    assert out[0]["reason"] is None


async def test_fills_empty_when_no_trades_that_day(isolated_storage_service):
    storage = isolated_storage_service
    assert await _build_postmarket_fills(storage, "2026-08-13") == []


async def test_realized_uses_net_not_gross_and_excludes_all_backfill(
    isolated_storage_service,
):
    storage = isolated_storage_service
    await storage.save_kr_realized_pnl({
        "id": "r1", "stk_cd": "316140", "entry_price": 34050, "exit_price": 33106,
        "quantity": 183, "realized_amount": -172782.0,
        "created_at": datetime(2026, 8, 13, 13, 26, 0),
        "fee": 500, "tax": 300, "net_amount": -173582.0, "cost_source": "model",
    })
    # 계좌 백필 행 — 거래가 아니므로 제외돼야 한다
    await storage.save_kr_realized_pnl({
        "id": "r2", "stk_cd": "ALL", "entry_price": None, "exit_price": None,
        "quantity": None, "realized_amount": 999999.0,
        "created_at": datetime(2026, 8, 13, 9, 0, 0),
        "fee": 0, "tax": 0, "net_amount": 999999.0, "cost_source": "model",
    })

    out = await _build_postmarket_realized(storage, "2026-08-13")

    assert len(out) == 1
    assert out[0] == {"ticker": "316140", "quantity": 183, "net": -173582.0, "slices": 1}


async def test_realized_falls_back_to_gross_when_net_missing(isolated_storage_service):
    storage = isolated_storage_service
    await storage.save_kr_realized_pnl({
        "id": "r3", "stk_cd": "090430", "entry_price": 100, "exit_price": 110,
        "quantity": 2, "realized_amount": 20.0,
        "created_at": datetime(2026, 8, 13, 10, 0, 0),
        # net_amount 생략 -- 마이그레이션 이전 옛 행 흉내
    })
    out = await _build_postmarket_realized(storage, "2026-08-13")
    assert out == [{"ticker": "090430", "quantity": 2, "net": 20.0, "slices": 1}]


async def test_realized_aggregates_multiple_slices_of_same_ticker(
    isolated_storage_service,
):
    """리뷰 Critical 2 재현: `kr_realized_pnl`은 매도 체결 1건당 1행이라
    부분체결로 나뉜 청산은 같은 종목이 여러 행으로 쌓인다(실측:
    2026-08-12 316140 청산 183+183+92+91=549주, 4행). 합산 없이 그대로
    내보내면 "정상 부분청산 4건"과 kr_stock_trades의 알려진 중복 기록
    버그를 사람이 구별할 수 없다 -- 한 줄로 합치되 슬라이스 수는 남긴다.
    """
    storage = isolated_storage_service
    slices = [
        (183, -35496.0215308439), (183, -31826.3953938205),
        (92, -67868.4169246648), (91, -63670.4169246648),
    ]
    for i, (qty, net) in enumerate(slices):
        await storage.save_kr_realized_pnl({
            "id": f"slice-{i}", "stk_cd": "316140", "entry_price": 34050,
            "exit_price": 33106, "quantity": qty, "realized_amount": net + 1000,
            "created_at": datetime(2026, 8, 13, 13, 25, i),
            "fee": 400, "tax": 600, "net_amount": net, "cost_source": "model",
        })
    # 다른 종목 1건 -- 섞여 합산되면 안 된다
    await storage.save_kr_realized_pnl({
        "id": "other", "stk_cd": "090430", "entry_price": 100, "exit_price": 110,
        "quantity": 2, "realized_amount": 20.0,
        "created_at": datetime(2026, 8, 13, 10, 0, 0),
        "fee": 0, "tax": 0, "net_amount": 20.0, "cost_source": "model",
    })

    out = await _build_postmarket_realized(storage, "2026-08-13")

    by_ticker = {r["ticker"]: r for r in out}
    assert len(out) == 2  # 316140 한 줄 + 090430 한 줄 -- 4행이 4줄로 새지 않는다

    row = by_ticker["316140"]
    assert row["quantity"] == 549  # 183+183+92+91
    assert row["net"] == pytest.approx(sum(n for _, n in slices))
    assert row["slices"] == 4  # 합쳐졌다는 사실 자체는 숨기지 않는다

    assert by_ticker["090430"] == {
        "ticker": "090430", "quantity": 2, "net": 20.0, "slices": 1,
    }


def _strategy_json(vol_multiplier_min: float, stop_loss_pct: float = 0.07) -> str:
    return json.dumps({
        "exit_conditions": {"stop_loss_pct": stop_loss_pct, "take_profit_pct": 0.15},
        "position_sizing": {
            "max_position_pct": 0.10, "min_cash_ratio": 0.20,
            "max_trade_notional_pct": 15.0, "risk_budget_pct": 0.75,
            "target_vol_pct": 18.0, "vol_multiplier_min": vol_multiplier_min,
        },
    })


async def test_revisions_diff_changed_knob_between_latest_two(isolated_storage_service):
    storage = isolated_storage_service
    await storage.save_strategy_revision({
        "id": "rev1", "trade_date": "2026-08-12", "source": "eod_consensus",
        "stance": "defensive", "consensus_level": 0.8, "changed": True,
        "strategy_json": _strategy_json(0.4),
    })
    await storage.save_strategy_revision({
        "id": "rev2", "trade_date": "2026-08-13", "source": "eod_consensus",
        "stance": "defensive", "consensus_level": 0.8, "changed": True,
        "strategy_json": _strategy_json(0.3),
    })

    out = await _build_postmarket_revisions(storage, "2026-08-13")

    knobs = {r["knob"]: r for r in out}
    assert knobs["vol_multiplier_min"] == {
        "knob": "vol_multiplier_min", "before": 0.4, "after": 0.3,
    }
    # stop_loss_pct는 두 리비전 모두 0.07 -- 변화가 없으니 출력에 없어야 한다
    assert "stop_loss_pct" not in knobs


async def test_revisions_empty_when_latest_row_unchanged(isolated_storage_service):
    storage = isolated_storage_service
    await storage.save_strategy_revision({
        "id": "rev1", "trade_date": "2026-08-12", "source": "eod_consensus",
        "stance": "defensive", "consensus_level": 0.8, "changed": True,
        "strategy_json": _strategy_json(0.4),
    })
    await storage.save_strategy_revision({
        "id": "rev2", "trade_date": "2026-08-13", "source": "eod_consensus",
        "stance": "defensive", "consensus_level": 0.8, "changed": False,
        "strategy_json": _strategy_json(0.4),
    })
    assert await _build_postmarket_revisions(storage, "2026-08-13") == []


async def test_revisions_empty_when_latest_row_is_not_today(isolated_storage_service):
    """합의가 아직 안 돌았으면(오늘자 행이 없으면) '오늘 개정'은 없다."""
    storage = isolated_storage_service
    await storage.save_strategy_revision({
        "id": "rev1", "trade_date": "2026-08-11", "source": "eod_consensus",
        "stance": "defensive", "consensus_level": 0.8, "changed": True,
        "strategy_json": _strategy_json(0.5),
    })
    await storage.save_strategy_revision({
        "id": "rev2", "trade_date": "2026-08-12", "source": "eod_consensus",
        "stance": "defensive", "consensus_level": 0.8, "changed": True,
        "strategy_json": _strategy_json(0.4),
    })
    assert await _build_postmarket_revisions(storage, "2026-08-13") == []


async def test_revisions_empty_with_fewer_than_two_rows(isolated_storage_service):
    storage = isolated_storage_service
    await storage.save_strategy_revision({
        "id": "rev1", "trade_date": "2026-08-13", "source": "eod_consensus",
        "stance": "defensive", "consensus_level": 0.8, "changed": True,
        "strategy_json": _strategy_json(0.4),
    })
    assert await _build_postmarket_revisions(storage, "2026-08-13") == []
