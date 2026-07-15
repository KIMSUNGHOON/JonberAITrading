"""Phase 4: strategy -> RiskParameters mapping — the single-source-of-truth
unification of the duplicated sizing knobs (PositionSizingRules vs
RiskParameters).

RiskParameters is the runtime truth every consumer already reads
(PortfolioAgent sizing, RiskMonitor, reconciler's default-stop fallback);
TradingStrategy is the strategy-facing surface Phase 3's EOD consensus
adapts. This module maps the strategy INTO the shared RiskParameters object
IN-PLACE (the object is reference-shared with PortfolioAgent/RiskMonitor/
TradingState from coordinator.__init__ — rebinding would silently orphan
them, the exact POST /trading/start bug this phase also fixes).

SELF-DEREGULATION SEAL — the reason this is an explicit allowlist, not a
dict walk: RiskParameters also carries the autonomy gate's hard caps
(max_trade_notional_krw, max_open_positions, max_daily_loss_pct — the ONLY
three fields gate.py reads) plus the breaker/mode knobs. An LLM-adapted
strategy must never be able to move those, so:
  - STRATEGY_MAPPED_FIELDS enumerates the only 4 assignable fields, each
    with its own hard bounds (KNOB_BOUNDS-equivalent — the manual
    PUT /strategy path bypasses Phase 3's consensus clamps, so the mapping
    clamps independently);
  - GATE_PROTECTED_FIELDS is the tested denylist — see
    test_gate_protected_fields_never_move.

Field priority: the 4 mapped fields become strategy-owned. A manual
PUT /risk-params edit of them survives only until the next set_strategy
(EOD consensus / restart restore) — intended: the strategy is their SSOT.
Clearing the strategy (set_strategy(None)) resets them to model defaults.
"""

from __future__ import annotations

from typing import Optional

from .models import RiskParameters
from .strategy import TradingStrategy

# risk_params 필드명 -> (lo, hi) 매핑 바운드. 값 출처는 아래 _source_values.
# 단위: max_single_position_pct/min_cash_ratio는 소수분율,
#       default_*_pct는 퍼센트(전략 분율 ×100 후 클램프).
STRATEGY_MAPPED_FIELDS: dict[str, tuple[float, float]] = {
    "max_single_position_pct": (0.02, 0.30),
    "min_cash_ratio": (0.05, 0.50),
    "default_stop_loss_pct": (3.0, 15.0),
    "default_take_profit_pct": (5.0, 30.0),
}

# 자율 게이트·브레이커·모드 필드 — 전략이 절대 못 움직인다(테스트로 봉인).
GATE_PROTECTED_FIELDS: frozenset[str] = frozenset({
    "max_daily_loss_pct",
    "max_open_positions",
    "max_trade_notional_krw",
    "stop_loss_mode",
    "take_profit_mode",
    "sudden_move_threshold_pct",
    "sudden_move_cooldown_ticks",
    "sudden_move_stabilization_pct",
    "max_daily_trades",
})


def _source_values(strategy: TradingStrategy) -> dict[str, float]:
    """전략에서 매핑 원천값 추출 (단위 변환 포함)."""
    return {
        "max_single_position_pct": strategy.position_sizing.max_position_pct,
        "min_cash_ratio": strategy.position_sizing.min_cash_ratio,
        "default_stop_loss_pct": strategy.exit_conditions.stop_loss_pct * 100.0,
        "default_take_profit_pct": strategy.exit_conditions.take_profit_pct * 100.0,
    }


def apply_strategy_to_risk_params(
    strategy: Optional[TradingStrategy], risk_params: RiskParameters
) -> dict[str, tuple]:
    """Map the strategy's sizing/stop knobs into the shared RiskParameters
    IN-PLACE. Returns {field: (before, after)} for fields that actually
    changed (for the STRATEGY_CHANGED activity log). strategy=None resets
    the mapped fields to model defaults ("no strategy = factory defaults").
    The reset branch reports all 4 fields unconditionally (before may equal
    after) — see the "deterministic, all-4-fields event" note above.
    """
    if strategy is None:
        # Reset is a deterministic, all-4-fields event for logging purposes
        # (STRATEGY_CHANGED "cleared" detail) even if a given field's value
        # happens to coincide with the model default already (e.g. a
        # strategy that never overrode min_cash_ratio) — unlike the
        # strategy-apply branch below, a no-op reset is still reported.
        targets = {
            field: RiskParameters.model_fields[field].default
            for field in STRATEGY_MAPPED_FIELDS
        }
        changes: dict[str, tuple] = {}
        for field, target in targets.items():
            before = getattr(risk_params, field)
            setattr(risk_params, field, target)
            changes[field] = (before, target)
        return changes

    sources = _source_values(strategy)
    targets = {
        field: max(lo, min(hi, sources[field]))
        for field, (lo, hi) in STRATEGY_MAPPED_FIELDS.items()
    }

    changes = {}
    for field, target in targets.items():
        before = getattr(risk_params, field)
        if before != target:
            setattr(risk_params, field, target)
            changes[field] = (before, target)
    return changes
