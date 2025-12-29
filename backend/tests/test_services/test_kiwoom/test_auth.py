"""
Kiwoom Auth Unit Tests

Tests for OAuth2 token management with mocked HTTP responses.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from services.kiwoom.auth import KiwoomAuth
from services.kiwoom.errors import KiwoomAuthError, KiwoomNetworkError
from services.kiwoom.models import KiwoomToken


class TestKiwoomAuth:
    """KiwoomAuth unit tests"""

    @pytest.fixture
    def auth(self):
        """Create KiwoomAuth instance"""
        return KiwoomAuth(
            base_url="https://mockapi.kiwoom.com",
            app_key="test_app_key",
            secret_key="test_secret_key"
        )

    @pytest.mark.asyncio
    async def test_auth_initialization(self, auth):
        """Test auth initialization"""
        assert auth.base_url == "https://mockapi.kiwoom.com"
        assert auth.app_key == "test_app_key"
        assert auth.secret_key == "test_secret_key"
        assert auth._token is None

    @pytest.mark.asyncio
    async def test_should_refresh_when_no_token(self, auth):
        """Test should_refresh returns True when no token"""
        assert auth._should_refresh() is True

    @pytest.mark.asyncio
    async def test_should_refresh_when_near_expiry(self, auth):
        """Test should_refresh returns True when token is near expiry"""
        # Token expires in 2 minutes (less than 5 min margin)
        auth._token = KiwoomToken(
            token="test_token",
            expires_dt=datetime.now() + timedelta(minutes=2)
        )
        assert auth._should_refresh() is True

    @pytest.mark.asyncio
    async def test_should_not_refresh_when_valid(self, auth):
        """Test should_refresh returns False when token is valid"""
        # Token expires in 1 hour
        auth._token = KiwoomToken(
            token="test_token",
            expires_dt=datetime.now() + timedelta(hours=1)
        )
        assert auth._should_refresh() is False

    @pytest.mark.asyncio
    async def test_has_valid_token_false_when_none(self, auth):
        """Test has_valid_token returns False when no token"""
        assert auth.has_valid_token is False

    @pytest.mark.asyncio
    async def test_has_valid_token_true_when_valid(self, auth):
        """Test has_valid_token returns True when token is valid"""
        auth._token = KiwoomToken(
            token="test_token",
            expires_dt=datetime.now() + timedelta(hours=1)
        )
        assert auth.has_valid_token is True

    @pytest.mark.asyncio
    async def test_token_expires_at(self, auth):
        """Test token_expires_at property"""
        expires = datetime.now() + timedelta(hours=1)
        auth._token = KiwoomToken(token="test_token", expires_dt=expires)
        assert auth.token_expires_at == expires

    @pytest.mark.asyncio
    async def test_token_expires_at_none(self, auth):
        """Test token_expires_at returns None when no token"""
        assert auth.token_expires_at is None

    @pytest.mark.asyncio
    async def test_issue_token_success(self, auth):
        """Test successful token issuance"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "return_code": 0,
            "token": "new_test_token",
            "token_type": "Bearer",
            "expires_dt": (datetime.now() + timedelta(hours=24)).strftime("%Y%m%d%H%M%S")
        }

        with patch.object(auth, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            await auth._issue_token()

            assert auth._token is not None
            assert auth._token.token == "new_test_token"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_issue_token_error_response(self, auth):
        """Test token issuance with error response"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "return_code": -1,
            "return_msg": "Invalid credentials"
        }

        with patch.object(auth, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            with pytest.raises(KiwoomAuthError) as exc_info:
                await auth._issue_token()

            assert exc_info.value.code == -1

    @pytest.mark.asyncio
    async def test_issue_token_no_token_in_response(self, auth):
        """Test token issuance when response has no token"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "return_code": 0,
            # Missing 'token' field
        }

        with patch.object(auth, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            with pytest.raises(KiwoomAuthError):
                await auth._issue_token()

    @pytest.mark.asyncio
    async def test_issue_token_network_error(self, auth):
        """Test token issuance with network error"""
        with patch.object(auth, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.HTTPError("Connection failed")
            mock_get_client.return_value = mock_client

            with pytest.raises(KiwoomNetworkError):
                await auth._issue_token()

    @pytest.mark.asyncio
    async def test_get_token_issues_new_when_none(self, auth):
        """Test get_token issues new token when none exists"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "return_code": 0,
            "token": "new_token",
            "token_type": "Bearer",
            "expires_dt": (datetime.now() + timedelta(hours=24)).strftime("%Y%m%d%H%M%S")
        }

        with patch.object(auth, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            token = await auth.get_token()

            assert token == "new_token"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_token_returns_cached(self, auth):
        """Test get_token returns cached token when valid"""
        # Set up a valid cached token
        auth._token = KiwoomToken(
            token="cached_token",
            expires_dt=datetime.now() + timedelta(hours=1)
        )

        with patch.object(auth, '_issue_token') as mock_issue:
            token = await auth.get_token()

            assert token == "cached_token"
            mock_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke_token_success(self, auth):
        """Test successful token revocation"""
        auth._token = KiwoomToken(
            token="token_to_revoke",
            expires_dt=datetime.now() + timedelta(hours=1)
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "return_code": 0,
            "return_msg": "Token revoked"
        }

        with patch.object(auth, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            await auth.revoke_token()

            assert auth._token is None

    @pytest.mark.asyncio
    async def test_revoke_token_no_token(self, auth):
        """Test revoke_token does nothing when no token"""
        with patch.object(auth, '_get_client') as mock_get_client:
            await auth.revoke_token()
            mock_get_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_close(self, auth):
        """Test close cleans up resources"""
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()
        auth._client = mock_client
        await auth.close()
        mock_client.aclose.assert_called_once()
        assert auth._client is None

    @pytest.mark.asyncio
    async def test_close_no_client(self, auth):
        """Test close when no client exists"""
        await auth.close()  # Should not raise
        assert auth._client is None


class TestKiwoomAuthExpireParsing:
    """Test token expiration date parsing"""

    @pytest.fixture
    def auth(self):
        return KiwoomAuth(
            base_url="https://mockapi.kiwoom.com",
            app_key="test_app_key",
            secret_key="test_secret_key"
        )

    @pytest.mark.asyncio
    async def test_parse_expires_dt_yyyymmddhhmmss(self, auth):
        """Test parsing YYYYMMDDHHMMSS format"""
        expires_str = "20241225120000"
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "return_code": 0,
            "token": "test_token",
            "expires_dt": expires_str
        }

        with patch.object(auth, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            await auth._issue_token()

            assert auth._token is not None
            assert auth._token.expires_dt.year == 2024
            assert auth._token.expires_dt.month == 12
            assert auth._token.expires_dt.day == 25

    @pytest.mark.asyncio
    async def test_parse_expires_dt_iso_format(self, auth):
        """Test parsing ISO format"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "return_code": 0,
            "token": "test_token",
            "expires_dt": "2024-12-25T12:00:00"
        }

        with patch.object(auth, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            await auth._issue_token()

            assert auth._token is not None
            assert auth._token.expires_dt.year == 2024

    @pytest.mark.asyncio
    async def test_parse_expires_dt_fallback(self, auth):
        """Test fallback to 24 hours when format is unknown"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "return_code": 0,
            "token": "test_token",
            "expires_dt": "invalid_format"
        }

        with patch.object(auth, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            await auth._issue_token()

            assert auth._token is not None
            # Token should be valid (fallback to 24 hours)
            assert auth._token.expires_dt > datetime.now()