"""
Settings API Schemas

Pydantic models for settings-related API operations.
"""

from pydantic import BaseModel


class SettingsResponse(BaseModel):
    """Full settings response."""

    llm_provider: str
    llm_model: str
    market_data_mode: str
