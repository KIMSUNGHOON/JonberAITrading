"""
Kiwoom Errors Unit Tests

Tests for error handling and error codes.
"""

import pytest

from services.kiwoom.errors import (
    KiwoomAuthError,
    KiwoomError,
    KiwoomErrorCode,
    KiwoomNetworkError,
    KiwoomOrderError,
    KiwoomRateLimitError,
)


class TestKiwoomErrorCode:
    """KiwoomErrorCode class tests"""

    def test_success_code(self):
        assert KiwoomErrorCode.SUCCESS == 0

    def test_token_expired(self):
        assert KiwoomErrorCode.TOKEN_EXPIRED == -100

    def test_invalid_token(self):
        assert KiwoomErrorCode.INVALID_TOKEN == -103

    def test_token_not_found(self):
        assert KiwoomErrorCode.TOKEN_NOT_FOUND == -104

    def test_rate_limit_exceeded(self):
        assert KiwoomErrorCode.RATE_LIMIT_EXCEEDED == -903

    def test_network_error(self):
        assert KiwoomErrorCode.NETWORK_ERROR == -901

    def test_invalid_stock_code(self):
        assert KiwoomErrorCode.INVALID_STOCK_CODE == -200

    def test_insufficient_balance(self):
        assert KiwoomErrorCode.INSUFFICIENT_BALANCE == -400


class TestKiwoomError:
    """KiwoomError tests"""

    def test_error_creation(self):
        error = KiwoomError(code=-1, message="Test error")
        assert error.code == -1
        assert error.message == "Test error"

    def test_error_str(self):
        error = KiwoomError(code=-1, message="Test error")
        assert "[-1]" in str(error)
        assert "Test error" in str(error)

    def test_error_with_api_id(self):
        error = KiwoomError(code=-1, message="Test error", api_id="ka10001")
        assert error.api_id == "ka10001"
        assert "[ka10001]" in str(error)

    def test_error_default_message(self):
        error = KiwoomError(code=KiwoomErrorCode.TOKEN_EXPIRED)
        assert "만료" in error.message  # "접근토큰이 만료되었습니다"

    def test_error_unknown_code_default_message(self):
        error = KiwoomError(code=-9999)
        assert error.message == "알 수 없는 오류"

    def test_from_response(self):
        response = {
            "return_code": -1,
            "return_msg": "Invalid parameter"
        }
        error = KiwoomError.from_response(response, api_id="ka10001")
        assert error.code == -1
        assert error.message == "Invalid parameter"
        assert error.api_id == "ka10001"

    def test_from_response_string_code(self):
        response = {
            "return_code": "-1",
            "return_msg": "Invalid parameter"
        }
        error = KiwoomError.from_response(response)
        assert error.code == -1

    def test_from_response_default_message(self):
        response = {
            "return_code": -1
        }
        error = KiwoomError.from_response(response)
        # When message is None, it uses the error message mapping

    def test_is_retryable_token_expired(self):
        error = KiwoomError(code=KiwoomErrorCode.TOKEN_EXPIRED)
        assert error.is_retryable is True

    def test_is_retryable_network_error(self):
        error = KiwoomError(code=KiwoomErrorCode.NETWORK_ERROR)
        assert error.is_retryable is True

    def test_is_retryable_rate_limit(self):
        error = KiwoomError(code=KiwoomErrorCode.RATE_LIMIT_EXCEEDED)
        assert error.is_retryable is True

    def test_is_not_retryable(self):
        error = KiwoomError(code=KiwoomErrorCode.INVALID_STOCK_CODE)
        assert error.is_retryable is False

    def test_is_auth_error_true(self):
        error = KiwoomError(code=KiwoomErrorCode.TOKEN_EXPIRED)
        assert error.is_auth_error is True

    def test_is_auth_error_false(self):
        error = KiwoomError(code=KiwoomErrorCode.NETWORK_ERROR)
        assert error.is_auth_error is False

    def test_is_order_error_true(self):
        error = KiwoomError(code=KiwoomErrorCode.INVALID_ORDER_QTY)
        assert error.is_order_error is True

    def test_is_order_error_false(self):
        error = KiwoomError(code=KiwoomErrorCode.TOKEN_EXPIRED)
        assert error.is_order_error is False


class TestKiwoomAuthError:
    """KiwoomAuthError tests"""

    def test_auth_error_creation(self):
        error = KiwoomAuthError(code=KiwoomErrorCode.TOKEN_NOT_FOUND, message="Token not found")
        assert error.code == KiwoomErrorCode.TOKEN_NOT_FOUND
        assert isinstance(error, KiwoomError)

    def test_auth_error_default_code(self):
        error = KiwoomAuthError()
        assert error.code == KiwoomErrorCode.INVALID_TOKEN


class TestKiwoomOrderError:
    """KiwoomOrderError tests"""

    def test_order_error_creation(self):
        error = KiwoomOrderError(
            code=KiwoomErrorCode.INVALID_ORDER_QTY,
            message="Invalid quantity",
            order_no="12345"
        )
        assert error.code == KiwoomErrorCode.INVALID_ORDER_QTY
        assert error.order_no == "12345"
        assert isinstance(error, KiwoomError)


class TestKiwoomNetworkError:
    """KiwoomNetworkError tests"""

    def test_network_error_creation(self):
        original = ConnectionError("Connection refused")
        error = KiwoomNetworkError(
            message="Network error occurred",
            original_error=original
        )
        assert error.message == "Network error occurred"
        assert error.original_error == original
        assert error.code == KiwoomErrorCode.NETWORK_ERROR

    def test_network_error_str(self):
        error = KiwoomNetworkError(message="Connection timeout")
        assert "Connection timeout" in str(error)

    def test_network_error_without_original(self):
        error = KiwoomNetworkError(message="Connection timeout")
        assert error.original_error is None


class TestKiwoomRateLimitError:
    """KiwoomRateLimitError tests"""

    def test_rate_limit_error_creation(self):
        error = KiwoomRateLimitError()
        assert error.code == KiwoomErrorCode.RATE_LIMIT_EXCEEDED

    def test_rate_limit_error_with_retry(self):
        error = KiwoomRateLimitError(retry_after=60)
        assert error.retry_after == 60
        assert isinstance(error, KiwoomError)

    def test_rate_limit_error_is_retryable(self):
        error = KiwoomRateLimitError()
        assert error.is_retryable is True