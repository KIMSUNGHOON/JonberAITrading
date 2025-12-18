"""
Approval API Schemas

Pydantic models for HITL approval request/response validation.
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# -------------------------------------------
# Request Schemas
# -------------------------------------------


class ApprovalRequest(BaseModel):
    """Request to submit approval decision."""

    session_id: str = Field(
        ...,
        description="Session ID of the pending approval",
    )
    decision: Literal["approved", "rejected", "modified"] = Field(
        ...,
        description="Approval decision",
    )
    feedback: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional feedback or notes",
    )
    modifications: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional modifications to the trade proposal",
    )


class ModificationRequest(BaseModel):
    """Specific modifications to a trade proposal."""

    quantity: Optional[int] = Field(default=None, ge=1)
    stop_loss: Optional[float] = Field(default=None, ge=0)
    take_profit: Optional[float] = Field(default=None, ge=0)


# -------------------------------------------
# Response Schemas
# -------------------------------------------


class ApprovalResponse(BaseModel):
    """Response after approval decision."""

    session_id: str
    decision: str
    status: str
    message: str
    execution_status: Optional[str] = None


class PendingProposalSummary(BaseModel):
    """Summary of analyses for a pending proposal."""

    technical: Optional[str] = None
    fundamental: Optional[str] = None
    sentiment: Optional[str] = None
    risk: Optional[str] = None


class PendingApprovalItem(BaseModel):
    """A single pending approval item."""

    session_id: str
    ticker: str
    action: str
    quantity: int
    risk_score: float
    rationale_preview: str = Field(description="First 200 chars of rationale")
    analyses_summary: PendingProposalSummary
    created_at: datetime


class PendingApprovalsResponse(BaseModel):
    """List of pending approvals."""

    pending_approvals: list[PendingApprovalItem]
    total: int
