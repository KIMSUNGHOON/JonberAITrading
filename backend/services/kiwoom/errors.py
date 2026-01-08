"""
Kiwoom REST API Error Handling

Error codes and exception classes for Kiwoom Securities REST API.
Based on KiwoomRESTAPI.xlsx '공통 > 오류코드' sheet.
"""

from typing import Optional


class KiwoomErrorCode:
    """Kiwoom API 에러 코드 상수"""

    # 성공
    SUCCESS = 0

    # 인증 관련 (-100 ~ -199)
    TOKEN_EXPIRED = -100
    INVALID_APP_KEY = -101
    INVALID_SECRET_KEY = -102
    INVALID_TOKEN = -103
    TOKEN_NOT_FOUND = -104

    # 종목 관련 (-200 ~ -299)
    INVALID_STOCK_CODE = -200
    STOCK_NOT_FOUND = -201
    MARKET_NOT_SUPPORTED = -202

    # 주문 관련 (-300 ~ -399)
    INVALID_ORDER_QTY = -300
    INVALID_ORDER_PRICE = -301
    INVALID_ORDER_TYPE = -302
    ORDER_QTY_EXCEED = -303
    ORDER_PRICE_EXCEED = -304

    # 계좌 관련 (-400 ~ -499)
    INSUFFICIENT_BALANCE = -400
    ORDER_NOT_FOUND = -401
    ACCOUNT_NOT_FOUND = -402
    PERMISSION_DENIED = -403

    # 시장 관련 (-500 ~ -599)
    MARKET_CLOSED = -500
    TRADING_HALTED = -501
    PRICE_LIMIT_REACHED = -502

    # 시스템 관련 (-900 ~ -999)
    SYSTEM_ERROR = -900
    NETWORK_ERROR = -901
    TIMEOUT_ERROR = -902
    RATE_LIMIT_EXCEEDED = -903


# 에러 코드 -> 메시지 매핑
ERROR_MESSAGES: dict[int, str] = {
    KiwoomErrorCode.SUCCESS: "정상 처리되었습니다",
    # 인증
    KiwoomErrorCode.TOKEN_EXPIRED: "접근토큰이 만료되었습니다",
    KiwoomErrorCode.INVALID_APP_KEY: "잘못된 앱키입니다",
    KiwoomErrorCode.INVALID_SECRET_KEY: "잘못된 시크릿키입니다",
    KiwoomErrorCode.INVALID_TOKEN: "유효하지 않은 접근토큰입니다",
    KiwoomErrorCode.TOKEN_NOT_FOUND: "접근토큰이 없습니다",
    # 종목
    KiwoomErrorCode.INVALID_STOCK_CODE: "잘못된 종목코드입니다",
    KiwoomErrorCode.STOCK_NOT_FOUND: "종목을 찾을 수 없습니다",
    KiwoomErrorCode.MARKET_NOT_SUPPORTED: "지원하지 않는 시장입니다",
    # 주문
    KiwoomErrorCode.INVALID_ORDER_QTY: "잘못된 주문수량입니다",
    KiwoomErrorCode.INVALID_ORDER_PRICE: "잘못된 주문가격입니다",
    KiwoomErrorCode.INVALID_ORDER_TYPE: "잘못된 주문유형입니다",
    KiwoomErrorCode.ORDER_QTY_EXCEED: "주문수량이 한도를 초과했습니다",
    KiwoomErrorCode.ORDER_PRICE_EXCEED: "주문가격이 범위를 초과했습니다",
    # 계좌
    KiwoomErrorCode.INSUFFICIENT_BALANCE: "잔고가 부족합니다",
    KiwoomErrorCode.ORDER_NOT_FOUND: "주문을 찾을 수 없습니다",
    KiwoomErrorCode.ACCOUNT_NOT_FOUND: "계좌를 찾을 수 없습니다",
    KiwoomErrorCode.PERMISSION_DENIED: "권한이 없습니다",
    # 시장
    KiwoomErrorCode.MARKET_CLOSED: "장이 마감되었습니다",
    KiwoomErrorCode.TRADING_HALTED: "거래가 정지되었습니다",
    KiwoomErrorCode.PRICE_LIMIT_REACHED: "가격제한에 도달했습니다",
    # 시스템
    KiwoomErrorCode.SYSTEM_ERROR: "시스템 오류가 발생했습니다",
    KiwoomErrorCode.NETWORK_ERROR: "네트워크 오류가 발생했습니다",
    KiwoomErrorCode.TIMEOUT_ERROR: "요청 시간이 초과되었습니다",
    KiwoomErrorCode.RATE_LIMIT_EXCEEDED: "API 호출 한도를 초과했습니다",
}


