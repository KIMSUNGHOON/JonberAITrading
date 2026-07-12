"""
Shared Autonomy Gate (R3)

The SINGLE policy point every autonomous execution request must pass. Exactly
two consumers: the analysis-pipeline auto-approve injector and the
ChatCoordinator execution path — both autonomy engines share one policy.

Check chain (first failure denies):
    master_gate → market_mode → paper_only → daily_loss_breaker
    → max_positions (BUY/ADD only) → notional_cap (BUY/ADD only)

Design rules:
- FAIL-CLOSED: any provider error converts to a deny with the failing check's
  name. Autonomy only acts when every check is affirmatively green.
- The paper_only check is HARDCODED — no setting can produce autonomous+live.
  (Relaxing it is an explicit, separate P3 change.)
- Limits come from RiskParameters (max_daily_loss_pct / max_open_positions /
  max_trade_notional_krw), adjustable via the existing risk-params API.

Spec: docs/superpowers/specs/2026-07-11-r3-autonomous-hitl-mode-design.md §2.1
"""

from dataclasses import dataclass
from datetime import date
from typing import Awaitable, Callable, Optional

import structlog

from app.config import settings
from services.trading.models import RiskParameters

logger = structlog.get_logger()

# Actions that grow exposure — the only ones subject to position/notional caps.
POSITION_INCREASING_ACTIONS = {"BUY", "ADD"}

Provider = Callable[[str], Awaitable]

# Circuit-breaker Telegram notice: at most once per local date.
_last_breaker_notice_date: Optional[date] = None


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str  # "ok" when allowed; deny reason otherwise
    check: str   # failed check name; "all" when allowed


def _deny(check: str, reason: str) -> GateDecision:
    logger.info("autonomy_gate_denied", check=check, reason=reason)
    return GateDecision(allowed=False, reason=reason, check=check)


async def _notify_breaker(message: str) -> None:
    """Best-effort Telegram notice when the daily-loss breaker trips."""
    try:
        from services.telegram import get_telegram_notifier

        notifier = await get_telegram_notifier()
        if notifier.is_ready:
            await notifier.send_message(message)
    except Exception as e:  # never let notification failure affect the gate
        logger.warning("breaker_notify_failed", error=str(e))


# -------------------------------------------
# Default providers
# -------------------------------------------


async def _default_mode_provider(market: str) -> str:
    from services.storage_service import get_storage_service

    storage = await get_storage_service()
    return await storage.get_app_setting(f"trading_mode:{market}", "hitl")


def _client_is_mock(client) -> bool:
    """A Kiwoom client is paper ONLY if both its flag and its bound URL say so."""
    return bool(
        getattr(client, "is_mock", False)
        and getattr(client, "base_url", None) == getattr(client, "MOCK_URL", object())
    )


async def _default_paper_provider(market: str) -> bool:
    if market == "kiwoom":
        # 1. Runtime intent flag (settings modal can flip it; falls back to env).
        from app.api.routes.settings import get_kiwoom_is_mock

        if not get_kiwoom_is_mock():
            return False

        # 2. Bind to the clients that ACTUALLY execute — the intent flag alone
        # is not enough: a client/coordinator constructed while live keeps its
        # live base URL even after the flag is flipped back to paper.
        from app.core.kiwoom_singleton import get_shared_kiwoom_client_async

        shared = await get_shared_kiwoom_client_async()
        if not _client_is_mock(shared):
            return False

        import app.dependencies as deps

        coordinator = getattr(deps, "_trading_coordinator_instance", None)
        captured = getattr(coordinator, "_kiwoom", None) if coordinator else None
        if captured is not None and not _client_is_mock(captured):
            return False

        return True
    if market == "coin":
        return settings.UPBIT_TRADING_MODE == "paper"
    return False  # unknown market: not provably paper → deny


async def _default_daily_loss_provider(market: str) -> float:
    """Today's realized loss as % of account value (≥0; 0 = no loss).

    kiwoom: 브로커의 당일 실현손익(ka10074)을 계좌 평가액(주식 평가 + D+2
    예수금) 대비 %로 환산한다 (Phase B2). 조회 실패·평가액 0은 예외로
    전파한다 — 게이트의 breaker 랩이 deny 처리하므로 fail-closed.

    coin: 실현 P&L 소스가 아직 없어(coin_trades에 pnl 컬럼 없음) 0 반환 —
    브레이커 비활성. coin 운용을 시작할 때 배선한다.
    """
    if market == "kiwoom":
        import app.core.kiwoom_singleton as kiwoom_singleton

        client = await kiwoom_singleton.get_shared_kiwoom_client_async()
        pnl = await client.get_realized_pnl()  # 당일 (KST)
        if pnl.realized_pnl >= 0:
            return 0.0
        balance = await client.get_account_balance()
        account_value = balance.evlu_amt + balance.d2_ord_psbl_amt
        if account_value <= 0:
            raise ValueError(
                "계좌 평가액이 0이라 당일 손실률을 계산할 수 없습니다 (fail-closed)"
            )
        return abs(pnl.realized_pnl) / account_value * 100.0
    return 0.0


