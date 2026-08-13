"""R-based position sizing cap — shared helper (S-4, 생존 규율).

Ties position size to how far the stop actually is, closing the sizing<->
stop-distance mismatch the two existing sizing sites had (spec
docs/superpowers/specs/2026-07-19-survival-discipline-design.md §1/§2 S-4):
never risk more than `risk_budget_pct`% of account equity on a single
trade's stop-loss distance.

    r_cap = equity * (risk_budget_pct / 100) / stop_distance_pct
    stop_distance_pct = (entry_price - stop_price) / entry_price

Both sizing sites — `portfolio_agent.PortfolioAgent._calculate_max_position_value`
and `agents.graph.kr_stock_nodes.decision_nodes.kr_stock_strategic_decision_node`
— call this SAME function and `min()` its result against their own existing
cap (the smaller of the two wins). This module is the single source of
truth for the R-cap math; callers own nothing but the plumbing and are
responsible for their own debug logging when the cap actually binds or a
guard suppresses it — this function stays a pure calculation with no side
effects.
"""

from __future__ import annotations

from typing import Optional

# Below this stop distance (as a fraction of entry price) the R math blows
# up toward a meaninglessly huge cap (near-divide-by-zero) — degrade to "no
# R cap" (None) instead of returning a number that would swamp every other
# limit and defeat the purpose of capping at all.
MIN_STOP_DISTANCE_PCT = 0.005  # 0.5%


def r_cap_value(
    equity: float,
    risk_budget_pct: float,
    entry_price: float,
    stop_price: Optional[float],
) -> Optional[float]:
    """R-based position-value cap, or None if the R rule doesn't apply here.

    Returns None (caller keeps its existing cap unmodified) when:
    - `stop_price` is None (no stop to size against)
    - `entry_price` <= 0 (degenerate/no price)
    - `stop_price` <= 0 (invalid/degenerate stop -- N4, spec docs/
      superpowers/specs/2026-07-20-gap-discipline-design.md §2 G-3: left
      unguarded, this computed a ~100% stop distance, collapsing the cap
      down to equity * risk_budget_pct% -- conservative in direction but
      an unintended, surprising value rather than "R rule doesn't apply")
    - `stop_price` >= `entry_price` (not a long-side risk-reducing stop)
    - the stop distance is under `MIN_STOP_DISTANCE_PCT` of entry (a
      near-zero risk distance would blow the cap up to an effectively
      unbounded value)
    """
    if stop_price is None:
        return None
    if entry_price <= 0:
        return None
    if stop_price <= 0:
        return None
    if stop_price >= entry_price:
        return None

    stop_distance_pct = (entry_price - stop_price) / entry_price
    if stop_distance_pct < MIN_STOP_DISTANCE_PCT:
        return None

    return equity * (risk_budget_pct / 100.0) / stop_distance_pct


# 유동성 캡이 계좌의 이 비율 미만으로 포지션을 밀어내면 진입 자체를 포기한다.
# 소액 포지션은 체결단위 미달 + 고정 수수료·호가단위 마찰로 실효 비용률이
# 오히려 올라간다.
SKIP_MIN_EQUITY_PCT = 0.01


def apply_liquidity_cap(
    base_cap: float,
    adtv: Optional[float],
    equity: float,
) -> tuple[float, Optional[str]]:
    """유동성 참여율 캡을 기존 캡에 결합한다.

    포지션은 일평균 거래대금의 `SIZING_PARTICIPATION_PCT`(0.5%)를 넘지 않는다 —
    한국 퀀트 실무 표준. 계좌 5억 기준 ADTV 40억이면 풀사이즈(2000만원), 20억이면
    1000만원으로 자동 축소된다.

    Returns (적용 캡, 사유):
    - `adtv`가 None이면 캡 미적용 + "adtv_unknown"(fail-open). 이미 발굴 A1
      게이트를 통과한 종목이고 R-cap·4% 캡이 여전히 작동하므로, 여기서
      fail-closed로 막으면 조회 실패가 곧 매매 정지가 된다.
    - `equity`가 0 이하면 skip-floor를 평가할 자본 베이스가 없다 → 캡 결합은
      그대로 하되 "skip_floor_disabled"를 반환한다(최종 리뷰 Blocking3).
      이전에는 `equity > 0` 선행 조건 때문에 skip-floor 분기가 조용히
      통과되어, 사유가 "liquidity_cap"/None으로만 보였다 — 방어선 하나가
      빠진 상태와 정상 동작이 로그에서 구분되지 않았다. `equity=0`은
      드문 사고가 아니라 확정 경로다(coordinator._state.account.total_equity
      기본값 0 → _refresh_account_info 전 구간).
    - 캡이 계좌의 1% 미만이면 0.0 + "liquidity_too_thin"(진입 포기).
    - 캡이 실제로 바인딩하면 "liquidity_cap", 아니면 None.
    """
    from services.discovery.liquidity import liquidity_cap_value

    liq_cap = liquidity_cap_value(adtv)
    if liq_cap is None:
        return base_cap, "adtv_unknown"

    if equity <= 0:
        # 캡 값 자체는 평소와 동일(둘 중 작은 쪽)하게 결합한다 — 안전 방향은
        # 유지하고, 사라진 건 skip-floor뿐임을 사유로 표면화한다.
        return min(liq_cap, base_cap), "skip_floor_disabled"

    if liq_cap < equity * SKIP_MIN_EQUITY_PCT:
        return 0.0, "liquidity_too_thin"

    if liq_cap < base_cap:
        return liq_cap, "liquidity_cap"

    return base_cap, None
