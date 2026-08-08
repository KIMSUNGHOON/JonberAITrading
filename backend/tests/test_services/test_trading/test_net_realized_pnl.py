"""순 실현손익(net) — 학습 신호가 거래비용을 무시하던 것을 봉합.

`kr_realized_pnl.realized_amount`는 (exit-entry)*qty 순수 gross였고, 그 값이
그대로 `agent_chat_decisions.outcome_realized_pnl`로 백필돼 calibration의
에이전트 정오답 채점 → 전략 재가중으로 흘러갔다. 비용을 못 넘긴 거래가
"승리"로 학습됐다.

실측(2026-08-08 라이브 DB 25행) 중 1건이 부호를 뒤집는다 — 아래
`_SAMSUNG_*` 상수가 그 행이다.

비용 기준은 앱 자체 모델(`services/trading/cost_model.compute_fill_cost`,
편도 수수료 2bp + 매도 증권거래세 23bp = 왕복 0.27%)이다. 모의 브로커의
실제 요율(왕복 0.90%)이 아니라 실전 키움(~0.19~0.23%)에 가까운 이쪽을
쓴다 — 캘리브레이션이 학습해야 하는 것은 실전에서 일반화되는 문턱이다.
"""

import uuid

import pytest

import services.storage_service as ss
from services.trading import trade_log
from services.trading.eod_snapshot import (
    _BACKFILL_STK_CD_SENTINEL,
    _count_win_loss_trades,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.usefixtures("isolated_storage_service"),
]


# 라이브 DB 실측 행 (005930 삼성전자, exit_at 2026-07-22 09:02:08).
_SAMSUNG_ENTRY = 273_027.0
_SAMSUNG_EXIT = 273_420.0
_SAMSUNG_QTY = 56
_SAMSUNG_GROSS = 22_008.0  # (273420 - 273027) * 56
# 매수 15,289,512 * 2bp = 3,058 / 매도 15,311,520 * 2bp = 3,062
_SAMSUNG_FEE = 6_120
# 매도 15,311,520 * 23bp = 35,216
_SAMSUNG_TAX = 35_216
_SAMSUNG_NET = -19_328.0  # 22,008 - 6,120 - 35,216


def _samsung_kwargs(**overrides) -> dict:
    base = dict(
        stk_cd="005930",
        entry_price=_SAMSUNG_ENTRY,
        exit_price=_SAMSUNG_EXIT,
        quantity=_SAMSUNG_QTY,
        realized_amount=_SAMSUNG_GROSS,
    )
    base.update(overrides)
    return base


# -------------------------------------------
# 1) 정확한 숫자 — 모델 요율이 실제로 이 값을 낸다
# -------------------------------------------


async def test_records_exact_model_costs_for_live_samsung_row(
    isolated_storage_service,
):
    await trade_log.record_kr_realized_pnl_async(**_samsung_kwargs())

    rows = await isolated_storage_service.get_kr_realized_pnl(stk_cd="005930")
    assert len(rows) == 1
    row = rows[0]
    assert row["realized_amount"] == _SAMSUNG_GROSS  # gross는 절대 안 건드린다
    assert row["fee"] == _SAMSUNG_FEE
    assert row["tax"] == _SAMSUNG_TAX
    assert row["net_amount"] == _SAMSUNG_NET
    assert row["cost_source"] == "model"


# -------------------------------------------
# 2) 부호가 뒤집힌다 — 승패 카운터가 패로 센다
# -------------------------------------------


async def test_gross_win_becomes_net_loss_in_win_loss_counter(
    isolated_storage_service,
):
    await trade_log.record_kr_realized_pnl_async(
        **_samsung_kwargs(exit_at="2026-07-22 09:02:08.650523")
    )

    rows = await isolated_storage_service.get_kr_realized_pnl(stk_cd="005930")
    assert rows[0]["realized_amount"] > 0  # gross는 여전히 양수(승리처럼 보인다)
    assert rows[0]["net_amount"] < 0

    win, loss = await _count_win_loss_trades(
        isolated_storage_service, "2026-07-22"
    )
    assert (win, loss) == (0, 1)


# -------------------------------------------
# 3) 결정 백필이 net을 받는다
# -------------------------------------------


async def test_decision_outcome_backfill_uses_net_not_gross(
    isolated_storage_service,
):
    did = str(uuid.uuid4())
    await isolated_storage_service.save_agent_chat_decision(
        {
            "id": did,
            "ticker": "005930",
            "stock_name": "삼성전자",
            "trade_date": "2026-07-22",
            "status": "decided",
            "action": "BUY",
            "confidence": 0.7,
            "consensus_level": 0.8,
            "rationale": "돌파",
            "dissenting_opinions": None,
            "entry_price": _SAMSUNG_ENTRY,
            "stop_loss": None,
            "take_profit": None,
            "position_pct": 0.1,
            "news_sentiment": None,
            "news_count": 0,
            "behavioral_signals": None,
            "market_sentiment": None,
            "flow": None,
        },
        [],
    )

    await trade_log.record_kr_realized_pnl_async(
        **_samsung_kwargs(entry_decision_id=did)
    )

    got = await isolated_storage_service.get_agent_chat_decisions(
        ticker="005930"
    )
    assert got[0]["outcome_realized_pnl"] == _SAMSUNG_NET
    assert got[0]["outcome_realized_pnl"] != _SAMSUNG_GROSS


