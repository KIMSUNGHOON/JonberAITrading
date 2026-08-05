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
    return False  # unknown market: not provably paper → deny


async def _default_daily_loss_provider(market: str) -> float:
    """Today's realized loss as % of account value (≥0; 0 = no loss).

    kiwoom: 브로커의 당일 실현손익(ka10074)을 계좌 평가액(주식 평가 + D+2
    예수금) 대비 %로 환산한다 (Phase B2). 조회 실패·평가액 0은 예외로
    전파한다 — 게이트의 breaker 랩이 deny 처리하므로 fail-closed.

    kiwoom 외 시장은 범위 밖 — 0 반환(브레이커 비활성).
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


async def _default_held_tickers_provider(market: str) -> set:
    """The set of tickers occupying a position slot right now.

    Split out of `_default_positions_count_provider` (2026-08-05) so the slot
    count and the slot MEMBERSHIP come from one place: check 6 needs both —
    the count to enforce the cap, the membership to know whether a request
    would occupy a NEW slot at all.
    """
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

        return tickers
    raise ValueError(f"unknown market: {market}")


async def _default_positions_count_provider(market: str) -> int:
    return len(await _default_held_tickers_provider(market))


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
        return None  # kiwoom 외 시장은 범위 밖 (notional %상한 미적용)
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
    ticker: Optional[str] = None,
    mode_provider: Optional[Provider] = None,
    paper_provider: Optional[Provider] = None,
    daily_loss_provider: Optional[Provider] = None,
    positions_count_provider: Optional[Provider] = None,
    held_tickers_provider: Optional[Provider] = None,
    risk_params_provider: Optional[Callable[[], RiskParameters]] = None,
    coordinator_active_provider: Optional[Provider] = None,
    account_equity_provider: Optional[Provider] = None,
) -> GateDecision:
    """Decide whether an autonomous execution is allowed. Fail-closed.

    `ticker` (optional, 2026-08-05) is used by check 6 ONLY: when the request
    targets a ticker that already occupies a position slot, the
    max_open_positions cap does not apply, because buying more of something
    you already hold cannot raise the number of open positions. Omitting it
    keeps the pre-existing behaviour exactly (the cap applies unconditionally),
    so no existing call site changes meaning.

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
    held_tickers_provider = held_tickers_provider or _default_held_tickers_provider
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

        # 5. Coordinator must be active (kiwoom only; scoped here, not in the
        # provider, in case a caller ever swaps a market-specific default
        # in). See _default_coordinator_active_provider for why an
        # inactive/None coordinator must deny a BUY/ADD.
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

        # 6. Max concurrent positions.
        #
        # 이미 슬롯을 차지하고 있는 종목을 더 사는 요청은 이 상한의 대상이
        # 아니다 — 보유 종목 수는 **서로 다른 티커의 집합** 크기이고, 추가
        # 매수는 그 집합에 원소를 더하지 않는다.
        #
        # 라이브 사고(2026-08-05): 316140이 하루 동안 ADD를 7회 의결했는데
        # 전부 여기서 `open positions 5 >= limit 5`로 거절돼 체결 0건이었다.
        # 만석(5/5)이 이 시스템의 정상 상태이므로 자율 추가매수가 상시
        # 불가능했다. `PositionManager._execute_add_position`은 "진입 BUY와
        # 동일한 안전"을 의도해 이 게이트를 action="BUY"로 부르는데, 진입
        # BUY 의미에 포함된 슬롯 점검이 추가매수에는 무의미했던 것이다.
        #
        # 면제는 호출자의 주장이 아니라 **게이트가 직접 조회한 보유 목록**을
        # 근거로 한다(`held_tickers_provider`). 조회 실패는 다른 검사와 똑같이
        # fail-closed — 보유 여부를 모르면 상한을 그대로 적용하는 것이 아니라
        # 거절한다(모른 채로 상한을 적용하면 정상 추가매수가 막히고, 모른 채로
        # 면제하면 슬롯이 새기 때문에 어느 쪽도 안전하지 않다).
        #
        # ticker가 주어지면 소속과 개수를 **같은 스냅샷**에서 얻는다. 보유
        # 목록과 카운트를 따로 조회하면 그 사이에 체결이 끼어 "목록엔 없는데
        # 카운트는 4" 같은 어긋난 쌍으로 판정할 수 있고, 브로커 왕복도 두
        # 번이 된다. ticker가 없는 기존 호출부는 종전대로 카운트만 조회한다.
        exempt_from_slot_cap = False
        if ticker:
            try:
                held = await held_tickers_provider(market)
            except Exception as e:
                return _deny("max_positions", str(e))
            exempt_from_slot_cap = ticker in held
            count = len(held)
        else:
            try:
                count = int(await positions_count_provider(market))
            except Exception as e:
                return _deny("max_positions", str(e))

        if not exempt_from_slot_cap and count >= params.max_open_positions:
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
