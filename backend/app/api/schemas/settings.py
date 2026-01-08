"""
Settings API Schemas

Pydantic models for settings-related API operations.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UpbitApiKeyRequest(BaseModel):
    """Request to update Upbit API keys."""

    access_key: str = Field(..., min_length=1, description="Upbit Access Key")
    secret_key: str = Field(..., min_length=1, description="Upbit Secret Key")


class UpbitApiKeyStatus(BaseModel):
    """Status of Upbit API key configuration."""

    is_configured: bool = Field(description="Whether API keys are configured")
    access_key_masked: Optional[str] = Field(
        default=None, description="Masked access key (first 4 chars + ****)"
    )
    trading_mode: str = Field(default="paper", description="Trading mode: paper or live")
    is_valid: Optional[bool] = Field(
        default=None, description="Whether API keys are valid (checked via API)"
    )
    last_validated: Optional[datetime] = Field(
        default=None, description="Last validation timestamp"
    )


class UpbitApiKeyResponse(BaseModel):
    """Response after updating Upbit API keys."""

    success: bool
    message: str
    status: UpbitApiKeyStatus


class UpbitValidateResponse(BaseModel):
    """Response after validating Upbit API keys."""

    is_valid: bool
    message: str
    account_count: Optional[int] = Field(
        default=None, description="Number of accounts (if valid)"
    )


class SettingsResponse(BaseModel):
    """Full settings response."""

    upbit: UpbitApiKeyStatus
    llm_provider: str
    llm_model: str
    market_data_mode: str
