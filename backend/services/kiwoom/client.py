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
from typing import Optional

import httpx
import pandas as pd
import structlog

from .auth import KiwoomAuth
from .cache import KiwoomCache, make_cache_key
from .errors import KiwoomError, KiwoomErrorCode, KiwoomNetworkError, KiwoomRateLimitError
from .rate_limiter import KiwoomRateLimiter, get_request_type
from .models import (
    AccountBalance,
    CashBalance,
    ChartData,
    Exchange,
    FilledOrder,
    Holding,
    Orderbook,
    OrderbookUnit,
    OrderRequest,
    OrderResponse,
    OrderType,
    PendingOrder,
    StockBasicInfo,
)

logger = structlog.get_logger()


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
    ) -> dict:
        """
        공통 API 요청 메서드 (429 에러 시 자동 재시도)

        Args:
            api_id: API ID (예: ka10001)
            endpoint: API endpoint (예: /api/dostk/stkinfo)
            data: Request body
            cont_yn: 연속조회여부 (Y/N)
            next_key: 연속조회키

        Returns:
            API 응답 딕셔너리

        Raises:
            KiwoomError: API 에러
            KiwoomNetworkError: 네트워크 에러
            KiwoomRateLimitError: Rate limit 초과 (재시도 후에도 실패)
        """
        last_error: Optional[Exception] = None

        for attempt in range(self.MAX_RETRY_ATTEMPTS):
            try:
                return await self._request_once(api_id, endpoint, data, cont_yn, next_key)
            except KiwoomError as e:
                # Check if it's a rate limit error (1700 code in message)
                if "1700" in str(e) or "429" in str(e) or "허용된 요청 개수" in str(e):
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
                else:
                    # Non-rate-limit error, don't retry
                    raise

        # All retries exhausted
        logger.error(
            "kiwoom_rate_limit_exhausted",
            api_id=api_id,
            attempts=self.MAX_RETRY_ATTEMPTS,
        )
        raise last_error or KiwoomRateLimitError(
            message="Rate limit 재시도 횟수 초과",
        )

    async def _request_once(
        self,
        api_id: str,
        endpoint: str,
        data: Optional[dict] = None,
        cont_yn: str = "",
        next_key: str = "",
    ) -> dict:
        """
        단일 API 요청 메서드

        Args:
            api_id: API ID (예: ka10001)
            endpoint: API endpoint (예: /api/dostk/stkinfo)
            data: Request body
            cont_yn: 연속조회여부 (Y/N)
            next_key: 연속조회키

        Returns:
            API 응답 딕셔너리
        """
        # Rate Limiting (이용약관 제11조)
        if self._rate_limiter:
            request_type = get_request_type(api_id)
            acquired = await self._rate_limiter.acquire(request_type)
            if not acquired:
                raise KiwoomRateLimitError(
                    message="Rate limit 대기 시간 초과",
                )

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

            result = response.json()

            # 에러 체크
            return_code = result.get("return_code")
            if return_code is not None:
                if isinstance(return_code, str):
                    return_code = int(return_code) if return_code.lstrip("-").isdigit() else 0

                if return_code != 0:
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

            return result

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
        """실수 파싱"""
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        value = str(value).strip().replace("+", "").replace(",", "")
        if not value:
            return 0.0
        return float(value)

    async def get_stock_info(self, stk_cd: str) -> StockBasicInfo:
        """
        주식기본정보요청 (ka10001)

        Args:
            stk_cd: 종목코드 (예: "005930")

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
            acml_tr_pbmn=self._parse_signed_price(output.get("acml_tr_pbmn", 0)),
            strt_prc=self._parse_signed_price(output.get("open_pric", output.get("strt_prc", 0))),
            high_prc=self._parse_signed_price(output.get("high_pric", output.get("high_prc", 0))),
            low_prc=self._parse_signed_price(output.get("low_pric", output.get("low_prc", 0))),
            stk_hgpr=self._parse_signed_price(output.get("upl_pric", output.get("stk_hgpr", 0))),
            stk_lwpr=self._parse_signed_price(output.get("lst_pric", output.get("stk_lwpr", 0))),
            per=self._parse_float(output.get("per")) if output.get("per") else None,
            pbr=self._parse_float(output.get("pbr")) if output.get("pbr") else None,
            eps=int(self._parse_float(output.get("eps"))) if output.get("eps") else None,
            bps=int(self._parse_float(output.get("bps"))) if output.get("bps") else None,
            lstg_stqt=self._parse_signed_price(output.get("lstg_stqt")) if output.get("lstg_stqt") else None,
            mrkt_tot_amt=self._parse_signed_price(output.get("mac", output.get("mrkt_tot_amt"))) if output.get("mac") or output.get("mrkt_tot_amt") else None,
        )

        # 캐시 저장
        if self._cache:
            self._cache.set(cache_key, stock_info)

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

        # 매도호가 파싱
        sell_hogas = []
        for i in range(1, 11):
            price = output.get(f"sell_hoga_{i}", output.get(f"ofr_prc{i}", 0))
            qty = output.get(f"sell_hoga_qty_{i}", output.get(f"ofr_qty{i}", 0))
            if price:
                sell_hogas.append(OrderbookUnit(price=int(price), quantity=int(qty)))

        # 매수호가 파싱
        buy_hogas = []
        for i in range(1, 11):
            price = output.get(f"buy_hoga_{i}", output.get(f"bid_prc{i}", 0))
            qty = output.get(f"buy_hoga_qty_{i}", output.get(f"bid_qty{i}", 0))
            if price:
                buy_hogas.append(OrderbookUnit(price=int(price), quantity=int(qty)))

        orderbook = Orderbook(
            stk_cd=stk_cd,
            sell_hogas=sell_hogas,
            buy_hogas=buy_hogas,
            tot_sell_qty=int(output.get("tot_sell_qty", output.get("total_ofr_qty", 0))),
            tot_buy_qty=int(output.get("tot_buy_qty", output.get("total_bid_qty", 0))),
        )

        # 캐시 저장
        if self._cache:
            self._cache.set(cache_key, orderbook)

        return orderbook

    async def get_daily_chart(
        self,
        stk_cd: str,
        base_dt: Optional[str] = None,
        upd_stkpc_tp: str = "0",
    ) -> list[ChartData]:
        """
        주식일봉차트조회요청 (ka10081)

        Args:
            stk_cd: 종목코드
            base_dt: 기준일자 (YYYYMMDD), None이면 오늘
            upd_stkpc_tp: 수정주가구분 ("0" or "1")

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
                acml_tr_pbmn=self._parse_signed_price(item.get("trde_prica")) if item.get("trde_prica") else None,
            )
            for item in output
        ]

        # 캐시 저장
        if self._cache:
            self._cache.set(cache_key, chart_data)

        return chart_data

    async def get_daily_chart_df(
        self,
        stk_cd: str,
        base_dt: Optional[str] = None,
        upd_stkpc_tp: str = "0",
    ) -> pd.DataFrame:
        """
        일봉 차트를 DataFrame으로 반환

        Args:
            stk_cd: 종목코드
            base_dt: 기준일자 (YYYYMMDD)
            upd_stkpc_tp: 수정주가구분 ("0" or "1")

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

        # API 응답 필드명 매핑 (문서와 실제 응답이 다름)
        # entr: 예수금, ord_alow_amt: 주문가능금액, pymn_alow_amt: 출금가능금액
        cash_balance = CashBalance(
            dnca_tot_amt=self._parse_signed_price(result.get("entr", result.get("dnca_tot_amt", 0))),
            ord_psbl_amt=self._parse_signed_price(result.get("ord_alow_amt", result.get("ord_psbl_amt", 0))),
            sttl_psbk_amt=self._parse_signed_price(result.get("pymn_alow_amt", result.get("sttl_psbk_amt", 0))),
            d1_ord_psbl_amt=self._parse_signed_price(result.get("d1_pymn_alow_amt", result.get("d1_ord_psbl_amt", 0))),
            d2_ord_psbl_amt=self._parse_signed_price(result.get("d2_pymn_alow_amt", result.get("d2_ord_psbl_amt", 0))),
        )

        # 캐시 저장
        if self._cache:
            self._cache.set(cache_key, cash_balance)

        return cash_balance

    async def get_account_balance(
        self,
        qry_tp: str = "0",
        exchange: Exchange = Exchange.KRX,
    ) -> AccountBalance:
        """
        계좌평가현황요청 (kt00004)

        Args:
            qry_tp: 상장폐지조회구분 - "0":전체, "1":상장폐지종목제외
            exchange: 거래소 구분

        Returns:
            AccountBalance 객체
        """
        # 캐시 조회
        cache_key = make_cache_key("account_balance", qry_tp, exchange.value)
        if self._cache:
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

        # API 응답 필드명 매핑 (문서와 실제 응답이 다름)
        # entr: 예수금, tot_pur_amt: 총매입금액, aset_evlt_amt: 자산평가금액
        # lspft_amt: 손익금액, lspft_rt: 손익률, d2_entra: D+2예수금

        # 보유 종목 파싱 (stk_acnt_evlt_prst 배열)
        holdings_data = result.get("stk_acnt_evlt_prst", result.get("output2", []))
        if not isinstance(holdings_data, list):
            holdings_data = []

        holdings = [
            Holding(
                stk_cd=h.get("stk_cd", ""),
                stk_nm=h.get("stk_nm", ""),
                hldg_qty=int(h.get("hldg_qty", h.get("hold_qty", 0))),
                avg_buy_prc=self._parse_signed_price(h.get("avg_buy_prc", h.get("pchs_avg_pric", h.get("avg_unpr", 0)))),
                cur_prc=self._parse_signed_price(h.get("cur_prc", h.get("prpr", h.get("now_pric", 0)))),
                evlu_amt=self._parse_signed_price(h.get("evlu_amt", h.get("evlt_amt", 0))),
                evlu_pfls_amt=self._parse_signed_price(h.get("evlu_pfls_amt", h.get("evlt_lspft_amt", 0))),
                evlu_pfls_rt=self._parse_float(h.get("evlu_pfls_rt", h.get("evlt_lspft_rt", 0))),
            )
            for h in holdings_data
        ]

        account_balance = AccountBalance(
            pchs_amt=self._parse_signed_price(result.get("tot_pur_amt", result.get("pchs_amt", 0))),
            evlu_amt=self._parse_signed_price(result.get("aset_evlt_amt", result.get("tot_est_amt", result.get("evlu_amt", 0)))),
            evlu_pfls_amt=self._parse_signed_price(result.get("lspft_amt", result.get("evlu_pfls_amt", 0))),
            evlu_pfls_rt=self._parse_float(result.get("lspft_rt", result.get("lspft_ratio", result.get("evlu_pfls_rt", 0)))),
            d2_ord_psbl_amt=self._parse_signed_price(result.get("d2_entra", result.get("d2_ord_psbl_amt", 0))),
            holdings=holdings,
        )

        # 캐시 저장
        if self._cache:
            self._cache.set(cache_key, account_balance)

        return account_balance

    async def get_pending_orders(
        self,
        all_stk_tp: str = "1",
        trde_tp: str = "0",
        stex_tp: str = "KRX",
    ) -> list[PendingOrder]:
        """
        미체결요청 (ka10075)

        Args:
            all_stk_tp: 전종목여부 - "0":특정종목, "1":전종목
            trde_tp: 거래구분 - "0":전체, "1":매수, "2":매도
            stex_tp: 거래소구분 - "KRX":한국거래소, "NXT":코넥스

        Returns:
            PendingOrder 리스트
        """
        # 캐시 조회
        cache_key = make_cache_key("pending_orders", all_stk_tp, trde_tp, stex_tp)
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._request(
            api_id="ka10075",
            endpoint="/api/dostk/acnt",
            data={
                "all_stk_tp": all_stk_tp,
                "trde_tp": trde_tp,
                "stex_tp": stex_tp,
            },
        )

        output = result.get("output", [])
        if not isinstance(output, list):
            output = [output] if output else []

        pending_orders = [
            PendingOrder(
                ord_no=item.get("ord_no", ""),
                stk_cd=item.get("stk_cd", ""),
                stk_nm=item.get("stk_nm", ""),
                ord_qty=int(item.get("ord_qty", 0)),
                ord_uv=int(item.get("ord_uv", 0)),
                ccld_qty=int(item.get("ccld_qty", 0)),
                rmn_qty=int(item.get("rmn_qty", 0)),
                ord_dt=item.get("ord_dt", ""),
                ord_tm=item.get("ord_tm", ""),
                buy_sell_tp=item.get("buy_sell_tp", ""),
            )
            for item in output
        ]

        # 캐시 저장
        if self._cache:
            self._cache.set(cache_key, pending_orders)

        return pending_orders

    async def get_filled_orders(self) -> list[FilledOrder]:
        """
        체결요청 (ka10076)

        Returns:
            FilledOrder 리스트
        """
        # 캐시 조회
        cache_key = make_cache_key("filled_orders")
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._request(
            api_id="ka10076",
            endpoint="/api/dostk/acnt",
            data={},
        )

        output = result.get("output", [])
        if not isinstance(output, list):
            output = [output] if output else []

        filled_orders = [
            FilledOrder(
                ord_no=item.get("ord_no", ""),
                stk_cd=item.get("stk_cd", ""),
                stk_nm=item.get("stk_nm", ""),
                ccld_qty=int(item.get("ccld_qty", 0)),
                ccld_uv=int(item.get("ccld_uv", 0)),
                ccld_amt=int(item.get("ccld_amt", 0)),
                ccld_dt=item.get("ccld_dt", ""),
                ccld_tm=item.get("ccld_tm", ""),
                buy_sell_tp=item.get("buy_sell_tp", ""),
            )
            for item in output
        ]

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
        order_type: OrderType = OrderType.LIMIT,
        exchange: Exchange = Exchange.KRX,
    ) -> OrderResponse:
        """
        주식 정정주문 (kt10002)

        Args:
            org_ord_no: 원주문번호
            stk_cd: 종목코드
            qty: 정정수량
            price: 정정가격
            order_type: 주문유형
            exchange: 거래소

        Returns:
            OrderResponse 객체
        """
        data = {
            "org_ord_no": org_ord_no,
            "dmst_stex_tp": exchange.value,
            "stk_cd": stk_cd,
            "ord_qty": str(qty),
            "ord_uv": str(price),
            "trde_tp": order_type.value,
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
            dmst_stex_tp=result.get("dmst_stex_tp"),
            return_code=int(result.get("return_code", 0)),
            return_msg=result.get("return_msg", ""),
        )

    async def cancel_order(
        self,
        org_ord_no: str,
        stk_cd: str,
        qty: int,
        exchange: Exchange = Exchange.KRX,
    ) -> OrderResponse:
        """
        주식 취소주문 (kt10003)

        Args:
            org_ord_no: 원주문번호
            stk_cd: 종목코드
            qty: 취소수량
            exchange: 거래소

        Returns:
            OrderResponse 객체
        """
        data = {
            "org_ord_no": org_ord_no,
            "dmst_stex_tp": exchange.value,
            "stk_cd": stk_cd,
            "ord_qty": str(qty),
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