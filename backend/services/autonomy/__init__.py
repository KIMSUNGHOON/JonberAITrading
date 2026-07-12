"""Autonomy gate package (R3) — the single policy point for autonomous execution."""

from services.autonomy.gate import GateDecision, check_autonomy

__all__ = ["GateDecision", "check_autonomy"]
