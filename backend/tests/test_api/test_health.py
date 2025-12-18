"""
Health Check Endpoint Tests
"""

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_200(self, client: TestClient):
        """Health endpoint should return 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_status(self, client: TestClient):
        """Health endpoint should return status field."""
        response = client.get("/health")
        data = response.json()

        assert "status" in data
        assert data["status"] in ["healthy", "degraded", "unhealthy"]

    def test_health_returns_services(self, client: TestClient):
        """Health endpoint should return services status."""
        response = client.get("/health")
        data = response.json()

        assert "services" in data
        assert "api" in data["services"]
        assert data["services"]["api"] == "healthy"

    def test_health_returns_environment(self, client: TestClient):
        """Health endpoint should return environment info."""
        response = client.get("/health")
        data = response.json()

        assert "environment" in data


class TestRootEndpoint:
    """Tests for / root endpoint."""

    def test_root_returns_200(self, client: TestClient):
        """Root endpoint should return 200 OK."""
        response = client.get("/")
        assert response.status_code == 200

    def test_root_returns_api_info(self, client: TestClient):
        """Root endpoint should return API information."""
        response = client.get("/")
        data = response.json()

        assert "name" in data
        assert "version" in data
        assert "health" in data

    def test_root_contains_correct_version(self, client: TestClient):
        """Root endpoint should contain correct version."""
        response = client.get("/")
        data = response.json()

        assert data["version"] == "1.0.0"
