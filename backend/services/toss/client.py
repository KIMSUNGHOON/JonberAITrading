"""토스증권 Open API 클라이언트.

OAuth2 client_credentials → Bearer 토큰(24h) → REST.

🔴 **`403`은 다른 실패와 구별한다.** 토스는 발급 화면에서 등록한 IP만
허용하고, 미등록 IP는 전 API가 `403 edge-blocked`가 된다. 이 시스템은 집
맥에서 돌아 공인 IP가 바뀔 수 있는데, 넓은 `except`가 403을 "데이터 없음"
으로 삼키면 **2026-08-07 계열의 사고**가 된다 — 그때는 지수 데이터 실패가
`m_vol=1.0`(가장 관대)으로 이어져 노출도 상한을 두 배로 열었다. 그래서
`TossIpBlockedError`를 따로 올려 호출자가 로그·Telegram에 남길 수 있게 한다.

실호출로 검증한 계약(2026-08-12 22:38):
  POST /oauth2/token  → 200 · access_token 834자 · expires_in 86399
  GET  /api/v1/market-indicators/KOSPI/candles → {"result": {"candles": [...]}}
  GET  /api/v1/stocks/{sym}/warnings          → {"result": []}
"""
from __future__ import annotations

import time
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

BASE_URL = "https://openapi.tossinvest.com"

# 토큰 만료 전 갱신 여유. expires_in이 86399(24h)라 5분이면 넉넉하다.
_REFRESH_MARGIN_SEC = 300


class TossError(Exception):
    """토스 API 호출 실패 일반."""


class TossIpBlockedError(TossError):
    """403 — IP 화이트리스트 이탈.

    '데이터 없음'과 절대 같이 취급하면 안 된다. 이 예외가 뜨면 발급
    화면에서 현재 공인 IP를 다시 등록해야 하고, 그전까지 토스 경로는
    전부 죽어 있다.
    """


class TossClient:
    """토큰을 캐시하고 Bearer를 자동 부착하는 얇은 REST 클라이언트.

    `http`는 주입형이다 — 라이브 API 없이 테스트하기 위함이고,
    `httpx.AsyncClient` 인터페이스(`get`/`post`)만 요구한다.
    """

    def __init__(
        self,
        *,
        client_id: Optional[str],
        client_secret: Optional[str],
        http: Any = None,
        base_url: str = BASE_URL,
    ):
        self._id = client_id
        self._secret = client_secret
        self._http = http
        self._base = base_url.rstrip("/")
        self._token: Optional[str] = None
        self._token_exp: float = 0.0

    @property
    def enabled(self) -> bool:
        """자격증명이 없으면 비활성. 호출자는 이것을 보고 토스 경로를
        통째로 건너뛴다 -- 조용히 실패하는 것보다 낫다."""
        return bool(self._id and self._secret)

    async def _token_value(self) -> str:
        now = time.time()
        if self._token and now < self._token_exp - _REFRESH_MARGIN_SEC:
            return self._token

        resp = await self._http.post(
            f"{self._base}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._id,
                "client_secret": self._secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code == 403:
            raise TossIpBlockedError("token endpoint returned 403 (IP whitelist)")
        if resp.status_code != 200:
            raise TossError(f"token endpoint returned {resp.status_code}")

        payload = resp.json()
        self._token = payload["access_token"]
        self._token_exp = now + float(payload.get("expires_in") or 0)
        return self._token

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        token = await self._token_value()
        resp = await self._http.get(
            f"{self._base}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        if resp.status_code == 403:
            raise TossIpBlockedError(f"{path} returned 403 (IP whitelist)")
        if resp.status_code != 200:
            raise TossError(f"{path} returned {resp.status_code}")
        return resp.json()

    async def get_warnings(self, symbol: str) -> list:
        """매수 유의사항. 정상 종목은 빈 리스트."""
        payload = await self._get(f"/api/v1/stocks/{symbol}/warnings")
        return payload.get("result") or []

    async def get_index_candles(
        self, symbol: str = "KOSPI", *, interval: str = "1d", count: int = 100
    ) -> list[tuple[str, float]]:
        """지수 일봉 → `[(YYYY-MM-DD, 종가), ...]` (응답 순서 그대로).

        yfinance와 달리 **전일 종가가 당일 아침에 이미 있다** — 이것이
        `index_daily`의 상시 1거래일 지연을 없앤다.
        """
        payload = await self._get(
            f"/api/v1/market-indicators/{symbol}/candles",
            params={"interval": interval, "count": count},
        )
        result = payload.get("result") or {}
        rows = result.get("candles") if isinstance(result, dict) else result
        out: list[tuple[str, float]] = []
        for c in rows or []:
            ts = c.get("timestamp")
            close = c.get("closePrice")
            if ts and close is not None:
                out.append((str(ts)[:10], float(close)))
        return out
