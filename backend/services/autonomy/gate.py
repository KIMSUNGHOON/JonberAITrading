"""
Shared Autonomy Gate (R3)

The SINGLE policy point every autonomous execution request must pass. Exactly
two consumers: the analysis-pipeline auto-approve injector and the
ChatCoordinator execution path — both autonomy engines share one policy.

Check chain (first failure denies):
    master_gate → market_mode → paper_only
    → daily_loss_breaker (BUY/ADD only, S-1/D3)
    → coordinator_active (BUY/ADD, kiwoom only)
    → max_positions (BUY/ADD only) → notional_cap (BUY/ADD only, kiwoom only)

Design rules:
- FAIL-CLOSED: any provider error converts to a deny with the failing check's
  name. Autonomy only acts when every check is affirmatively green.
- The paper_only check is HARDCODED — no setting can produce autonomous+live.
  (Relaxing it is an explicit, separate P3 change.)
- Limits come from RiskParameters (max_daily_loss_pct / max_open_positions /
  max_trade_notional_pct), adjustable via the existing risk-params API.
- The daily-loss breaker is scoped to POSITION_INCREASING_ACTIONS (S-1/D3,
  docs/superpowers/specs/2026-07-19-survival-discipline-design.md §D3): no
  short-selling exists in this system, so SELL/REDUCE is always a size-down
  and can never deepen today's loss — exempting it keeps the breaker's
  purpose (stop compounding losses) intact instead of also freezing the
  stop-loss exit that would stop the bleeding. master_gate/market_mode/
  paper_only stay action-agnostic (they precede the action branch).

Spec: docs/superpowers/specs/2026-07-11-r3-autonomous-hitl-mode-design.md §2.1
Spec: docs/superpowers/specs/2026-07-19-survival-discipline-design.md §D3 (S-1)
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
        tickers = {h.stk_cd for h in (balance.holdings or [])}

        # F3 (I2): the account-balance snapshot is ~30s cached and blind to a
        # BUY that has been placed but not (fully) filled yet — a burst of
        # autonomous BUYs can blow past max_open_positions before the next
        # refresh sees them. Union in tickers the coordinator's fill tracker
        # is still watching for a BUY fill (audit I2, 2026-07-14). Same
        # getattr pattern as _default_risk_params/_default_paper_provider;
        # no coordinator constructed yet → nothing pending to add.
        import app.dependencies as deps

        coordinator = getattr(deps, "_trading_coordinator_instance", None)
        if coordinator is not None:
            tickers |= {
                t.ticker
                for t in coordinator.fill_tracker.tracking()
                if t.side == "buy"
            }

        return len(tickers)
    raise ValueError(f"unknown market: {market}")


def _default_risk_params() -> RiskParameters:
    """Runtime risk params if the trading coordinator exists, else defaults."""
    import app.dependencies as deps

    coordinator = getattr(deps, "_trading_coordinator_instance", None)
    params = getattr(coordinator, "risk_params", None)
    return params if isinstance(params, RiskParameters) else RiskParameters()


async def _default_coordinator_active_provider(market: str) -> bool:
    """Kiwoom only: is the trading coordinator started (`/trading/start`)?

    A BUY/ADD placed through the graph's execution node registers its
    unfilled remainder with `coordinator.fill_tracker` (F3) so the
    coordinator's own scheduler loop can poll ka10076 for the post-fill and
    register the resulting position's stop-loss/take-profit. That poll loop
    — and RiskMonitor/PositionManager's defensive-exit watch — only run once
    the coordinator is active. `get_trading_coordinator()` lazily constructs
    the singleton on first use regardless of activity, so an *existing but
    inactive* instance is just as dead here as `None` (audit I6, 2026-07-14):
    the new exposure would sit unwatched with nothing to reconcile or defend
    it. Same getattr pattern as `_default_risk_params`/`_default_paper_provider`.
    """
    import app.dependencies as deps

    coordinator = getattr(deps, "_trading_coordinator_instance", None)
    return coordinator is not None and bool(coordinator.is_active)


async def _default_account_equity_provider(market: str) -> Optional[float]:
    """총평가액 = evlu_amt + d2_ord_psbl_amt (daily-loss breaker와 동일 소스, F4b/B2)."""
    if market != "kiwoom":
        return None  # coin은 범위 밖 (notional %상한 미적용)
    from app.core.kiwoom_singleton import get_shared_kiwoom_client_async

    client = await get_shared_kiwoom_client_async()
    balance = await client.get_account_balance()
    return float(balance.evlu_amt + balance.d2_ord_psbl_amt)


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
    coordinator_active_provider: Optional[Provider] = None,
    account_equity_provider: Optional[Provider] = None,
) -> GateDecision:
    """Decide whether an autonomous execution is allowed. Fail-closed.

    NOTE (I6 scoping): this function is the shared policy point for
    AUTONOMOUS execution only — the injector's pre-check/re-check and every
    coordinator/PositionManager auto-execution call it; a human's manual
    decision (`app.api.routes.approval.submit_decision`, actor='user' or the
    injector's own actor='system' call INTO it) never does. So a check added
    here — like the coordinator-active link below — can only ever gate an
    autonomous request; it cannot block HITL, which doesn't pass through
    this function at all.
    """
    global _last_breaker_notice_date

    mode_provider = mode_provider or _default_mode_provider
    paper_provider = paper_provider or _default_paper_provider
    daily_loss_provider = daily_loss_provider or _default_daily_loss_provider
    positions_count_provider = positions_count_provider or _default_positions_count_provider
    risk_params_provider = risk_params_provider or _default_risk_params
    coordinator_active_provider = coordinator_active_provider or _default_coordinator_active_provider
    account_equity_provider = account_equity_provider or _default_account_equity_provider

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

    # 4 + 5 + 6 + 7 apply only to exposure-increasing actions (S-1 / D3,
    # docs/superpowers/specs/2026-07-19-survival-discipline-design.md §D3):
    # this system has no short-selling, so a SELL/REDUCE is always a
    # size-down — it can never be the thing that deepens today's loss.
    # Scoping the daily-loss breaker to BUY/ADD (same guard as caps 5/6/7
    # already use) keeps the breaker's purpose intact — stop compounding
    # losses — while removing the paradox where a tripped breaker also
    # blocks the stop-loss exit that would stop the bleeding. Master gate /
    # market mode / paper-only above are unaffected: they gate the request
    # regardless of action, before this branch is ever reached.
    if action in POSITION_INCREASING_ACTIONS:
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

        # 5. Coordinator must be active (kiwoom only — coin has no equivalent
        # fill-tracker/coordinator; scoped here, not in the provider, in case
        # a caller ever swaps a coin-specific default in). See
        # _default_coordinator_active_provider for why an inactive/None
        # coordinator must deny a BUY/ADD.
        if market == "kiwoom":
            try:
                coordinator_ok = bool(await coordinator_active_provider(market))
            except Exception as e:
                return _deny("coordinator_active", str(e))
            if not coordinator_ok:
                return _deny(
                    "coordinator_active",
                    "사후 체결 추적 불가 — trading 시스템 미기동",
                )

        # 6. Max concurrent positions
        try:
            count = int(await positions_count_provider(market))
        except Exception as e:
            return _deny("max_positions", str(e))
        if count >= params.max_open_positions:
            return _deny(
                "max_positions",
                f"open positions {count} >= limit {params.max_open_positions}",
            )

        # 7. Per-trade notional cap = equity × pct (fail-closed)
        if quantity is None or entry_price is None:
            return _deny("notional_cap", "quantity/entry_price unknown for a BUY/ADD")
        if market == "kiwoom":
            try:
                equity = await (account_equity_provider or _default_account_equity_provider)(market)
            except Exception as e:
                return _deny("notional_cap", f"account equity unavailable: {e}")
            if not equity or equity <= 0:
                return _deny("notional_cap", "account equity unknown/zero")
            cap = equity * params.max_trade_notional_pct / 100.0
            notional = float(quantity) * float(entry_price)
            if notional > cap:
                return _deny(
                    "notional_cap",
                    f"notional ₩{notional:,.0f} > cap ₩{cap:,.0f} "
                    f"({params.max_trade_notional_pct}% of ₩{equity:,.0f})",
                )

    return GateDecision(allowed=True, reason="ok", check="all")
