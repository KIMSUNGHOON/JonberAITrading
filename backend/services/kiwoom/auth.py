"""
Kiwoom REST API OAuth Authentication

OAuth2 token management for Kiwoom Securities REST API.
- Token issuance (au10001)
- Token revocation (au10002)
- Automatic token refresh before expiration
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog

from .errors import KiwoomAuthError, KiwoomErrorCode, KiwoomNetworkError
from .models import KiwoomToken

logger = structlog.get_logger()

# 키움 서버 시간대 — expires_dt는 KST 문자열로 온다
KST = timezone(timedelta(hours=9))


class KiwoomAuth:
    """
    Kiwoom OAuth2 인증 관리자

    Features:
    - 접근토큰 발급 및 캐싱
    - 토큰 만료 전 자동 갱신
    - 토큰 폐기

    Usage:
        auth = KiwoomAuth(
            base_url="https://mockapi.kiwoom.com",
            app_key="your_app_key",
            secret_key="your_secret_key"
        )
        token = await auth.get_token()
    """

    # 토큰 만료 전 갱신 여유 시간 (초)
    TOKEN_REFRESH_MARGIN = 300  # 5분

    def __init__(
        self,
        base_url: str,
        app_key: str,
        secret_key: str,
        timeout: float = 30.0,
    ):
        """
        Initialize Kiwoom Auth.

        Args:
            base_url: Kiwoom API base URL
            app_key: 발급받은 앱키
            secret_key: 발급받은 시크릿키
            timeout: HTTP 요청 타임아웃 (초)
        """
        self.base_url = base_url.rstrip("/")
        self.app_key = app_key
        self.secret_key = secret_key
        self.timeout = timeout

        self._token: Optional[KiwoomToken] = None
        self._lock = asyncio.Lock()
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """HTTP 클라이언트 가져오기 (Lazy initialization)"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                },
            )
        return self._client

    async def close(self):
        """리소스 정리"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_token(self) -> str:
        """
        유효한 접근토큰 가져오기

        토큰이 없거나 만료 임박 시 자동으로 새 토큰 발급

        Returns:
            접근토큰 문자열

        Raises:
            KiwoomAuthError: 토큰 발급 실패 시
        """
        async with self._lock:
            # 토큰이 없거나 만료 임박 시 새로 발급
            if self._token is None or self._should_refresh():
                await self._issue_token()

            return self._token.token

    def _should_refresh(self) -> bool:
        """토큰 갱신 필요 여부 확인"""
        if self._token is None:
            return True

        # 만료 시간에서 여유 시간을 뺀 시점보다 현재가 늦으면 갱신 (KST 기준 비교;
        # naive expires_dt는 KST로 간주)
        expires = self._token.expires_dt
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=KST)
        refresh_threshold = expires - timedelta(seconds=self.TOKEN_REFRESH_MARGIN)
        return datetime.now(KST) >= refresh_threshold

    def invalidate_token(self) -> None:
        """로컬 토큰 무효화 — 다음 get_token()이 새 토큰을 발급받게 한다.

        서버가 토큰 만료/무효(8005 등, HTTP 401)를 반환했을 때 클라이언트가
        재발급-재시도하기 위해 호출한다. 서버측 폐기(revoke)는 하지 않는다.
        """
        self._token = None

    @staticmethod
    def _parse_expires_dt(expires_dt_str: Optional[str]) -> datetime:
        """expires_dt 문자열을 KST tz-aware datetime으로 파싱 (실패 시 24h 후)."""
        if expires_dt_str:
            for fmt in ["%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
                try:
                    return datetime.strptime(expires_dt_str, fmt).replace(tzinfo=KST)
                except ValueError:
                    continue
        return datetime.now(KST) + timedelta(hours=24)

    async def _issue_token(self, max_retries: int = 3, base_delay: float = 1.0):
        """
        접근토큰 발급 (au10001)

        POST /oauth2/token

        Args:
            max_retries: Rate limit 시 최대 재시도 횟수
            base_delay: 재시도 시 기본 대기 시간 (초, exponential backoff 적용)
        """
        client = await self._get_client()

        request_body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.secret_key,
        }

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    # Exponential backoff with jitter
                    import random
                    delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    logger.info(
                        "kiwoom_auth_retry",
                        attempt=attempt + 1,
                        max_retries=max_retries + 1,
                        delay=f"{delay:.2f}s",
                    )
                    await asyncio.sleep(delay)

                logger.info("kiwoom_auth_issuing_token", base_url=self.base_url, attempt=attempt + 1)

                response = await client.post(
                    f"{self.base_url}/oauth2/token",
                    json=request_body,
                    headers={"api-id": "au10001"},
                )

                # Handle 429 Rate Limit
                if response.status_code == 429:
                    logger.warning(
                        "kiwoom_auth_rate_limited",
                        attempt=attempt + 1,
                        status_code=429,
                    )
                    last_error = KiwoomAuthError(
                        code=KiwoomErrorCode.RATE_LIMIT_EXCEEDED,
                        message="허용된 요청 개수를 초과했습니다. 잠시 후 다시 시도해주세요.",
                    )
                    continue

                data = response.json()

                # 에러 체크 (API 응답 내 return_code)
                return_code = data.get("return_code")
                if return_code is not None:
                    # 문자열 코드를 정수로 변환
                    if isinstance(return_code, str):
                        return_code = int(return_code) if return_code.lstrip("-").isdigit() else -1

                    # Rate limit error in response body (return_code=5)
                    if return_code == 5:
                        logger.warning(
                            "kiwoom_auth_rate_limited_response",
                            attempt=attempt + 1,
                            return_code=return_code,
                            return_msg=data.get("return_msg"),
                        )
                        last_error = KiwoomAuthError(
                            code=return_code,
                            message=data.get("return_msg", "허용된 요청 개수를 초과했습니다"),
                        )
                        continue

                    if return_code != 0:
                        logger.error(
                            "kiwoom_auth_token_error",
                            return_code=return_code,
                            return_msg=data.get("return_msg"),
                        )
                        raise KiwoomAuthError(
                            code=return_code,
                            message=data.get("return_msg", "토큰 발급 실패"),
                        )

                # 토큰 파싱
                token = data.get("token")
                token_type = data.get("token_type", "Bearer")
                expires_dt_str = data.get("expires_dt")

                if not token:
                    raise KiwoomAuthError(
                        code=KiwoomErrorCode.TOKEN_NOT_FOUND,
                        message="응답에 토큰이 없습니다",
                    )

                # 만료 시간 파싱 — 서버가 KST 문자열로 주므로 KST tz-aware로
                expires_dt = self._parse_expires_dt(expires_dt_str)

                self._token = KiwoomToken(
                    token=token,
                    token_type=token_type,
                    expires_dt=expires_dt,
                )

                logger.info(
                    "kiwoom_auth_token_issued",
                    expires_dt=expires_dt.isoformat(),
                )
                return  # 성공 시 함수 종료

            except httpx.HTTPError as e:
                logger.error("kiwoom_auth_network_error", error=str(e), attempt=attempt + 1)
                last_error = KiwoomNetworkError(
                    message=f"토큰 발급 중 네트워크 오류: {str(e)}",
                    original_error=e,
                )
                continue

        # 모든 재시도 실패 시 마지막 에러 발생
        if last_error:
            raise last_error
        raise KiwoomAuthError(
            code=KiwoomErrorCode.RATE_LIMIT_EXCEEDED,
            message="토큰 발급에 실패했습니다. 잠시 후 다시 시도해주세요.",
        )

    async def revoke_token(self):
        """
        접근토큰 폐기 (au10002)

        POST /oauth2/revoke
        """
        if self._token is None:
            return

        client = await self._get_client()

        try:
            logger.info("kiwoom_auth_revoking_token")

            # 공식 계약: revoke body는 appkey/secretkey/token 3필드 (참조 구현
            # kiwoom/core/auth.py:180-189; authorization 헤더 아님)
            response = await client.post(
                f"{self.base_url}/oauth2/revoke",
                json={
                    "appkey": self.app_key,
                    "secretkey": self.secret_key,
                    "token": self._token.token,
                },
                headers={"api-id": "au10002"},
            )

            data = response.json()
            return_code = data.get("return_code", 0)

            if isinstance(return_code, str):
                return_code = int(return_code) if return_code.lstrip("-").isdigit() else 0

            if return_code == 0:
                logger.info("kiwoom_auth_token_revoked")
            else:
                logger.warning(
                    "kiwoom_auth_revoke_warning",
                    return_code=return_code,
                    return_msg=data.get("return_msg"),
                )

        except httpx.HTTPError as e:
            logger.warning("kiwoom_auth_revoke_network_error", error=str(e))

        finally:
            self._token = None

    @property
    def has_valid_token(self) -> bool:
        """유효한 토큰 보유 여부"""
        return self._token is not None and not self._token.is_expired

    @property
    def token_expires_at(self) -> Optional[datetime]:
        """토큰 만료 시간"""
        return self._token.expires_dt if self._token else None