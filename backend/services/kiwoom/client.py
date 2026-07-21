"""
Kiwoom REST API Client

Async HTTP client for Kiwoom Securities REST API.
Supports both Mock Trading (mockapi) and Live Trading (api).

Rate Limiting:
  이용약관 제11조에 따라 API 호출 횟수가 제한됩니다:
  - 조회횟수: 초당 5건
  - 주문횟수: 초당 5건
  Rate Limiter가 자동으로 요청 속도를 조절합니다.
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import pandas as pd
import structlog

from .auth import KiwoomAuth
from .cache import KiwoomCache, make_cache_key
from .errors import (
    KiwoomAuthError,
    KiwoomError,
    KiwoomErrorCode,
    KiwoomNetworkError,
    KiwoomRateLimitError,
)
from .rate_limiter import KiwoomRateLimiter, get_request_type
from .models import (
    AccountBalance,
    CashBalance,
    ChartData,
    DailyRealizedPnlRow,
    Exchange,
    FilledOrder,
    Holding,
    MarketType,
    Orderbook,
    OrderbookUnit,
    OrderRequest,
    OrderResponse,
    OrderType,
    PendingOrder,
    RealizedPnl,
    StockBasicInfo,
    StockListItem,
)

logger = structlog.get_logger()

# 키움 서버 시간대 (실현손익 기본 조회일 계산)
KST = timezone(timedelta(hours=9))

# ETN/스팩/채권 파생상품 이름 패턴 (DQ-1) — ETF/리츠/ELW는 이미 get_all_stocks의
# mrkt_tp=0,10 쿼리에서 구조적으로 제외되므로(전용 시장구분 존재), 여기서는
# 전용 시장구분이 없어 코스피/코스닥에 혼입되는 ETN·스팩만 이름으로 거른다.
# 보수적 키워드 목록 — 오탐(정상 종목 오제외)보다 누락(ETN 잔존)이 안전하므로
# 종목명 전반에 흔한 한 글자/두 글자 단어는 넣지 않는다.
_ETF_ETN_NAME_KEYWORDS: tuple[str, ...] = (
    "ETN",
    "스팩",
    "채권",
    "회사채",
    "국고",
    "통안",
    "금리",
    "CD ",
    "인버스",
    "레버리지",
    "선물",
    # DQ-3 보강 — 해외지수/상품/테마 ETF·ETN이 흔히 쓰는 단어. "리츠"는
    # REITS(mrkt_tp=6)가 이미 위 mrkt_tp=0,10 쿼리에서 구조적으로 빠지므로
    # 실효 매치는 없을 것으로 보이나(정상 상장 리츠는 애초에 이 목록에
    # 들어오지 않음), Kiwoom 분류가 어긋나는 예외 케이스에 대한 방어선으로
    # 유지한다.
    "미국",
    "중국",
    "일본",
    "베트남",
    "인도",
    "S&P",
    "나스닥",
    "배당",
    "커버드콜",
    "하이일드",
    "액티브",
    "리츠",
)

# 발행사 브랜드 프리픽스 (DQ-3) — DQ-1 키워드 목록은 브랜드명 없이 상품명만
# 있는 ETF/ETN을 못 잡는 결함이 있었다("KODEX 200"처럼 브랜드+지수명만인
# 경우 위 키워드 어디에도 안 걸림). 종목명 "줄 시작"에서만 매칭한다 — 실제
# ETF/ETN 명명 관례가 "브랜드 + 공백 + 설명"이므로, 브랜드 뒤에 공백(또는
# 문자열 끝)이 오는 경우만 매치해 "BNK금융지주"(실제 은행지주 종목, BNK
# 뒤에 공백 없이 바로 한글)·"HK이노엔"(실제 제약 종목, HK 뒤에 공백 없음)
# 같은 브랜드-프리픽스 우연일치를 배제한다.
_ETF_ETN_BRAND_PREFIXES: tuple[str, ...] = (
    "KODEX",
    "TIGER",
    "ACE",
    "KBSTAR",
    "PLUS",
    "RISE",
    "SOL",
    "HANARO",
    "KOSEF",
    "ARIRANG",
    "TIMEFOLIO",
    "TIME",
    "WON",
    "KIWOOM",
    "1Q",
    "HK",
    "BNK",
    "FOCUS",
    "TREX",
    "KCGI",
)

_ETF_ETN_NAME_RE = re.compile(
    "(?:"
    + "|".join(re.escape(kw) for kw in _ETF_ETN_NAME_KEYWORDS)
    + ")"
    + "|^(?:"
    + "|".join(re.escape(p) for p in _ETF_ETN_BRAND_PREFIXES)
    + r")(?=\s|$)",
    re.IGNORECASE,
)


class KiwoomClient:
    """
    Kiwoom REST API 비동기 클라이언트

    Features:
    - 종목 정보 조회 (시세, 호가, 차트)
    - 계좌 조회 (잔고, 예수금)
    - 주문 (매수/매도/정정/취소)

    Usage:
        async with KiwoomClient(
            app_key="your_key",
            secret_key="your_secret",
            is_mock=True
        ) as client:
            info = await client.get_stock_info("005930")
            print(f"삼성전자: {info.cur_prc:,}원")
    """

    # API Base URLs
    MOCK_URL = "https://mockapi.kiwoom.com"
    LIVE_URL = "https://api.kiwoom.com"

    def __init__(
        self,
        app_key: str,
        secret_key: str,
        is_mock: bool = True,
        timeout: float = 30.0,
        enable_rate_limit: bool = True,
        enable_cache: bool = True,
    ):
        """
        Initialize Kiwoom Client.

        Args:
            app_key: 발급받은 앱키
            secret_key: 발급받은 시크릿키
            is_mock: True=모의투자, False=실거래
            timeout: HTTP 요청 타임아웃 (초)
            enable_rate_limit: Rate limit 활성화 여부 (기본: True)
            enable_cache: 캐시 활성화 여부 (기본: True)
        """
        self.is_mock = is_mock
        self.base_url = self.MOCK_URL if is_mock else self.LIVE_URL
        self.timeout = timeout
        self.enable_rate_limit = enable_rate_limit
        self.enable_cache = enable_cache

        # Auth manager
        self.auth = KiwoomAuth(
            base_url=self.base_url,
            app_key=app_key,
            secret_key=secret_key,
            timeout=timeout,
        )

        # Rate Limiter (이용약관 제11조: 조회/주문 각각 초당 5건)
        self._rate_limiter: Optional[KiwoomRateLimiter] = (
            KiwoomRateLimiter() if enable_rate_limit else None
        )

        # Cache (API 호출 최소화)
        self._cache: Optional[KiwoomCache] = (
            KiwoomCache() if enable_cache else None
        )

        # HTTP client
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """HTTP 클라이언트 가져오기"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                    "Accept": "application/json",
                },
            )
        return self._client

    async def close(self):
        """리소스 정리"""
        if self._client:
            await self._client.aclose()
            self._client = None
        await self.auth.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # ============================================================
    # Internal Request Method
    # ============================================================

    # Maximum retry attempts for rate limit errors
    MAX_RETRY_ATTEMPTS = 3
    RETRY_BASE_DELAY = 1.0  # seconds

    async def _request(
        self,
        api_id: str,
        endpoint: str,
        data: Optional[dict] = None,
        cont_yn: str = "",
        next_key: str = "",
        with_continuation: bool = False,
    ):
        """
        공통 API 요청 메서드 (레이트리밋 재시도 + 토큰만료 재발급-재시도 1회)

        Args:
            api_id: API ID (예: ka10001)
            endpoint: API endpoint (예: /api/dostk/stkinfo)
            data: Request body
            cont_yn: 연속조회여부 (Y/N)
            next_key: 연속조회키
            with_continuation: True면 (result, {"cont_yn","next_key"}) 튜플 반환.
                연속조회 값은 응답 HTTP **헤더**로 온다 (공식 계약).

        Returns:
            API 응답 딕셔너리 (with_continuation=True면 (dict, dict) 튜플)

        Raises:
            KiwoomError: API 에러
            KiwoomNetworkError: 네트워크 에러
            KiwoomRateLimitError: Rate limit 초과 (재시도 후에도 실패)
        """
        last_error: Optional[Exception] = None
        auth_retried = False

        attempt = 0
        while attempt < self.MAX_RETRY_ATTEMPTS:
            try:
                result, continuation = await self._request_once(
                    api_id, endpoint, data, cont_yn, next_key
                )
                if with_continuation:
                    return result, continuation
                return result
            except KiwoomError as e:
                if e.is_token_expired and not auth_retried:
                    # 토큰 만료/무효 — 재발급 후 1회만 재시도 (시도 횟수 미소모)
                    auth_retried = True
                    logger.warning("kiwoom_token_expired_reissue", api_id=api_id, code=e.code)
                    self.auth.invalidate_token()
                    continue
                if e.is_rate_limit:
                    last_error = e
                    # Exponential backoff: 1s, 2s, 4s
                    delay = self.RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "kiwoom_rate_limit_retry",
                        api_id=api_id,
                        attempt=attempt + 1,
                        max_attempts=self.MAX_RETRY_ATTEMPTS,
                        delay=delay,
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                else:
                    # Non-retryable error
                    raise

        # All retries exhausted
        logger.error(
            "kiwoom_rate_limit_exhausted",
            api_id=api_id,
            attempts=self.MAX_RETRY_ATTEMPTS,
        )
        raise last_error or KiwoomRateLimitError()

    async def _request_once(
        self,
        api_id: str,
        endpoint: str,
        data: Optional[dict] = None,
        cont_yn: str = "",
        next_key: str = "",
    ) -> tuple[dict, dict]:
        """
        단일 API 요청 메서드

        Args:
            api_id: API ID (예: ka10001)
            endpoint: API endpoint (예: /api/dostk/stkinfo)
            data: Request body
            cont_yn: 연속조회여부 (Y/N)
            next_key: 연속조회키

        Returns:
            (API 응답 딕셔너리, 연속조회 정보 {"cont_yn","next_key"}) —
            연속조회 값은 응답 HTTP 헤더에서 읽는다 (공식 계약; body에는 없음)
        """
        # Rate Limiting (이용약관 제11조)
        if self._rate_limiter:
            request_type = get_request_type(api_id)
            acquired = await self._rate_limiter.acquire(request_type, api_id=api_id)
            if not acquired:
                raise KiwoomRateLimitError()

        client = await self._get_client()
        token = await self.auth.get_token()

        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "api-id": api_id,
            "authorization": f"Bearer {token}",
        }

        if cont_yn:
            headers["cont-yn"] = cont_yn
        if next_key:
            headers["next-key"] = next_key

        url = f"{self.base_url}{endpoint}"

        try:
            logger.debug(
                "kiwoom_api_request",
                api_id=api_id,
                endpoint=endpoint,
            )

            response = await client.post(
                url,
                json=data or {},
                headers=headers,
            )

            # HTTP 401 — 토큰 무효 (body 없이 올 수 있음). _request가 재발급-재시도.
            if response.status_code == 401:
                raise KiwoomAuthError(
                    code=KiwoomErrorCode.TOKEN_EXPIRED,
                    message="HTTP 401 Unauthorized",
                )

            try:
                result = response.json()
            except ValueError:
                # 비-JSON 응답 (게이트웨이 오류 페이지 등)
                raise KiwoomError(
                    code=KiwoomErrorCode.SYSTEM_ERROR,
                    message=f"비-JSON 응답 (HTTP {response.status_code})",
                    api_id=api_id,
                )

            # 에러 체크 (비숫자 코드는 판정 제외 — 참조 구현 normalize_return_code)
            return_code = result.get("return_code")
            if return_code is not None:
                if isinstance(return_code, str):
                    return_code = (
                        int(return_code) if return_code.lstrip("-").isdigit() else None
                    )

                if return_code is not None and return_code != 0:
                    logger.error(
                        "kiwoom_api_error",
                        api_id=api_id,
                        return_code=return_code,
                        return_msg=result.get("return_msg"),
                    )
                    raise KiwoomError.from_response(result, api_id=api_id)

            logger.debug(
                "kiwoom_api_response",
                api_id=api_id,
                success=True,
            )

            resp_headers = response.headers or {}
            continuation = {
                "cont_yn": resp_headers.get("cont-yn", "N") or "N",
                "next_key": resp_headers.get("next-key", "") or "",
            }
            return result, continuation

        except httpx.HTTPError as e:
            logger.error(
                "kiwoom_api_network_error",
                api_id=api_id,
                error=str(e),
            )
            raise KiwoomNetworkError(
                message=f"API 요청 중 네트워크 오류: {str(e)}",
                original_error=e,
            )

    # ============================================================
    # 종목 정보 API (ka10001, ka10004, ka10081 등)
    # ============================================================

    @staticmethod
    def _strip_stock_prefix(code: str) -> str:
        """계좌 응답 종목코드의 시장 접두사 제거 (예: "A005930" -> "005930").

        kt00004/ka10075/ka10076 응답의 stk_cd는 접두사가 붙어 온다
        (계좌.md:2128 응답 예제) — 시세/주문 TR의 6자리 코드와 대조하려면
        스트립이 필요하다.
        """
        if code and len(code) > 6 and code[0].isalpha():
            return code[1:]
        return code or ""

    @staticmethod
    def _parse_signed_price(value: str | int | None) -> int:
        """
        부호가 포함된 가격 문자열 파싱
        예: "+112400" -> 112400, "-110900" -> 110900
        부호는 전일대비 상승/하락을 나타내며, 실제 가격은 절대값
        """
        if value is None:
            return 0
        if isinstance(value, int):
            return abs(value)
        value = str(value).strip()
        if not value or value == "0":
            return 0
        # 부호 제거하고 절대값 반환
        return abs(int(value.replace("+", "").replace("-", "").replace(",", "")))

    @staticmethod
    def _parse_change(value: str | int | None) -> int:
        """전일대비 값 파싱 (부호 유지)"""
        if value is None:
            return 0
        if isinstance(value, int):
            return value
        value = str(value).strip()
        if not value or value == "0":
            return 0
        return int(value.replace(",", ""))

    @staticmethod
    def _parse_float(value: str | float | None) -> float:
        """실수 파싱. Kiwoom 부호 규약: 양수 '+N', 음수 이중부호 '--N'
        (ka10131 순매수액 등) 또는 단일 '-N'(연속일수·등락률). '--N'을 '-N'으로
        정규화하고 선두 '+'를 제거한다."""
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        value = str(value).strip().replace(",", "")
        if value.startswith("--"):
            value = value[1:]          # '--35' -> '-35'
        value = value.lstrip("+")      # '+122068' -> '122068'
        if not value or value in ("-", "."):
            return 0.0
        return float(value)

    async def get_stock_info(
        self, stk_cd: str, ttl: Optional[float] = None
    ) -> StockBasicInfo:
        """
        주식기본정보요청 (ka10001)

        Args:
            stk_cd: 종목코드 (예: "005930")
            ttl: 캐시 저장 TTL(초) 오버라이드. None이면 `stock_info` 프리픽스
                기본값(3.0s)을 그대로 사용 — 감시 종목 수(N)에 따라 동적으로
                산출한 TTL(`services.trading.cadence.compute_held_ttl`)을
                보유 종목 조회 경로에서 넘길 때 사용 (감시 튜닝 아크).

        Returns:
            StockBasicInfo 객체
        """
        # 캐시 조회
        cache_key = make_cache_key("stock_info", stk_cd)
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._request(
            api_id="ka10001",
            endpoint="/api/dostk/stkinfo",
            data={"stk_cd": stk_cd},
        )

        # output 필드가 있으면 그 안의 데이터 사용
        output = result.get("output", result)
        if isinstance(output, list) and len(output) > 0:
            output = output[0]

        # 현재가 파싱 (부호 포함된 문자열)
        cur_prc = self._parse_signed_price(output.get("cur_prc"))

        # 전일대비 파싱
        prdy_vrss = self._parse_change(output.get("pred_pre", output.get("prdy_vrss", 0)))

        # 등락률 파싱
        prdy_ctrt = self._parse_float(output.get("flu_rt", output.get("prdy_ctrt", 0)))

        stock_info = StockBasicInfo(
            stk_cd=output.get("stk_cd", stk_cd),
            stk_nm=output.get("stk_nm", ""),
            cur_prc=cur_prc,
            prdy_vrss=prdy_vrss,
            prdy_ctrt=prdy_ctrt,
            acml_vol=self._parse_signed_price(output.get("trde_qty", output.get("acml_vol", 0))),
            # ka10001 응답에 누적거래대금 필드는 없다 (감사 M2) — 항상 0
            acml_tr_pbmn=0,
            strt_prc=self._parse_signed_price(output.get("open_pric", output.get("strt_prc", 0))),
            high_prc=self._parse_signed_price(output.get("high_pric", output.get("high_prc", 0))),
            low_prc=self._parse_signed_price(output.get("low_pric", output.get("low_prc", 0))),
            stk_hgpr=self._parse_signed_price(output.get("upl_pric", output.get("stk_hgpr", 0))),
            stk_lwpr=self._parse_signed_price(output.get("lst_pric", output.get("stk_lwpr", 0))),
            per=self._parse_float(output.get("per")) if output.get("per") else None,
            pbr=self._parse_float(output.get("pbr")) if output.get("pbr") else None,
            eps=int(self._parse_float(output.get("eps"))) if output.get("eps") else None,
            bps=int(self._parse_float(output.get("bps"))) if output.get("bps") else None,
            # 상장주식수의 스펙 키는 flo_stk (감사 M2 — lstg_stqt는 미존재 키)
            lstg_stqt=self._parse_signed_price(output.get("flo_stk")) if output.get("flo_stk") else None,
            mrkt_tot_amt=self._parse_signed_price(output.get("mac", output.get("mrkt_tot_amt"))) if output.get("mac") or output.get("mrkt_tot_amt") else None,
        )

        # 캐시 저장
        if self._cache:
            self._cache.set(cache_key, stock_info, ttl=ttl)

        return stock_info

    async def get_orderbook(self, stk_cd: str) -> Orderbook:
        """
        주식호가요청 (ka10004)

        Args:
            stk_cd: 종목코드

        Returns:
            Orderbook 객체
        """
        # 캐시 조회
        cache_key = make_cache_key("orderbook", stk_cd)
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._request(
            api_id="ka10004",
            endpoint="/api/dostk/mrkcond",
            data={"stk_cd": stk_cd},
        )

        output = result.get("output", result)
        if isinstance(output, list) and len(output) > 0:
            output = output[0]

        # 공식 계약 키 (시세.md:90-137; 감사 C8): 1호가는 *_fpr_*(최우선),
        # 2~10호가는 *_{n}th_pre_* — 기존 sell_hoga_*/ofr_prc* 키는 스펙에
        # 없어 호가 전체가 조용히 빈 리스트로 반환됐었다.
        def _hoga_keys(side: str, level: int) -> tuple[str, str]:
            if level == 1:
                return f"{side}_fpr_bid", f"{side}_fpr_req"
            return f"{side}_{level}th_pre_bid", f"{side}_{level}th_pre_req"

        sell_hogas = []
        buy_hogas = []
        for i in range(1, 11):
            price_key, qty_key = _hoga_keys("sel", i)
            price = self._parse_signed_price(output.get(price_key))
            if price:
                sell_hogas.append(OrderbookUnit(
                    price=price,
                    quantity=self._parse_signed_price(output.get(qty_key)),
                ))
            price_key, qty_key = _hoga_keys("buy", i)
            price = self._parse_signed_price(output.get(price_key))
            if price:
                buy_hogas.append(OrderbookUnit(
                    price=price,
                    quantity=self._parse_signed_price(output.get(qty_key)),
                ))

        orderbook = Orderbook(
            stk_cd=stk_cd,
            sell_hogas=sell_hogas,
            buy_hogas=buy_hogas,
            tot_sell_qty=self._parse_signed_price(output.get("tot_sel_req")),
            tot_buy_qty=self._parse_signed_price(output.get("tot_buy_req")),
        )

        # 캐시 저장
        if self._cache:
            self._cache.set(cache_key, orderbook)

        return orderbook

    async def get_daily_chart(
        self,
        stk_cd: str,
        base_dt: Optional[str] = None,
        upd_stkpc_tp: str = "1",
    ) -> list[ChartData]:
        """
        주식일봉차트조회요청 (ka10081)

        Args:
            stk_cd: 종목코드
            base_dt: 기준일자 (YYYYMMDD), None이면 오늘
            upd_stkpc_tp: 수정주가구분 — "1":수정주가(기본; 액면분할 등 기업행위 보정), "0":원주가

        Returns:
            ChartData 리스트
        """
        from datetime import datetime

        if base_dt is None:
            base_dt = datetime.now().strftime("%Y%m%d")

        # 캐시 조회
        cache_key = make_cache_key("daily_chart", stk_cd, base_dt)
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        data = {
            "stk_cd": stk_cd,
            "base_dt": base_dt,
            "upd_stkpc_tp": upd_stkpc_tp,
        }

        result = await self._request(
            api_id="ka10081",
            endpoint="/api/dostk/chart",
            data=data,
        )

        # 응답 필드명: stk_dt_pole_chart_qry (일봉차트 배열)
        output = result.get("stk_dt_pole_chart_qry", result.get("output", []))
        if not isinstance(output, list):
            output = [output] if output else []

        chart_data = [
            ChartData(
                stk_cd=result.get("stk_cd", stk_cd),
                dt=item.get("dt", ""),
                open_prc=self._parse_signed_price(item.get("open_pric", item.get("open_prc", 0))),
                high_prc=self._parse_signed_price(item.get("high_pric", item.get("high_prc", 0))),
                low_prc=self._parse_signed_price(item.get("low_pric", item.get("low_prc", 0))),
                clos_prc=self._parse_signed_price(item.get("cur_prc", item.get("clos_prc", 0))),
                acml_vol=self._parse_signed_price(item.get("trde_qty", item.get("acml_vol", 0))),
                # trde_prica 단위는 백만원 (kiwoom_api_spec.json; 감사 M4) —
                # 하류(REST 응답·mock 경로)는 원 단위를 기대하므로 환산
                acml_tr_pbmn=self._parse_signed_price(item.get("trde_prica")) * 1_000_000
                if item.get("trde_prica") else None,
            )
            for item in output
        ]

        # 캐시 저장
        if self._cache:
            self._cache.set(cache_key, chart_data)

        return chart_data

    async def get_sector_index(self, inds_cd: str = "001") -> Optional[list[dict]]:
        """전업종지수요청 (ka20003). inds_cd: "001"=KOSPI계열, "101"=KOSDAQ계열.
        실패-무해: 예외/빈응답이면 None (EOD 배치가 절대 안 깨지도록)."""
        try:
            result = await self._request(
                api_id="ka20003",
                endpoint="/api/dostk/sect",
                data={"inds_cd": inds_cd},
            )
            rows = result.get("all_inds_idex")
            if not rows:
                return None
            out = []
            for r in rows:
                out.append({
                    "stk_cd": r.get("stk_cd", ""),
                    "stk_nm": r.get("stk_nm", ""),
                    "cur_prc": abs(self._parse_float(r.get("cur_prc"))),  # 부호=방향
                    "chg_pct": self._parse_float(r.get("flu_rt")),        # 부호 유지
                    "rising": int(self._parse_float(r.get("rising"))),
                    "stdns": int(self._parse_float(r.get("stdns"))),
                    "fall": int(self._parse_float(r.get("fall"))),
                })
            return out
        except Exception as e:
            logger.warning(f"[Kiwoom] get_sector_index({inds_cd}) failed: {e}")
            return None

    async def get_inst_foreign_flow(self, mrkt_tp: str = "001") -> Optional[list[dict]]:
        """기관외국인연속매매현황요청 (ka10131). mrkt_tp: "001"=KOSPI, "101"=KOSDAQ.
        실패-무해: 예외/빈응답이면 None. 행단위: 한 행 파싱 실패는 해당 행만 skip."""
        try:
            result = await self._request(
                api_id="ka10131",
                endpoint="/api/dostk/frgnistt",
                data={
                    "dt": "1", "strt_dt": "", "end_dt": "",
                    "mrkt_tp": mrkt_tp, "netslmt_tp": "2", "stk_inds_tp": "0",
                    "amt_qty_tp": "0", "stex_tp": "1",
                },
            )
            rows = result.get("orgn_frgnr_cont_trde_prst")
            if not rows:
                return None
            out = []
            for r in rows:
                try:
                    out.append({
                        "stk_cd": r.get("stk_cd", ""),
                        "orgn_net_amt": self._parse_float(r.get("orgn_nettrde_amt")),
                        "frgnr_net_amt": self._parse_float(r.get("frgnr_nettrde_amt")),
                        "orgn_cont_days": int(self._parse_float(r.get("orgn_cont_netprps_dys"))),
                        "frgnr_cont_days": int(self._parse_float(r.get("frgnr_cont_netprps_dys"))),
                    })
                except Exception as e:
                    logger.warning(
                        f"[Kiwoom] get_inst_foreign_flow({mrkt_tp}) row skipped: {e}"
                    )
                    continue
            return out
        except Exception as e:
            logger.warning(f"[Kiwoom] get_inst_foreign_flow({mrkt_tp}) failed: {e}")
            return None

    async def get_daily_chart_df(
        self,
        stk_cd: str,
        base_dt: Optional[str] = None,
        upd_stkpc_tp: str = "1",
    ) -> pd.DataFrame:
        """
        일봉 차트를 DataFrame으로 반환

        Args:
            stk_cd: 종목코드
            base_dt: 기준일자 (YYYYMMDD)
            upd_stkpc_tp: 수정주가구분 — "1":수정주가(기본; 액면분할 등 기업행위 보정), "0":원주가

        Returns:
            OHLCV DataFrame
        """
        charts = await self.get_daily_chart(stk_cd, base_dt, upd_stkpc_tp)

        if not charts:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

        data = [
            {
                "date": c.dt,
                "open": c.open_prc,
                "high": c.high_prc,
                "low": c.low_prc,
                "close": c.clos_prc,
                "volume": c.acml_vol,
            }
            for c in charts
        ]

        df = pd.DataFrame(data)

        # Filter out rows with invalid dates before parsing
        df = df[df["date"].str.len() == 8]  # YYYYMMDD format
        if df.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["date"])  # Remove rows with unparseable dates
        df = df.sort_values("date").reset_index(drop=True)

        return df

    # ============================================================
    # 계좌 조회 API (kt00001, kt00004, ka10075, ka10076)
    # ============================================================

    async def get_cash_balance(self, qry_tp: str = "2") -> CashBalance:
        """
        예수금상세현황요청 (kt00001)

        Args:
            qry_tp: 조회구분 - "2":일반조회, "3":추정조회

        Returns:
            CashBalance 객체
        """
        # 캐시 조회
        cache_key = make_cache_key("cash_balance", qry_tp)
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._request(
            api_id="kt00001",
            endpoint="/api/dostk/acnt",
            data={"qry_tp": qry_tp},
        )

        # 공식 계약 키 (계좌.md kt00001): entr=예수금, ord_alow_amt=주문가능금액,
        # pymn_alow_amt=출금가능금액, d1_entra/d2_entra=D+1/D+2 추정예수금
        # (d1_pymn_alow_amt는 '출금'가능금액 — 감사 MINOR: 라벨과 값이 어긋났었음)
        cash_balance = CashBalance(
            dnca_tot_amt=self._parse_signed_price(result.get("entr")),
            ord_psbl_amt=self._parse_signed_price(result.get("ord_alow_amt")),
            sttl_psbk_amt=self._parse_signed_price(result.get("pymn_alow_amt")),
            d1_ord_psbl_amt=self._parse_signed_price(result.get("d1_entra")),
            d2_ord_psbl_amt=self._parse_signed_price(result.get("d2_entra")),
        )

        # 캐시 저장
        if self._cache:
            self._cache.set(cache_key, cash_balance)

        return cash_balance

    async def get_account_balance(
        self,
        qry_tp: str = "0",
        exchange: Exchange = Exchange.KRX,
        use_cache: bool = True,
    ) -> AccountBalance:
        """
        계좌평가현황요청 (kt00004)

        Args:
            qry_tp: 상장폐지조회구분 - "0":전체, "1":상장폐지종목제외
            exchange: 거래소 구분
            use_cache: False면 30s 캐시를 우회한다 — 브로커-로컬 리컨실러는
                체결 폴 직후의 최신 잔고를 봐야 하므로 캐시를 건너뛴다.
                스테일 스냅샷은 방금 등록된 포지션을 '외부 매도'로 오판해
                제거·재채택을 반복시킨다 (get_filled_orders와 동일 패턴;
                F3 t6 리뷰 M1).

        Returns:
            AccountBalance 객체
        """
        # 캐시 조회
        cache_key = make_cache_key("account_balance", qry_tp, exchange.value)
        if self._cache and use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._request(
            api_id="kt00004",
            endpoint="/api/dostk/acnt",
            data={
                "qry_tp": qry_tp,
                "dmst_stex_tp": exchange.value,
            },
        )

        # 응답 파싱 — 공식 계약 키 (계좌.md kt00004 응답 사양; 감사 C4/C5/M1)
        # 보유종목 리스트: stk_acnt_evlt_prst, 아이템 키 rmnd_qty/avg_prc/pl_amt/pl_rt
        holdings_data = result.get("stk_acnt_evlt_prst", [])
        if not isinstance(holdings_data, list):
            holdings_data = []

        holdings = [
            Holding(
                stk_cd=self._strip_stock_prefix(h.get("stk_cd", "")),
                stk_nm=h.get("stk_nm", ""),
                hldg_qty=int(h.get("rmnd_qty") or 0),
                avg_buy_prc=self._parse_signed_price(h.get("avg_prc")),
                cur_prc=self._parse_signed_price(h.get("cur_prc")),
                evlu_amt=self._parse_signed_price(h.get("evlt_amt")),
                # 손익은 부호 보존 (음수 손실이 abs로 뒤집히면 안 됨)
                evlu_pfls_amt=self._parse_change(h.get("pl_amt")),
                evlu_pfls_rt=self._parse_float(h.get("pl_rt")),
            )
            for h in holdings_data
        ]

        # 합계: tot_est_amt=유가잔고평가액(주식만; aset_evlt_amt는 예수금 포함이라
        # total_value에서 현금 이중 계상됨). kt00004에 평가손익 합계 필드는 없어
        # 정의대로 계산한다 (lspft_amt는 '누적투자원금' — 손익이 아님).
        pchs_amt = self._parse_signed_price(result.get("tot_pur_amt"))
        evlu_amt = self._parse_signed_price(result.get("tot_est_amt"))
        evlu_pfls_amt = evlu_amt - pchs_amt
        account_balance = AccountBalance(
            pchs_amt=pchs_amt,
            evlu_amt=evlu_amt,
            evlu_pfls_amt=evlu_pfls_amt,
            evlu_pfls_rt=(evlu_pfls_amt / pchs_amt * 100.0) if pchs_amt else 0.0,
            d2_ord_psbl_amt=self._parse_signed_price(result.get("d2_entra")),
            holdings=holdings,
        )

        # 캐시 저장
        if self._cache:
            self._cache.set(cache_key, account_balance)

        return account_balance

    async def get_pending_orders(
        self,
        trde_tp: str = "0",
        stex_tp: str = "0",
        stk_cd: Optional[str] = None,
    ) -> list[PendingOrder]:
        """
        미체결요청 (ka10075)

        공식 계약 (계좌.md:441-447; 감사 C6):
        - all_stk_tp: 0=전체, 1=종목 — stk_cd 지정 여부로 자동 결정
        - trde_tp: 0=전체, 1=매도, 2=매수
        - stex_tp: 0=통합, 1=KRX, 2=NXT (1자리 코드)

        Args:
            trde_tp: 매매구분 - "0":전체, "1":매도, "2":매수
            stex_tp: 거래소구분 - "0":통합, "1":KRX, "2":NXT
            stk_cd: 지정 시 해당 종목만 조회

        Returns:
            PendingOrder 리스트
        """
        # 캐시 조회
        cache_key = make_cache_key("pending_orders", trde_tp, stex_tp, stk_cd or "")
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        data = {
            "all_stk_tp": "1" if stk_cd else "0",
            "trde_tp": trde_tp,
            "stex_tp": stex_tp,
        }
        if stk_cd:
            data["stk_cd"] = stk_cd

        result = await self._request(
            api_id="ka10075",
            endpoint="/api/dostk/acnt",
            data=data,
        )

        # 응답 리스트 키는 oso (계좌.md:463); 아이템 키 ord_pric/cntr_qty/oso_qty/tm
        output = result.get("oso", [])
        if not isinstance(output, list):
            output = [output] if output else []

        pending_orders = [
            PendingOrder(
                ord_no=item.get("ord_no", ""),
                stk_cd=self._strip_stock_prefix(item.get("stk_cd", "")),
                stk_nm=item.get("stk_nm", ""),
                ord_qty=int(item.get("ord_qty") or 0),
                ord_uv=self._parse_signed_price(item.get("ord_pric")),
                ccld_qty=int(item.get("cntr_qty") or 0),
                rmn_qty=int(item.get("oso_qty") or 0),
                ord_dt="",  # ka10075 응답에 주문일자 필드 없음
                ord_tm=item.get("tm", ""),
                buy_sell_tp=self._normalize_buy_sell(
                    item.get("trde_tp"), item.get("io_tp_nm")
                ),
            )
            for item in output
        ]

        # 캐시 저장
        if self._cache:
            self._cache.set(cache_key, pending_orders)

        return pending_orders

    async def get_realized_pnl(
        self,
        strt_dt: Optional[str] = None,
        end_dt: Optional[str] = None,
    ) -> RealizedPnl:
        """
        일자별실현손익요청 (ka10074)

        daily-loss 브레이커(당일)와 성과 리포트(기간)의 데이터 소스.
        스펙 주의: 실현손익이 발생한 일자만 데이터가 채워진다 — 무거래
        기간이면 합계 0 + 빈 리스트가 정상이다. 손익은 부호를 보존한다.

        Args:
            strt_dt: 시작일자 YYYYMMDD (기본: 오늘 KST)
            end_dt: 종료일자 YYYYMMDD (기본: strt_dt)

        Returns:
            RealizedPnl 객체
        """
        if strt_dt is None:
            strt_dt = datetime.now(KST).strftime("%Y%m%d")
        if end_dt is None:
            end_dt = strt_dt

        # 캐시 조회 (당일 값은 체결마다 변함 — 계좌 계열 짧은 TTL 사용)
        cache_key = make_cache_key("realized_pnl", strt_dt, end_dt)
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._request(
            api_id="ka10074",
            endpoint="/api/dostk/acnt",
            data={"strt_dt": strt_dt, "end_dt": end_dt},
        )

        rows = result.get("dt_rlzt_pl", [])
        if not isinstance(rows, list):
            rows = [rows] if rows else []

        pnl = RealizedPnl(
            strt_dt=strt_dt,
            end_dt=end_dt,
            total_buy_amount=self._parse_signed_price(result.get("tot_buy_amt")),
            total_sell_amount=self._parse_signed_price(result.get("tot_sell_amt")),
            realized_pnl=self._parse_change(result.get("rlzt_pl")),
            commission=self._parse_signed_price(result.get("trde_cmsn")),
            tax=self._parse_signed_price(result.get("trde_tax")),
            daily=[
                DailyRealizedPnlRow(
                    dt=row.get("dt", ""),
                    buy_amount=self._parse_signed_price(row.get("buy_amt")),
                    sell_amount=self._parse_signed_price(row.get("sell_amt")),
                    sell_pnl=self._parse_change(row.get("tdy_sel_pl")),
                    commission=self._parse_signed_price(row.get("tdy_trde_cmsn")),
                    tax=self._parse_signed_price(row.get("tdy_trde_tax")),
                )
                for row in rows
            ],
        )

        if self._cache:
            self._cache.set(cache_key, pnl)

        return pnl

    @staticmethod
    def _normalize_buy_sell(trde_tp: Optional[str], io_tp_nm: Optional[str]) -> str:
        """매수/매도를 소비자 계약("1"=매수, "2"=매도)으로 정규화.

        ka10075/ka10076의 trde_tp는 1=매도, 2=매수로 소비자 계약과 **반대**다
        (계좌.md:445; 감사 C6의 반전 발견). io_tp_nm 텍스트("+매수"/"-매도")를
        우선 신뢰하고, 없으면 trde_tp 코드를 뒤집어 매핑한다.
        """
        name = io_tp_nm or ""
        if "매수" in name:
            return "1"
        if "매도" in name:
            return "2"
        if trde_tp == "2":
            return "1"  # 스펙 2=매수
        if trde_tp == "1":
            return "2"  # 스펙 1=매도
        return ""

    async def get_filled_orders(
        self,
        sell_tp: str = "0",
        stex_tp: str = "0",
        stk_cd: Optional[str] = None,
        use_cache: bool = True,
    ) -> list[FilledOrder]:
        """
        체결요청 (ka10076)

        공식 계약 (계좌.md:626-631; 감사 C7): qry_tp/sell_tp/stex_tp는 필수 —
        누락 시 서버가 요청을 거부한다 (모의서버 실증: "필수입력 파라미터=qry_tp").

        Args:
            sell_tp: 매도수구분 - "0":전체, "1":매도, "2":매수
            stex_tp: 거래소구분 - "0":통합, "1":KRX, "2":NXT
            stk_cd: 지정 시 해당 종목만 조회
            use_cache: False면 5s 캐시를 우회한다 — 주문 체결 확인 폴링 루프는
                매 폴에서 최신 체결을 봐야 하므로 캐시를 건너뛴다 (R5-P1 리뷰 #1).

        Returns:
            FilledOrder 리스트
        """
        # 캐시 조회
        cache_key = make_cache_key("filled_orders", sell_tp, stex_tp, stk_cd or "")
        if self._cache and use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        data = {
            "qry_tp": "1" if stk_cd else "0",
            "sell_tp": sell_tp,
            "stex_tp": stex_tp,
        }
        if stk_cd:
            data["stk_cd"] = stk_cd

        result = await self._request(
            api_id="ka10076",
            endpoint="/api/dostk/acnt",
            data=data,
        )

        # 응답 리스트 키는 cntr (계좌.md:647); 체결금액/체결일자 필드는 응답에
        # 없으므로 금액은 체결량×체결가로 계산하고 일자는 빈 값으로 둔다.
        output = result.get("cntr", [])
        if not isinstance(output, list):
            output = [output] if output else []

        filled_orders = []
        for item in output:
            ccld_qty = int(item.get("cntr_qty") or 0)
            ccld_uv = self._parse_signed_price(item.get("cntr_pric"))
            filled_orders.append(
                FilledOrder(
                    ord_no=item.get("ord_no", ""),
                    stk_cd=self._strip_stock_prefix(item.get("stk_cd", "")),
                    stk_nm=item.get("stk_nm", ""),
                    ccld_qty=ccld_qty,
                    ccld_uv=ccld_uv,
                    ccld_amt=ccld_qty * ccld_uv,
                    ccld_dt="",  # ka10076 응답에 체결일자 필드 없음
                    ccld_tm=item.get("ord_tm", ""),
                    buy_sell_tp=self._normalize_buy_sell(
                        item.get("trde_tp"), item.get("io_tp_nm")
                    ),
                )
            )

        # 캐시 저장
        if self._cache:
            self._cache.set(cache_key, filled_orders)

        return filled_orders

    # ============================================================
    # 주문 API (kt10000~kt10003)
    # ============================================================

    async def place_buy_order(
        self,
        stk_cd: str,
        qty: int,
        price: Optional[int] = None,
        order_type: OrderType = OrderType.MARKET,
        exchange: Exchange = Exchange.KRX,
    ) -> OrderResponse:
        """
        주식 매수주문 (kt10000)

        Args:
            stk_cd: 종목코드
            qty: 주문수량
            price: 주문가격 (시장가 주문 시 생략)
            order_type: 주문유형
            exchange: 거래소

        Returns:
            OrderResponse 객체
        """
        request = OrderRequest(
            dmst_stex_tp=exchange,
            stk_cd=stk_cd,
            ord_qty=qty,
            ord_uv=price,
            trde_tp=order_type,
        )

        result = await self._request(
            api_id="kt10000",
            endpoint="/api/dostk/ordr",
            data=request.to_api_dict(),
        )

        # 주문 성공 시 계좌 관련 캐시 무효화
        if self._cache:
            self._cache.invalidate_account_cache()

        return OrderResponse(
            ord_no=result.get("ord_no", ""),
            base_orig_ord_no=result.get("base_orig_ord_no"),
            dmst_stex_tp=result.get("dmst_stex_tp"),
            return_code=int(result.get("return_code", 0)),
            return_msg=result.get("return_msg", ""),
        )

    async def place_sell_order(
        self,
        stk_cd: str,
        qty: int,
        price: Optional[int] = None,
        order_type: OrderType = OrderType.MARKET,
        exchange: Exchange = Exchange.KRX,
    ) -> OrderResponse:
        """
        주식 매도주문 (kt10001)

        Args:
            stk_cd: 종목코드
            qty: 주문수량
            price: 주문가격 (시장가 주문 시 생략)
            order_type: 주문유형
            exchange: 거래소

        Returns:
            OrderResponse 객체
        """
        request = OrderRequest(
            dmst_stex_tp=exchange,
            stk_cd=stk_cd,
            ord_qty=qty,
            ord_uv=price,
            trde_tp=order_type,
        )

        result = await self._request(
            api_id="kt10001",
            endpoint="/api/dostk/ordr",
            data=request.to_api_dict(),
        )

        # 주문 성공 시 계좌 관련 캐시 무효화
        if self._cache:
            self._cache.invalidate_account_cache()

        return OrderResponse(
            ord_no=result.get("ord_no", ""),
            base_orig_ord_no=result.get("base_orig_ord_no"),
            dmst_stex_tp=result.get("dmst_stex_tp"),
            return_code=int(result.get("return_code", 0)),
            return_msg=result.get("return_msg", ""),
        )

    async def modify_order(
        self,
        org_ord_no: str,
        stk_cd: str,
        qty: int,
        price: int,
        exchange: Exchange = Exchange.KRX,
    ) -> OrderResponse:
        """
        주식 정정주문 (kt10002)

        공식 계약 (주문.md:185-194; 감사 C1): 필드는 orig_ord_no/stk_cd/
        mdfy_qty/mdfy_uv/dmst_stex_tp — trde_tp는 kt10002에 존재하지 않는다.

        Args:
            org_ord_no: 원주문번호
            stk_cd: 종목코드
            qty: 정정수량
            price: 정정단가
            exchange: 거래소

        Returns:
            OrderResponse 객체
        """
        data = {
            "orig_ord_no": org_ord_no,
            "dmst_stex_tp": exchange.value,
            "stk_cd": stk_cd,
            "mdfy_qty": str(qty),
            "mdfy_uv": str(price),
        }

        result = await self._request(
            api_id="kt10002",
            endpoint="/api/dostk/ordr",
            data=data,
        )

        # 주문 정정 시 계좌 관련 캐시 무효화
        if self._cache:
            self._cache.invalidate_account_cache()

        return OrderResponse(
            ord_no=result.get("ord_no", ""),
            base_orig_ord_no=result.get("base_orig_ord_no"),
            dmst_stex_tp=result.get("dmst_stex_tp"),
            return_code=int(result.get("return_code", 0)),
            return_msg=result.get("return_msg", ""),
        )

    async def cancel_order(
        self,
        org_ord_no: str,
        stk_cd: str,
        qty: int = 0,
        exchange: Exchange = Exchange.KRX,
    ) -> OrderResponse:
        """
        주식 취소주문 (kt10003)

        공식 계약 (주문.md:263-268; 감사 C2): 필드는 orig_ord_no/stk_cd/
        cncl_qty/dmst_stex_tp. cncl_qty '0'은 잔량 전부 취소.

        Args:
            org_ord_no: 원주문번호
            stk_cd: 종목코드
            qty: 취소수량 (0=잔량 전부 취소, 기본값)
            exchange: 거래소

        Returns:
            OrderResponse 객체
        """
        data = {
            "orig_ord_no": org_ord_no,
            "dmst_stex_tp": exchange.value,
            "stk_cd": stk_cd,
            "cncl_qty": str(qty),
        }

        result = await self._request(
            api_id="kt10003",
            endpoint="/api/dostk/ordr",
            data=data,
        )

        # 주문 취소 시 계좌 관련 캐시 무효화
        if self._cache:
            self._cache.invalidate_account_cache()

        return OrderResponse(
            ord_no=result.get("ord_no", ""),
            base_orig_ord_no=result.get("base_orig_ord_no"),
            dmst_stex_tp=result.get("dmst_stex_tp"),
            return_code=int(result.get("return_code", 0)),
            return_msg=result.get("return_msg", ""),
        )

    # ============================================================
    # 편의 메서드
    # ============================================================

    async def get_current_price(self, stk_cd: str) -> int:
        """
        현재가 간편 조회

        Args:
            stk_cd: 종목코드

        Returns:
            현재가 (원)
        """
        info = await self.get_stock_info(stk_cd)
        return info.cur_prc

    async def buy_market_order(self, stk_cd: str, qty: int) -> OrderResponse:
        """
        시장가 매수 간편 메서드

        Args:
            stk_cd: 종목코드
            qty: 수량

        Returns:
            OrderResponse
        """
        return await self.place_buy_order(stk_cd, qty, order_type=OrderType.MARKET)

    async def sell_market_order(self, stk_cd: str, qty: int) -> OrderResponse:
        """
        시장가 매도 간편 메서드

        Args:
            stk_cd: 종목코드
            qty: 수량

        Returns:
            OrderResponse
        """
        return await self.place_sell_order(stk_cd, qty, order_type=OrderType.MARKET)

    @property
    def rate_limiter(self) -> Optional[KiwoomRateLimiter]:
        """Rate Limiter 인스턴스 (통계 조회용)"""
        return self._rate_limiter

    @property
    def rate_limiter_stats(self) -> dict:
        """
        Rate Limiter 통계 조회

        Returns:
            통계 딕셔너리 (query_count, order_count, total_wait_time 등)
        """
        if self._rate_limiter:
            return self._rate_limiter.stats
        return {"enabled": False}

    @property
    def cache(self) -> Optional[KiwoomCache]:
        """Cache 인스턴스 (통계 조회 및 직접 제어용)"""
        return self._cache

    @property
    def cache_stats(self) -> dict:
        """
        Cache 통계 조회

        Returns:
            통계 딕셔너리 (hits, misses, hit_rate, size 등)
        """
        if self._cache:
            return self._cache.stats
        return {"enabled": False}

    def invalidate_cache(self) -> int:
        """
        모든 캐시 무효화

        Returns:
            삭제된 엔트리 수
        """
        if self._cache:
            return self._cache.clear()
        return 0

    # ===========================================
    # 종목 목록 조회 API (ka10099)
    # ===========================================

    async def get_stock_list(
        self,
        market_type: MarketType = MarketType.KOSPI,
    ) -> list[StockListItem]:
        """
        종목 정보 리스트 조회 (ka10099)

        전체 KOSPI/KOSDAQ 종목 목록을 조회합니다.
        연속 조회를 자동으로 처리하여 전체 목록을 반환합니다.

        Args:
            market_type: 시장 구분 (KOSPI, KOSDAQ, ETF 등)

        Returns:
            StockListItem 리스트
        """
        cache_key = make_cache_key("stock_list", market_type.value)

        # 캐시 확인 (1시간 유효)
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached:
                return cached

        all_items: list[StockListItem] = []
        cont_yn = "N"
        next_key = ""

        while True:
            response, continuation = await self._request(
                api_id="ka10099",
                endpoint="/api/dostk/stkinfo",
                data={"mrkt_tp": market_type.value},
                cont_yn=cont_yn if cont_yn == "Y" else "",
                next_key=next_key if cont_yn == "Y" else "",
                with_continuation=True,
            )

            # 응답 파싱
            output = response.get("output", response)
            items = output.get("list", [])

            for item in items:
                try:
                    # 상장주식수 파싱 (문자열 -> 정수)
                    list_count_str = item.get("listCount", "0")
                    list_count = int(list_count_str) if list_count_str else None

                    stock_item = StockListItem(
                        code=item.get("code", ""),
                        name=item.get("name", ""),
                        market_code=item.get("marketCode", ""),
                        market_name=item.get("marketName", ""),
                        list_count=list_count,
                        state=item.get("state", ""),
                        order_warning=item.get("orderWarning", "0"),
                    )

                    # 유효한 종목만 추가 (코드가 있고 6자리인 경우)
                    if stock_item.code and len(stock_item.code) == 6:
                        all_items.append(stock_item)

                except Exception as e:
                    logger.warning(
                        "stock_list_item_parse_error",
                        item=item,
                        error=str(e),
                    )

            # 연속 조회 확인 (응답 HTTP 헤더 기반 — 공식 계약)
            cont_yn = continuation["cont_yn"]
            next_key = continuation["next_key"]

            if cont_yn != "Y":
                break

            # Rate limit 대기
            await asyncio.sleep(0.3)

        logger.info(
            "stock_list_fetched",
            market_type=market_type.value,
            count=len(all_items),
        )

        # 캐시 저장 (1시간)
        if self._cache and all_items:
            self._cache.set(cache_key, all_items, ttl=3600)

        return all_items

    async def get_all_stocks(
        self,
        include_kospi: bool = True,
        include_kosdaq: bool = True,
        exclude_warnings: bool = True,
        exclude_etf_etn: bool = True,
    ) -> list[StockListItem]:
        """
        KOSPI/KOSDAQ 전체 종목 조회

        Args:
            include_kospi: 코스피 포함 여부
            include_kosdaq: 코스닥 포함 여부
            exclude_warnings: 투자주의/경고 종목 제외 여부
            exclude_etf_etn: ETN/스팩/채권 파생상품 이름 패턴 제외 여부
                (DQ-1 — ETF/리츠/ELW는 mrkt_tp 쿼리에서 이미 구조적으로
                제외되므로 대상 아님). 기본 True — 현재 유일한 콜사이트인
                discovery 스캐너(_load_stock_list)가 원하는 거동이며, 이
                파라미터를 명시하지 않는 다른 잠재 소비자도 오염된 유니버스보다
                안전한 쪽(제외)을 기본으로 받는다. False로 넘기면 이름 필터
                없이 기존 거동(byte-불변) 그대로 유지된다.

        Returns:
            StockListItem 리스트
        """
        all_stocks: list[StockListItem] = []

        if include_kospi:
            kospi_stocks = await self.get_stock_list(MarketType.KOSPI)
            all_stocks.extend(kospi_stocks)

        if include_kosdaq:
            kosdaq_stocks = await self.get_stock_list(MarketType.KOSDAQ)
            all_stocks.extend(kosdaq_stocks)

        if exclude_warnings:
            all_stocks = [s for s in all_stocks if s.is_normal]

        if exclude_etf_etn:
            all_stocks = [
                s for s in all_stocks if not _ETF_ETN_NAME_RE.search(s.name)
            ]

        # 중복 제거 (코드 기준)
        seen = set()
        unique_stocks = []
        for stock in all_stocks:
            if stock.code not in seen:
                seen.add(stock.code)
                unique_stocks.append(stock)

        logger.info(
            "all_stocks_fetched",
            total=len(unique_stocks),
            kospi=include_kospi,
            kosdaq=include_kosdaq,
            exclude_etf_etn=exclude_etf_etn,
        )

        return unique_stocks