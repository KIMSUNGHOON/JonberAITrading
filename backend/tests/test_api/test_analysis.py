"""
Analysis API Endpoint Tests
"""

import pytest
from fastapi.testclient import TestClient


class TestAnalysisEndpoints:
    """Tests for /api/analysis endpoints."""

    def test_start_analysis_requires_ticker(self, client: TestClient):
        """Start analysis should require ticker field."""
        response = client.post(
            "/api/analysis/start",
            json={},
        )
        # Should return 422 Unprocessable Entity for missing required field
        assert response.status_code == 422

    def test_start_analysis_with_valid_ticker(self, client: TestClient, mock_analysis_request):
        """Start analysis should accept valid ticker."""
        response = client.post(
            "/api/analysis/start",
            json=mock_analysis_request,
        )
        # Either 200 (success) or 503 (if LLM not available)
        assert response.status_code in [200, 503]

    def test_start_analysis_returns_session_id(self, client: TestClient, mock_analysis_request):
        """Start analysis should return session_id."""
        response = client.post(
            "/api/analysis/start",
            json=mock_analysis_request,
        )

        if response.status_code == 200:
            data = response.json()
            assert "session_id" in data
            assert isinstance(data["session_id"], str)

    def test_get_status_invalid_session(self, client: TestClient):
        """Get status for invalid session should return 404."""
        response = client.get("/api/analysis/status/invalid-session-id")
        assert response.status_code == 404

    def test_list_sessions(self, client: TestClient):
        """List sessions should return array."""
        response = client.get("/api/analysis/sessions")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)

    def test_cancel_invalid_session(self, client: TestClient):
        """Cancel invalid session should return 404."""
        response = client.post("/api/analysis/cancel/invalid-session-id")
        assert response.status_code == 404


class TestAnalysisValidation:
    """Tests for analysis input validation."""

    def test_ticker_uppercase(self, client: TestClient):
        """Ticker should be case insensitive."""
        response = client.post(
            "/api/analysis/start",
            json={"ticker": "aapl"},
        )
        # Should accept lowercase ticker
        assert response.status_code in [200, 503]

    def test_ticker_max_length(self, client: TestClient):
        """Ticker should have maximum length."""
        response = client.post(
            "/api/analysis/start",
            json={"ticker": "TOOLONGTICKER123"},
        )
        # Should reject overly long ticker
        assert response.status_code in [422, 400]

    def test_empty_ticker_rejected(self, client: TestClient):
        """Empty ticker should be rejected."""
        response = client.post(
            "/api/analysis/start",
            json={"ticker": ""},
        )
        assert response.status_code == 422
