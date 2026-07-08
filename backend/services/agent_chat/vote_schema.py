"""Structured-vote JSON schemas for the group-chat agents (Phase 3 follow-on).

VoteType values are lowercase, so the enum + the caller's mapping use lowercase.
"""

VOTE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "vote": {
            "type": "string",
            "enum": ["strong_buy", "buy", "hold", "sell", "strong_sell", "abstain"],
        },
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "key_factors": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["vote", "confidence"],
}

RISK_VOTE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        **VOTE_SCHEMA["properties"],
        "suggested_position_pct": {"type": "number"},
        "suggested_stop_loss_pct": {"type": "number"},
        "suggested_take_profit_pct": {"type": "number"},
    },
    "required": ["vote", "confidence"],
}