class KiwoomError(Exception):
    """
    Kiwoom API 에러 예외 클래스

    Attributes:
        code: 에러 코드
        message: 에러 메시지
        api_id: API ID (선택)
        details: 추가 상세 정보 (선택)
    """

    def __init__(
        self,
        code: int,
        message: Optional[str] = None,
        api_id: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        self.code = code
        self.message = message or ERROR_MESSAGES.get(code, "알 수 없는 오류")
        self.api_id = api_id
        self.details = details or {}

        error_str = f"[{code}] {self.message}"
        if api_id:
            error_str = f"[{api_id}] {error_str}"

        super().__init__(error_str)

    @property
    def is_retryable(self) -> bool:
        """재시도 가능한 에러인지 확인"""
        retryable_codes = {
            KiwoomErrorCode.TOKEN_EXPIRED,
            KiwoomErrorCode.NETWORK_ERROR,
            KiwoomErrorCode.TIMEOUT_ERROR,
            KiwoomErrorCode.RATE_LIMIT_EXCEEDED,
            KiwoomErrorCode.SYSTEM_ERROR,
        }
        return self.code in retryable_codes

    @property
    def is_auth_error(self) -> bool:
        """인증 관련 에러인지 확인"""
        return -199 <= self.code <= -100

    @property
    def is_order_error(self) -> bool:
        """주문 관련 에러인지 확인"""
        return -399 <= self.code <= -300

    @classmethod
    def from_response(
        cls,
        response_data: dict,
        api_id: Optional[str] = None,
    ) -> "KiwoomError":
        """
        API 응답에서 에러 생성

        Args:
            response_data: API 응답 데이터
            api_id: API ID

        Returns:
            KiwoomError 인스턴스
        """
        code = response_data.get("return_code", KiwoomErrorCode.SYSTEM_ERROR)
        message = response_data.get("return_msg")

        # 문자열 코드를 정수로 변환
        if isinstance(code, str):
            try:
                code = int(code)
            except ValueError:
                code = KiwoomErrorCode.SYSTEM_ERROR

        return cls(
            code=code,
            message=message,
            api_id=api_id,
            details=response_data,
        )


class KiwoomAuthError(KiwoomError):
    """인증 관련 에러"""

    def __init__(self, code: int = KiwoomErrorCode.INVALID_TOKEN, message: Optional[str] = None):
        super().__init__(code=code, message=message)


class KiwoomOrderError(KiwoomError):
    """주문 관련 에러"""

    def __init__(
        self,
        code: int,
        message: Optional[str] = None,
        order_no: Optional[str] = None,
    ):
        super().__init__(code=code, message=message)
        self.order_no = order_no


class KiwoomNetworkError(KiwoomError):
    """네트워크 에러"""

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(
            code=KiwoomErrorCode.NETWORK_ERROR,
            message=message,
            details={"original_error": str(original_error)} if original_error else {},
        )
        self.original_error = original_error


class KiwoomRateLimitError(KiwoomError):
    """Rate Limit 초과 에러"""

    def __init__(self, retry_after: Optional[int] = None):
        super().__init__(
            code=KiwoomErrorCode.RATE_LIMIT_EXCEEDED,
            details={"retry_after": retry_after} if retry_after else {},
        )
        self.retry_after = retry_after