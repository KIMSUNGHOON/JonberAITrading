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

    def test_is_token_expired_nested_code_in_message(self):
        # 라이브 관측: Kiwoom가 최상위 return_code=3(일반 인증실패)로 감싸고
        # 실제 8005를 return_msg에 중첩해 반환 → 코드만 보면 놓친다.
        error = KiwoomError(
            code=3,
            message="인증에 실패했습니다[8005:Token이 유효하지 않습니다]",
        )
        assert error.is_token_expired is True
        assert error.is_retryable is True

    def test_is_token_expired_phrase_only(self):
        # 코드 없이 문구만 오는 경우도 감지
        error = KiwoomError(code=3, message="Token이 유효하지 않습니다")
        assert error.is_token_expired is True

    def test_is_token_expired_false_for_unrelated_error(self):
        # 오탐 방지: 토큰과 무관한 에러는 False
        error = KiwoomError(
            code=KiwoomErrorCode.INVALID_STOCK_CODE,
            message="잘못된 종목코드입니다",
        )
        assert error.is_token_expired is False

    def test_from_response_nested_8005_is_token_expired(self):
        # from_response 경로(실 응답 형태) end-to-end
        response = {
            "return_code": 3,
            "return_msg": "인증에 실패했습니다[8005:Token이 유효하지 않습니다]",
        }
        error = KiwoomError.from_response(response, api_id="kt00001")
        assert error.is_token_expired is True

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


class TestKiwoomErrorRateLimitCode5:
    """코드 5(일반 오류)로 감싸 유량초과를 반환하는 라이브 관측 패턴.

    Kiwoom는 유량(rate-limit) 초과를 전용 코드(1700/-903)가 아니라 일반
    코드 5로 감싸고, 실제 사유를 return_msg에 중첩해 반환하는 경우가 있다
    (is_token_expired와 동일한 중첩 패턴). 코드만 보면 놓쳐 재시도가 뜨지
    않고 발굴 유니버스가 15종목 폴백으로 축소된다.
    """

    def test_code5_with_유량_marker_is_rate_limit(self):
        error = KiwoomError(
            code=5,
            message="허용된 요청 개수를 초과하였습니다[1700:허용된 API 요청 개수를 초과하였습니다. 유량=1, API ID=ka10099]",
        )
        assert error.is_rate_limit is True
        assert error.is_retryable is True

    def test_code5_without_marker_not_rate_limit(self):
        error = KiwoomError(code=5, message="종목코드 오류입니다")
        assert error.is_rate_limit is False

    def test_existing_1700_still_rate_limit(self):
        assert KiwoomError(code=1700, message="x").is_rate_limit is True

    def test_rate_limit_exceeded_negative_code(self):
        assert KiwoomError(code=KiwoomErrorCode.RATE_LIMIT_EXCEEDED, message="x").is_rate_limit is True

    def test_허용된요청개수_marker_alt(self):
        error = KiwoomError(code=5, message="허용된 요청 개수를 초과했습니다")
        assert error.is_rate_limit is True


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