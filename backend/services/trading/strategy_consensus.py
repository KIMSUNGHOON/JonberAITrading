"""Phase 3: strategy-level consensus math — PURE functions, NO LLM.

The EOD strategy panel (strategy_panel.py) produces structured votes; this
module turns them into (a) a stance consensus and (b) a deterministically
adjusted TradingStrategy. Three known agent-chat defects are corrected here
by design, not inherited:

- single-vote=100% consensus (agent_chat/models.py:319-325): a `min_valid`
  gate (default 2 of 3 panelists) returns "no_change" instead.
- free-text substring action parsing (moderator_agent._parse_action): votes
  are schema-validated dicts; anything without a recognized stance is simply
  not a valid vote.
- swallowed-error strings becoming data (base_agent._call_llm): error
  entries ({"panelist", "error"}) are excluded from the electorate.

Numeric knob updates are deterministic: median of panelist suggestions ->
hard safety bounds (module constants, intentionally narrower than the
Pydantic field ranges) -> per-run relative delta cap, so one EOD run can
never lurch the strategy. The LLM only ever *suggests*.
"""

from __future__ import annotations

import statistics
from typing import Any, Optional

from .strategy import RiskTolerance, StrategyPreset, TradingStrategy

STANCES = ("aggressive", "neutral", "defensive")

# Hard safety rails per adjustable knob — (lo, hi), all inside the Pydantic
# field ranges (strategy.py:52-98) but narrower on purpose: these bound what
# EOD consensus may ever set, independent of what a user may set manually.
KNOB_BOUNDS: dict[str, tuple[float, float]] = {
    "max_position_pct": (0.02, 0.30),   # PositionSizingRules (0.01-0.50)
    "min_cash_ratio": (0.05, 0.50),     # PositionSizingRules (0.0-0.90)
    "max_positions": (1, 15),           # PositionSizingRules (1-50), int
    "stop_loss_pct": (0.03, 0.15),      # ExitConditions (0.01-0.50), 소수분율
    "take_profit_pct": (0.05, 0.30),    # ExitConditions (0.01-1.0), 소수분율
    # PositionSizingRules (0.5-50.0), 퍼센트 단위(소수분율 아님) — 위 5개와
    # 달리 ×100/÷100 변환 없이 그대로 클램프한다 (Phase5 결정B, strategy_apply.py
    # STRATEGY_MAPPED_FIELDS와 동일 [5,30] 바운드로 정합).
    "max_trade_notional_pct": (5.0, 30.0),
    # EntryConditions (0.5-0.9) — E-3(진입 활성화): 4-에이전트 합의 문턱을
    # EOD 전략 합의가 조정할 수 있는 안전 레일. 위 소수분율 노브들과 같은
    # 단위(0.0-1.0)라 변환 없이 그대로 클램프한다.
    "consensus_threshold": (0.60, 0.85),
    # 변동성 타게팅 (2026-08-07). PositionSizingRules (10.0-40.0), 퍼센트
    # 단위 — max_trade_notional_pct와 같은 계열로 변환 없이 그대로 클램프한다.
    # strategy_apply.py STRATEGY_MAPPED_FIELDS와 동일 [10,40] 바운드로 정합
    # (두 곳이 어긋나면 이중 클램프가 되어 추적이 어려워진다).
    "target_vol_pct": (10.0, 40.0),
    # PositionSizingRules (0.2-0.8), 분율 — consensus_threshold와 같은 계열로
    # 변환 없이 그대로 클램프한다. strategy_apply.py STRATEGY_MAPPED_FIELDS와
    # 동일 [0.2,0.8] 바운드로 정합. 상한이 0.8인 이유는 1.0을 허용하면 전략이
    # 변동성 방어를 통째로 끌 수 있기 때문 — 절대 1.0으로 올리지 않는다.
    "vol_multiplier_min": (0.2, 0.8),
}

_INT_KNOBS = {"max_positions"}


def clamp_knob(knob: str, value: float) -> float:
    """Clamp a raw (fractional-unit) knob value into its KNOB_BOUNDS hard
    rail. Single source for the safety bounds — reused outside this module
    by the tactical consumption paths (agent_chat coordinator's strategy
    context, KR graph decision nodes' `_strategy_stop_params`) so a manual
    PUT /strategy edit (which bypasses `apply_consensus`'s `_bounded`
    clamp) can't diverge into different numbers across consumers of the
    same live TradingStrategy (final-review Fix2, Phase4)."""
    lo, hi = KNOB_BOUNDS[knob]
    return max(lo, min(hi, value))

# One EOD run may move a knob at most this relative fraction from its
# current value — bounded adaptation (25%/run).
MAX_RELATIVE_DELTA = 0.25

_STANCE_TO_TOLERANCE = {
    "aggressive": RiskTolerance.AGGRESSIVE,
    "neutral": RiskTolerance.MODERATE,
    "defensive": RiskTolerance.CONSERVATIVE,
}

# Structured output contract for each panelist (generate_structured enforces
# top-level `required`; adjustments are optional suggestions).
STRATEGY_VOTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "stance": {"type": "string", "enum": list(STANCES)},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "key_factors": {"type": "array", "items": {"type": "string"}},
        "adjustments": {
            "type": "object",
            "properties": {
                "max_position_pct": {"type": ["number", "null"]},
                "min_cash_ratio": {"type": ["number", "null"]},
                "max_positions": {"type": ["integer", "null"]},
                "stop_loss_pct": {"type": ["number", "null"]},
                "take_profit_pct": {"type": ["number", "null"]},
                "max_trade_notional_pct": {"type": ["number", "null"]},
                "consensus_threshold": {"type": ["number", "null"]},
                "target_vol_pct": {"type": ["number", "null"]},
                "vol_multiplier_min": {"type": ["number", "null"]},
            },
        },
    },
    "required": ["stance", "confidence", "reasoning"],
}


