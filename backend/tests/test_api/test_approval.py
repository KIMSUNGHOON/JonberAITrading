"""
Approval API Endpoint Tests
"""

import pytest
from fastapi.testclient import TestClient


class TestApprovalEndpoints:
    """Tests for /api/approval endpoints."""

    def test_get_pending_invalid_session(self, client: TestClient):
        """Get pending proposal for invalid session should return 404."""
        response = client.get("/api/approval/pending/invalid-session-id")
        assert response.status_code == 404

    def test_decide_requires_fields(self, client: TestClient):
        """Decide endpoint should require all fields."""
        response = client.post(
            "/api/approval/decide",
            json={},
        )
        assert response.status_code == 422

    def test_decide_requires_session_id(self, client: TestClient):
        """Decide endpoint should require session_id."""
        response = client.post(
            "/api/approval/decide",
            json={
                "proposal_id": "test-proposal",
                "approved": True,
            },
        )
        assert response.status_code == 422

    def test_decide_requires_proposal_id(self, client: TestClient):
        """Decide endpoint should require proposal_id."""
        response = client.post(
            "/api/approval/decide",
            json={
                "session_id": "test-session",
                "approved": True,
            },
        )
        assert response.status_code == 422

    def test_decide_requires_approved(self, client: TestClient):
        """Decide endpoint should require approved field."""
        response = client.post(
            "/api/approval/decide",
            json={
                "session_id": "test-session",
                "proposal_id": "test-proposal",
            },
        )
        assert response.status_code == 422

    def test_decide_with_invalid_session(self, client: TestClient, mock_approval_request):
        """Decide with invalid session should return 404."""
        response = client.post(
            "/api/approval/decide",
            json=mock_approval_request,
        )
        assert response.status_code == 404

    def test_decide_accepts_feedback(self, client: TestClient):
        """Decide should accept optional feedback."""
        response = client.post(
            "/api/approval/decide",
            json={
                "session_id": "test-session",
                "proposal_id": "test-proposal",
                "approved": False,
                "feedback": "Risk is too high",
            },
        )
        # Should be 404 (session not found) not 422 (validation error)
        assert response.status_code == 404


class TestApprovalValidation:
    """Tests for approval input validation."""

    def test_approved_must_be_boolean(self, client: TestClient):
        """Approved field must be boolean."""
        response = client.post(
            "/api/approval/decide",
            json={
                "session_id": "test-session",
                "proposal_id": "test-proposal",
                "approved": "yes",  # Should be boolean
            },
        )
        assert response.status_code == 422

    def test_feedback_can_be_empty(self, client: TestClient):
        """Feedback field can be empty string."""
        response = client.post(
            "/api/approval/decide",
            json={
                "session_id": "test-session",
                "proposal_id": "test-proposal",
                "approved": True,
                "feedback": "",
            },
        )
        # Should be 404 (session not found) not 422 (validation error)
        assert response.status_code == 404
