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