async def _default_positions_count_provider(market: str) -> int:
    if market == "coin":
        from services.storage_service import get_storage_service

        storage = await get_storage_service()
        return len(await storage.get_coin_positions())
    if market == "kiwoom":
        # Storage has no KR position store — count from the broker (the mock
        # server in paper mode). Errors bubble to the gate's fail-closed wrap.
        from app.core.kiwoom_singleton import get_shared_kiwoom_client_async

        client = await get_shared_kiwoom_client_async()
        balance = await client.get_account_balance()
        return len(balance.holdings or [])
    raise ValueError(f"unknown market: {market}")


def _default_risk_params() -> RiskParameters:
    """Runtime risk params if the trading coordinator exists, else defaults."""
    import app.dependencies as deps

    coordinator = getattr(deps, "_trading_coordinator_instance", None)
    params = getattr(coordinator, "risk_params", None)
    return params if isinstance(params, RiskParameters) else RiskParameters()


# -------------------------------------------
# The gate
# -------------------------------------------


async def check_autonomy(
    market: str,
    *,
    action: str,
    quantity: Optional[float],
    entry_price: Optional[float],
    mode_provider: Optional[Provider] = None,
    paper_provider: Optional[Provider] = None,
    daily_loss_provider: Optional[Provider] = None,
    positions_count_provider: Optional[Provider] = None,
    risk_params_provider: Optional[Callable[[], RiskParameters]] = None,
) -> GateDecision:
    """Decide whether an autonomous execution is allowed. Fail-closed."""
    global _last_breaker_notice_date

    mode_provider = mode_provider or _default_mode_provider
    paper_provider = paper_provider or _default_paper_provider
    daily_loss_provider = daily_loss_provider or _default_daily_loss_provider
    positions_count_provider = positions_count_provider or _default_positions_count_provider
    risk_params_provider = risk_params_provider or _default_risk_params

    # 1. Master gate (env)
    if not settings.AUTONOMY_ENABLED:
        return _deny("master_gate", "AUTONOMY_ENABLED is off")

    # 2. Per-market mode
    try:
        mode = await mode_provider(market)
    except Exception as e:
        return _deny("market_mode", str(e))
    if mode != "autonomous":
        return _deny("market_mode", f"trading_mode:{market} is '{mode}'")

    # 3. Paper-only — HARDCODED. Autonomous+live is impossible (P3 change only).
    try:
        is_paper = await paper_provider(market)
    except Exception as e:
        return _deny("paper_only", str(e))
    if not is_paper:
        return _deny("paper_only", f"{market} is not in paper/mock mode")

    try:
        params = risk_params_provider()
    except Exception as e:
        return _deny("risk_params", str(e))

    # 4. Daily-loss circuit breaker (re-computed per request — the check IS the breaker)
    try:
        loss_pct = float(await daily_loss_provider(market))
    except Exception as e:
        return _deny("daily_loss_breaker", str(e))
    if loss_pct >= params.max_daily_loss_pct:
        today = date.today()
        if _last_breaker_notice_date != today:
            _last_breaker_notice_date = today
            await _notify_breaker(
                f"⛔ 자율 매매 서킷 브레이커 발동: 당일 실현 손실 {loss_pct:.2f}% ≥ "
                f"한도 {params.max_daily_loss_pct:.2f}%. 오늘 자율 승인은 전면 중단됩니다 (HITL은 정상)."
            )
        return _deny(
            "daily_loss_breaker",
            f"daily loss {loss_pct:.2f}% >= limit {params.max_daily_loss_pct:.2f}%",
        )

    # 5 + 6 apply only to exposure-increasing actions.
    if action in POSITION_INCREASING_ACTIONS:
        # 5. Max concurrent positions
        try:
            count = int(await positions_count_provider(market))
        except Exception as e:
            return _deny("max_positions", str(e))
        if count >= params.max_open_positions:
            return _deny(
                "max_positions",
                f"open positions {count} >= limit {params.max_open_positions}",
            )

        # 6. Per-trade notional cap (unknown size = fail-closed)
        if quantity is None or entry_price is None:
            return _deny("notional_cap", "quantity/entry_price unknown for a BUY/ADD")
        notional = float(quantity) * float(entry_price)
        if notional > params.max_trade_notional_krw:
            return _deny(
                "notional_cap",
                f"notional ₩{notional:,.0f} > cap ₩{params.max_trade_notional_krw:,.0f}",
            )

    return GateDecision(allowed=True, reason="ok", check="all")