async def test_decision_outcome_backfill_passes_net_to_storage_call(
    isolated_storage_service, monkeypatch
):
    """호출 인자 자체를 관측한다 — 3번 테스트가 라벨/저장 경로를 통과하는
    동안, 이 테스트는 `update_decision_outcome`에 넘어간 값이 net인지를
    직접 본다(gross로 되돌리면 여기서 즉시 깨진다)."""
    seen: list = []

    async def _spy(decision_id, amount):
        seen.append((decision_id, amount))
        return True

    monkeypatch.setattr(
        isolated_storage_service, "update_decision_outcome", _spy
    )

    await trade_log.record_kr_realized_pnl_async(
        **_samsung_kwargs(entry_decision_id="dec-1")
    )

    assert seen == [("dec-1", _SAMSUNG_NET)]


# -------------------------------------------
# 4) 레거시 폴백 — net_amount가 NULL인 행은 gross 부호로 센다
# -------------------------------------------


async def test_legacy_row_without_net_amount_falls_back_to_gross(
    isolated_storage_service,
):
    await isolated_storage_service.save_kr_realized_pnl(
        {
            "id": str(uuid.uuid4()),
            "stk_cd": "093190",
            "entry_price": 8327.0,
            "exit_price": 9147.0,
            "quantity": 218,
            "realized_amount": 178_726.0,
            "exit_at": "2026-07-27 09:36:23.901505",
            # net_amount 없음 = 이 수정 이전에 쓰인 행
        }
    )

    rows = await isolated_storage_service.get_kr_realized_pnl(stk_cd="093190")
    assert rows[0]["net_amount"] is None

    win, loss = await _count_win_loss_trades(
        isolated_storage_service, "2026-07-27"
    )
    assert (win, loss) == (1, 0)


async def test_net_amount_wins_over_gross_when_both_present(
    isolated_storage_service,
):
    """폴백이 반대로 붙어 있지 않은지 — net이 있으면 net이 이긴다."""
    await isolated_storage_service.save_kr_realized_pnl(
        {
            "id": str(uuid.uuid4()),
            "stk_cd": "005930",
            "entry_price": _SAMSUNG_ENTRY,
            "exit_price": _SAMSUNG_EXIT,
            "quantity": _SAMSUNG_QTY,
            "realized_amount": _SAMSUNG_GROSS,
            "fee": _SAMSUNG_FEE,
            "tax": _SAMSUNG_TAX,
            "net_amount": _SAMSUNG_NET,
            "cost_source": "model",
            "exit_at": "2026-07-22 09:02:08.650523",
        }
    )

    win, loss = await _count_win_loss_trades(
        isolated_storage_service, "2026-07-22"
    )
    assert (win, loss) == (0, 1)


async def test_all_sentinel_row_still_excluded_from_win_loss(
    isolated_storage_service,
):
    """계좌 전체 백필 집계 행은 net 컬럼이 생겨도 여전히 매매가 아니다."""
    await isolated_storage_service.save_kr_realized_pnl(
        {
            "id": "backfill-20260722",
            "stk_cd": _BACKFILL_STK_CD_SENTINEL,
            "entry_price": None,
            "exit_price": None,
            "quantity": None,
            "realized_amount": 999_999.0,
            "exit_at": "2026-07-22",
        }
    )

    win, loss = await _count_win_loss_trades(
        isolated_storage_service, "2026-07-22"
    )
    assert (win, loss) == (0, 0)


# -------------------------------------------
# 5) 경계 — 0/음수 입력이면 net == gross (compute_fill_cost가 (0,0))
# -------------------------------------------


async def test_zero_quantity_leaves_net_equal_to_gross(
    isolated_storage_service,
):
    await trade_log.record_kr_realized_pnl_async(
        stk_cd="000660",
        entry_price=1_909_000.0,
        exit_price=1_755_000.0,
        quantity=0,
        realized_amount=-1_232_000.0,
    )

    row = (await isolated_storage_service.get_kr_realized_pnl(stk_cd="000660"))[0]
    assert row["fee"] == 0
    assert row["tax"] == 0
    assert row["net_amount"] == -1_232_000.0


# -------------------------------------------
# 6) never-raise 계약 — 비용 계산이 그 계약을 깨지 않는다
# -------------------------------------------


async def test_cost_model_failure_does_not_lose_the_ledger_row(
    isolated_storage_service, monkeypatch
):
    """`compute_fill_cost`는 `get_paper_fill_settings()`를 호출한다 —
    설정 구성이 터져도 (a) 예외가 호출자의 매도 경로로 전파되지 않고
    (b) 원장 행 자체를 잃지 않아야 한다(비용만 미상으로 남는다)."""
    import services.trading.cost_model as cost_model

    def _boom(*_a, **_kw):
        raise RuntimeError("settings boom")

    monkeypatch.setattr(cost_model, "compute_fill_cost", _boom)

    await trade_log.record_kr_realized_pnl_async(**_samsung_kwargs())

    rows = await isolated_storage_service.get_kr_realized_pnl(stk_cd="005930")
    assert len(rows) == 1, "비용 계산 실패가 원장 행을 통째로 삼켰다"
    assert rows[0]["realized_amount"] == _SAMSUNG_GROSS


async def test_storage_failure_still_never_raises(monkeypatch):
    async def _boom():
        raise RuntimeError("db boom")

    monkeypatch.setattr(ss, "get_storage_service", _boom)

    await trade_log.record_kr_realized_pnl_async(**_samsung_kwargs())