def valid_votes(votes: list[dict]) -> list[dict]:
    """Votes that actually elect: no error entries, recognized stance."""
    return [
        v for v in votes
        if isinstance(v, dict) and not v.get("error") and v.get("stance") in STANCES
    ]


def _clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def aggregate_stance(votes: list[dict], *, min_valid: int, threshold: float) -> dict:
    """Weighted stance consensus over the valid electorate.

    Returns {"stance", "consensus_level", "valid_votes"}; stance is one of
    STANCES, or "no_change" when the electorate is too small (< min_valid),
    the dominant share is below `threshold`, or the top buckets tie.
    """
    electorate = valid_votes(votes)
    result = {"stance": "no_change", "consensus_level": 0.0, "valid_votes": len(electorate)}
    if len(electorate) < min_valid:
        return result

    buckets = {stance: 0.0 for stance in STANCES}
    for vote in electorate:
        buckets[vote["stance"]] += _clamp01(vote.get("confidence"))

    total = sum(buckets.values())
    if total <= 0.0:
        return result

    top_mass = max(buckets.values())
    winners = [s for s, mass in buckets.items() if mass == top_mass]
    result["consensus_level"] = top_mass / total
    if len(winners) != 1 or result["consensus_level"] < threshold:
        return result

    result["stance"] = winners[0]
    return result


def semantic_fingerprint(strategy: TradingStrategy) -> tuple:
    """The comparison key for `changed` detection — the fields EOD consensus
    can move (identity/timestamps excluded on purpose)."""
    return (
        strategy.risk_tolerance.value,
        strategy.position_sizing.max_position_pct,
        strategy.position_sizing.min_cash_ratio,
        strategy.position_sizing.max_positions,
        strategy.exit_conditions.stop_loss_pct,
        strategy.exit_conditions.take_profit_pct,
        strategy.position_sizing.max_trade_notional_pct,
        strategy.entry_conditions.consensus_threshold,
        strategy.position_sizing.target_vol_pct,
        strategy.position_sizing.vol_multiplier_min,
    )


def _aggregate_knob(votes: list[dict], knob: str) -> Optional[float]:
    """Median of the numeric suggestions for `knob`, or None if nobody
    (validly) suggested it. Non-numeric suggestions are ignored, booleans
    are rejected (bool is an int subclass)."""
    suggestions = []
    for vote in votes:
        adjustments = vote.get("adjustments")
        if not isinstance(adjustments, dict):
            continue
        raw = adjustments.get(knob)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            suggestions.append(float(raw))
    if not suggestions:
        return None
    return statistics.median(suggestions)


def _bounded(knob: str, target: float, current: float) -> float:
    """Hard bounds first, then the per-run relative delta cap around the
    current value (delta window itself re-clamped into bounds)."""
    lo, hi = KNOB_BOUNDS[knob]
    target = max(lo, min(hi, target))
    delta_lo = current * (1 - MAX_RELATIVE_DELTA)
    delta_hi = current * (1 + MAX_RELATIVE_DELTA)
    return max(lo, min(hi, max(delta_lo, min(delta_hi, target))))


def apply_consensus(
    current: TradingStrategy,
    votes: list[dict],
    stance: str,
    consensus_level: float,
    trade_date: str,
    revision_id: str,
) -> TradingStrategy:
    """Deterministically build the adapted strategy. `current` is never
    mutated; the returned copy carries the revision id + provenance stamp."""
    strategy = current.model_copy(deep=True)
    electorate = valid_votes(votes)

    strategy.risk_tolerance = _STANCE_TO_TOLERANCE.get(stance, strategy.risk_tolerance)

    sizing, exits, entry = (
        strategy.position_sizing, strategy.exit_conditions, strategy.entry_conditions
    )
    knob_targets = {
        "max_position_pct": (sizing, "max_position_pct"),
        "min_cash_ratio": (sizing, "min_cash_ratio"),
        "max_positions": (sizing, "max_positions"),
        "stop_loss_pct": (exits, "stop_loss_pct"),
        "take_profit_pct": (exits, "take_profit_pct"),
        "max_trade_notional_pct": (sizing, "max_trade_notional_pct"),
        "consensus_threshold": (entry, "consensus_threshold"),
        "target_vol_pct": (sizing, "target_vol_pct"),
        "vol_multiplier_min": (sizing, "vol_multiplier_min"),
    }
    for knob, (owner, attr) in knob_targets.items():
        target = _aggregate_knob(electorate, knob)
        if target is None:
            continue
        new_value = _bounded(knob, target, float(getattr(owner, attr)))
        if knob in _INT_KNOBS:
            new_value = int(round(new_value))
        setattr(owner, attr, new_value)

    from datetime import datetime  # local: strategy.py도 datetime.now 사용

    strategy.id = revision_id
    strategy.preset = StrategyPreset.CUSTOM
    strategy.updated_at = datetime.now()
    strategy.description = (
        f"EOD 전략 합의 {trade_date}: {stance} (합의 {consensus_level:.2f})"
    )
    if current.name == "My Strategy":
        strategy.name = "EOD 적응형 전략"
    return strategy
