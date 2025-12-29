# Kiwoom REST API 구현 계획서

## 1. 개요

### 1.1 목표
- Kiwoom REST API를 통한 한국 주식 거래 기능 구현
- 모의투자(MockInvest) 환경에서 먼저 테스트 후 실서버 전환
- 기존 미국 주식(yfinance) 구조를 확장하여 한국 주식 지원

### 1.2 현재 상태
- 미국 주식: yfinance 기반 완전 구현 ✅
- 한국 주식: 미구현 ❌

### 1.3 Kiwoom REST API 정보
| 항목 | 내용 |
|------|------|
| 공식 포털 | https://openapi.kiwoom.com |
| 실서버 API | https://api.kiwoom.com |
| 모의투자 API | https://mockapi.kiwoom.com (KRX만 지원) |
| 인증 방식 | OAuth2 (client_credentials) |
| Format | JSON |
| Content-Type | application/json;charset=UTF-8 |

---

## 2. API 명세서 분석 결과 (KiwoomRESTAPI.xlsx)

### 2.1 전체 API 통계

| 대분류 | API 수 | 주요 기능 |
|--------|--------|----------|
| OAuth 인증 | 2 | 토큰 발급/폐기 |
| 종목정보 | 40+ | 기본정보, 거래원, 체결정보 |
| 시세 | 25+ | 호가, 일/분/틱 차트, 현재가 |
| 차트 | 15+ | 틱/분/일/주/월/년봉 |
| 계좌 | 25+ | 잔고, 예수금, 체결내역 |
| 주문 | 8 | 매수/매도/정정/취소 |
| 순위정보 | 20+ | 거래량, 등락률, 외인매매 |
| 실시간시세 | 19 | WebSocket (체결, 호가, VI) |
| 기타 | 50+ | ELW, ETF, 금현물, 테마 |
| **총계** | **207** | |

### 2.2 핵심 API 상세 스펙

#### 2.2.1 OAuth 인증 - 접근토큰 발급 (au10001)

```
POST /oauth2/token
Content-Type: application/json;charset=UTF-8

Header:
  api-id: au10001 (필수)

Request Body:
  grant_type: "client_credentials" (필수)
  appkey: 앱키 (필수)
  secretkey: 시크릿키 (필수)

Response Body:
  expires_dt: 만료일 (String)
  token_type: 토큰타입 (String)
  token: 접근토큰 (String)
  return_code: 응답코드 (String)
  return_msg: 응답메시지 (String)
```

#### 2.2.2 주식 매수주문 (kt10000)

```
POST /api/dostk/ordr
Content-Type: application/json;charset=UTF-8

Header:
  api-id: kt10000 (필수)
  authorization: Bearer {token} (필수)
  cont-yn: 연속조회여부 (선택)
  next-key: 연속조회키 (선택)

Request Body:
  dmst_stex_tp: 거래소구분 - "KRX" | "NXT" | "SOR" (필수)
  stk_cd: 종목코드 - "005930" (필수, 12자리)
  ord_qty: 주문수량 (필수, 12자리)
  ord_uv: 주문단가 (선택, 시장가 시 생략)
  trde_tp: 매매구분 (필수) - 아래 코드 참조
  cond_uv: 조건단가 (선택)

매매구분 코드 (trde_tp):
  0: 보통
  3: 시장가
  5: 조건부지정가
  6: 최유리지정가
  7: 최우선지정가
  10: 보통(IOC)
  13: 시장가(IOC)
  16: 최유리(IOC)
  20: 보통(FOK)
  23: 시장가(FOK)
  26: 최유리(FOK)
  28: 스톱지정가
  29: 중간가
  61: 장시작전시간외
  62: 시간외단일가
  81: 장마감후시간외

Response Body:
  ord_no: 주문번호 (String, 7자리)
  dmst_stex_tp: 거래소구분 (String)
  return_code: 응답코드
  return_msg: 응답메시지

예시:
Request: {"dmst_stex_tp": "KRX", "stk_cd": "005930", "ord_qty": "1", "ord_uv": "", "trde_tp": "3", "cond_uv": ""}
Response: {"ord_no": "00024", "return_code": 0, "return_msg": "정상적으로 처리되었습니다"}
```

#### 2.2.3 주식 매도주문 (kt10001)

```
POST /api/dostk/ordr
Header: api-id: kt10001
(매수주문과 동일한 구조, api-id만 다름)
```

#### 2.2.4 주식 정정주문 (kt10002)

```
POST /api/dostk/ordr
Header: api-id: kt10002
추가 필드: org_ord_no (원주문번호)
```

#### 2.2.5 주식 취소주문 (kt10003)

```
POST /api/dostk/ordr
Header: api-id: kt10003
추가 필드: org_ord_no (원주문번호)
```

#### 2.2.6 주식기본정보요청 (ka10001)

```
POST /api/dostk/stkinfo
Header: api-id: ka10001

Request:
  stk_cd: 종목코드 - "039490" | "039490_NX" | "039490_AL" (거래소별)

Response (주요 필드):
  stk_cd: 종목코드
  stk_nm: 종목명
  cur_prc: 현재가
  prdy_vrss: 전일대비
  prdy_ctrt: 전일대비율
  acml_vol: 누적거래량
  acml_tr_pbmn: 누적거래대금
  stk_hgpr: 상한가
  stk_lwpr: 하한가
  strt_prc: 시가
  high_prc: 고가
  low_prc: 저가
  per: PER
  pbr: PBR
  eps: EPS
  bps: BPS
  lstg_stqt: 상장주수
  mrkt_tot_amt: 시가총액
```

#### 2.2.7 주식호가요청 (ka10004)

```
POST /api/dostk/mrkcond
Header: api-id: ka10004

Request:
  stk_cd: 종목코드

Response (주요 필드):
  매도호가 1~10: sell_hoga_1 ~ sell_hoga_10
  매도잔량 1~10: sell_hoga_qty_1 ~ sell_hoga_qty_10
  매수호가 1~10: buy_hoga_1 ~ buy_hoga_10
  매수잔량 1~10: buy_hoga_qty_1 ~ buy_hoga_qty_10
  총매도잔량: tot_sell_qty
  총매수잔량: tot_buy_qty
```

#### 2.2.8 주식일봉차트조회요청 (ka10081)

```
POST /api/dostk/chart
Header: api-id: ka10081

Request:
  stk_cd: 종목코드 (필수)
  base_dt: 기준일자 YYYYMMDD (선택)
  updn_tp: 과거/미래 구분 "D"/"U" (선택)
  cnt: 요청건수 (선택)

Response (배열):
  stk_cd: 종목코드
  dt: 일자
  open_prc: 시가
  high_prc: 고가
  low_prc: 저가
  clos_prc: 종가
  acml_vol: 거래량
  acml_tr_pbmn: 거래대금
```

#### 2.2.9 계좌평가현황요청 (kt00004)

```
POST /api/dostk/acnt
Header: api-id: kt00004

Response:
  pchs_amt: 매입금액
  evlu_amt: 평가금액
  evlu_pfls_amt: 평가손익
  evlu_pfls_rt: 평가손익률
  d2_ord_psbl_amt: D+2 주문가능금액
  종목별 상세 (배열):
    stk_cd: 종목코드
    stk_nm: 종목명
    hldg_qty: 보유수량
    avg_buy_prc: 평균매입가
    cur_prc: 현재가
    evlu_amt: 평가금액
    evlu_pfls_amt: 평가손익
    evlu_pfls_rt: 평가손익률
```

#### 2.2.10 실시간시세 - WebSocket API

```
WebSocket: /api/dostk/websocket

주요 실시간 API:
  00: 주문체결 (계좌)
  04: 잔고 (계좌)
  0A: 주식기세
  0B: 주식체결
  0C: 주식우선호가
  0D: 주식호가잔량
  0E: 주식시간외호가
  0F: 주식당일거래원
  0G: ETF NAV
  0H: 주식예상체결
  0J: 업종지수
  1h: VI발동/해제
```

---

## 3. API URL 체계

### 3.1 Base URL

| 환경 | URL |
|------|-----|
| 운영서버 | https://api.kiwoom.com |
| 모의투자 | https://mockapi.kiwoom.com |

### 3.2 Endpoint 분류

| Path | 용도 | 주요 API |
|------|------|---------|
| `/oauth2/token` | 토큰 발급 | au10001 |
| `/oauth2/revoke` | 토큰 폐기 | au10002 |
| `/api/dostk/stkinfo` | 종목정보 | ka10001, ka10099 |
| `/api/dostk/mrkcond` | 시세/시황 | ka10004, ka10086 |
| `/api/dostk/chart` | 차트 | ka10079~ka10094 |
| `/api/dostk/acnt` | 계좌 | kt00001~kt00018 |
| `/api/dostk/ordr` | 주문 | kt10000~kt10003 |
| `/api/dostk/crdordr` | 신용주문 | kt10006~kt10009 |
| `/api/dostk/frgnistt` | 기관/외국인 | ka10008, ka10009 |
| `/api/dostk/rkinfo` | 순위정보 | ka10020~ka10042 |
| `/api/dostk/sect` | 업종 | ka20001~ka20009 |
| `/api/dostk/etf` | ETF | ka40001~ka40010 |
| `/api/dostk/elw` | ELW | ka30001~ka30012 |
| `/api/dostk/thme` | 테마 | ka90001, ka90002 |
| `/api/dostk/slb` | 대차거래 | ka10068, ka10069 |
| `/api/dostk/shsa` | 공매도 | ka10014 |
| `/api/dostk/websocket` | 실시간/조건검색 | 00~1h |

---

## 4. 아키텍처 설계

### 4.1 디렉토리 구조

```
backend/
├── agents/
│   ├── tools/
│   │   ├── market_data.py           # 기존 (US Stock - yfinance)
│   │   └── kr_market_data.py        # 신규 (KR Stock - Kiwoom)
│   └── graph/
│       ├── nodes.py                  # 수정 (한국 주식 지원 추가)
│       └── kr_trading_graph.py       # 신규 (한국 전용 그래프)
├── services/
│   ├── kiwoom/                       # 신규 Kiwoom 서비스
│   │   ├── __init__.py
│   │   ├── client.py                 # API 클라이언트 (핵심)
│   │   ├── auth.py                   # OAuth 인증 (au10001, au10002)
│   │   ├── market.py                 # 시세 조회 (ka10001, ka10004, ka10081 등)
│   │   ├── account.py                # 계좌 조회 (kt00001~kt00018)
│   │   ├── order.py                  # 주문 (kt10000~kt10003)
│   │   ├── realtime.py               # 실시간 WebSocket
│   │   └── models.py                 # Pydantic 모델
│   └── market_data_factory.py        # 시장 데이터 팩토리
├── app/
│   └── api/
│       ├── routes/
│       │   └── kr_stocks.py          # 신규 한국 주식 라우트
│       └── schemas/
│           └── kr_stocks.py          # 신규 한국 주식 스키마
└── config.py                         # Kiwoom 설정 추가
```

### 4.2 Pydantic 모델 설계

```python
# backend/services/kiwoom/models.py

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

class KiwoomToken(BaseModel):
    """OAuth 토큰"""
    token: str
    token_type: str = "Bearer"
    expires_dt: datetime

    @property
    def is_expired(self) -> bool:
        return datetime.now() >= self.expires_dt

class StockBasicInfo(BaseModel):
    """주식 기본 정보 (ka10001)"""
    stk_cd: str = Field(..., description="종목코드")
    stk_nm: str = Field(..., description="종목명")
    cur_prc: int = Field(..., description="현재가")
    prdy_vrss: int = Field(..., description="전일대비")
    prdy_ctrt: float = Field(..., description="전일대비율")
    acml_vol: int = Field(..., description="누적거래량")
    mrkt_tot_amt: int = Field(..., description="시가총액")
    per: Optional[float] = Field(None, description="PER")
    pbr: Optional[float] = Field(None, description="PBR")
    eps: Optional[int] = Field(None, description="EPS")

class OrderRequest(BaseModel):
    """주문 요청 (kt10000, kt10001)"""
    dmst_stex_tp: Literal["KRX", "NXT", "SOR"] = Field("KRX", description="거래소구분")
    stk_cd: str = Field(..., description="종목코드", max_length=12)
    ord_qty: int = Field(..., description="주문수량", gt=0)
    ord_uv: Optional[int] = Field(None, description="주문단가 (시장가시 생략)")
    trde_tp: str = Field(..., description="매매구분")
    cond_uv: Optional[int] = Field(None, description="조건단가")

class OrderResponse(BaseModel):
    """주문 응답"""
    ord_no: str = Field(..., description="주문번호")
    dmst_stex_tp: str = Field(..., description="거래소구분")
    return_code: int
    return_msg: str

class ChartData(BaseModel):
    """일봉 차트 데이터 (ka10081)"""
    stk_cd: str
    dt: str  # YYYYMMDD
    open_prc: int  # 시가
    high_prc: int  # 고가
    low_prc: int   # 저가
    clos_prc: int  # 종가
    acml_vol: int  # 거래량

class AccountBalance(BaseModel):
    """계좌 평가 현황 (kt00004)"""
    pchs_amt: int = Field(..., description="매입금액")
    evlu_amt: int = Field(..., description="평가금액")
    evlu_pfls_amt: int = Field(..., description="평가손익")
    evlu_pfls_rt: float = Field(..., description="평가손익률")
    d2_ord_psbl_amt: int = Field(..., description="D+2 주문가능금액")
    holdings: list[dict] = Field(default_factory=list, description="보유종목")
```

### 4.3 Kiwoom 클라이언트 설계

```python
# backend/services/kiwoom/client.py

import httpx
from typing import Optional, Literal
import pandas as pd
from .auth import KiwoomAuth
from .models import *

class KiwoomClient:
    """Kiwoom REST API 클라이언트"""

    def __init__(self, is_mock: bool = True):
        self.base_url = (
            "https://mockapi.kiwoom.com" if is_mock
            else "https://api.kiwoom.com"
        )
        self.auth = KiwoomAuth(self.base_url)
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _request(
        self,
        api_id: str,
        endpoint: str,
        data: dict,
        cont_yn: str = "",
        next_key: str = ""
    ) -> dict:
        """공통 API 요청"""
        token = await self.auth.get_token()
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "api-id": api_id,
            "authorization": f"Bearer {token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
        }
        response = await self._client.post(
            f"{self.base_url}{endpoint}",
            json=data,
            headers=headers
        )
        response.raise_for_status()
        return response.json()

    # === 종목정보 ===
    async def get_stock_info(self, stk_cd: str) -> StockBasicInfo:
        """주식기본정보요청 (ka10001)"""
        result = await self._request(
            api_id="ka10001",
            endpoint="/api/dostk/stkinfo",
            data={"stk_cd": stk_cd}
        )
        return StockBasicInfo(**result)

    # === 시세 ===
    async def get_orderbook(self, stk_cd: str) -> dict:
        """주식호가요청 (ka10004)"""
        return await self._request(
            api_id="ka10004",
            endpoint="/api/dostk/mrkcond",
            data={"stk_cd": stk_cd}
        )

    # === 차트 ===
    async def get_daily_chart(
        self,
        stk_cd: str,
        base_dt: Optional[str] = None,
        cnt: int = 100
    ) -> pd.DataFrame:
        """주식일봉차트조회요청 (ka10081)"""
        data = {"stk_cd": stk_cd, "cnt": str(cnt)}
        if base_dt:
            data["base_dt"] = base_dt
        result = await self._request(
            api_id="ka10081",
            endpoint="/api/dostk/chart",
            data=data
        )
        return pd.DataFrame(result.get("output", []))

    # === 계좌 ===
    async def get_account_balance(self) -> AccountBalance:
        """계좌평가현황요청 (kt00004)"""
        result = await self._request(
            api_id="kt00004",
            endpoint="/api/dostk/acnt",
            data={}
        )
        return AccountBalance(**result)

    # === 주문 ===
    async def place_buy_order(
        self,
        stk_cd: str,
        qty: int,
        price: Optional[int] = None,
        order_type: str = "3"  # 기본: 시장가
    ) -> OrderResponse:
        """주식 매수주문 (kt10000)"""
        data = {
            "dmst_stex_tp": "KRX",
            "stk_cd": stk_cd,
            "ord_qty": str(qty),
            "ord_uv": str(price) if price else "",
            "trde_tp": order_type,
            "cond_uv": ""
        }
        result = await self._request(
            api_id="kt10000",
            endpoint="/api/dostk/ordr",
            data=data
        )
        return OrderResponse(**result)

    async def place_sell_order(
        self,
        stk_cd: str,
        qty: int,
        price: Optional[int] = None,
        order_type: str = "3"
    ) -> OrderResponse:
        """주식 매도주문 (kt10001)"""
        data = {
            "dmst_stex_tp": "KRX",
            "stk_cd": stk_cd,
            "ord_qty": str(qty),
            "ord_uv": str(price) if price else "",
            "trde_tp": order_type,
            "cond_uv": ""
        }
        result = await self._request(
            api_id="kt10001",
            endpoint="/api/dostk/ordr",
            data=data
        )
        return OrderResponse(**result)

    async def cancel_order(self, org_ord_no: str) -> OrderResponse:
        """주식 취소주문 (kt10003)"""
        result = await self._request(
            api_id="kt10003",
            endpoint="/api/dostk/ordr",
            data={"org_ord_no": org_ord_no}
        )
        return OrderResponse(**result)
```

---

## 5. 구현 단계

### Phase 1: 인증 및 기반 구축 (필수)

| 작업 | 파일 | API ID | 설명 |
|------|------|--------|------|
| OAuth 인증 | auth.py | au10001 | 토큰 발급 |
| 토큰 갱신 | auth.py | au10001 | 만료 전 자동 갱신 |
| 토큰 폐기 | auth.py | au10002 | 앱 종료 시 |
| HTTP 클라이언트 | client.py | - | httpx 기반 |
| 에러 핸들링 | errors.py | - | 에러 코드 매핑 |

### Phase 2: 시세 조회

| 작업 | 파일 | API ID | 설명 |
|------|------|--------|------|
| 주식 기본정보 | market.py | ka10001 | 종목명, 현재가, PER 등 |
| 호가 조회 | market.py | ka10004 | 10호가 |
| 일봉 차트 | market.py | ka10081 | OHLCV |
| 분봉 차트 | market.py | ka10080 | 분봉 데이터 |
| 일별 주가 | market.py | ka10086 | 일별 시세 |

### Phase 3: 계좌 조회

| 작업 | 파일 | API ID | 설명 |
|------|------|--------|------|
| 예수금 조회 | account.py | kt00001 | 주문가능금액 |
| 계좌 평가 | account.py | kt00004 | 보유종목, 손익 |
| 미체결 조회 | account.py | ka10075 | 미체결 주문 |
| 체결 조회 | account.py | ka10076 | 체결 내역 |

### Phase 4: 주문 기능

| 작업 | 파일 | API ID | 설명 |
|------|------|--------|------|
| 매수 주문 | order.py | kt10000 | 시장가/지정가 |
| 매도 주문 | order.py | kt10001 | 시장가/지정가 |
| 정정 주문 | order.py | kt10002 | 가격/수량 변경 |
| 취소 주문 | order.py | kt10003 | 주문 취소 |

### Phase 5: 실시간 데이터 (선택)

| 작업 | 파일 | API ID | 설명 |
|------|------|--------|------|
| WebSocket 연결 | realtime.py | - | 실시간 연결 |
| 주문체결 알림 | realtime.py | 00 | 체결 통보 |
| 잔고 변동 | realtime.py | 04 | 잔고 업데이트 |
| 실시간 체결 | realtime.py | 0B | 종목별 체결 |
| 실시간 호가 | realtime.py | 0D | 호가 변동 |

### Phase 6: 에이전트 통합

| 작업 | 파일 | 설명 |
|------|------|------|
| 한국 시장 데이터 도구 | kr_market_data.py | 기술 지표 계산 |
| 한국 주식 분석 노드 | nodes.py 수정 | 시장 구분 로직 |
| 거래 실행 노드 | nodes.py 수정 | Kiwoom 주문 연동 |

---

## 6. 환경 설정

### 6.1 환경 변수 (.env)

```bash
# Kiwoom REST API
KIWOOM_APP_KEY=your_app_key
KIWOOM_SECRET_KEY=your_secret_key
KIWOOM_ACCOUNT_NO=your_account_number
KIWOOM_IS_MOCK=true  # true: 모의투자, false: 실거래

# 기존 설정
MARKET_DATA_MODE=live
LLM_PROVIDER=ollama
```

### 6.2 설정 클래스

```python
# backend/app/config.py 추가

class Settings(BaseSettings):
    # ... 기존 설정 ...

    # Kiwoom 설정
    KIWOOM_APP_KEY: str = ""
    KIWOOM_SECRET_KEY: str = ""
    KIWOOM_ACCOUNT_NO: str = ""
    KIWOOM_IS_MOCK: bool = True

    @property
    def kiwoom_base_url(self) -> str:
        return (
            "https://mockapi.kiwoom.com" if self.KIWOOM_IS_MOCK
            else "https://api.kiwoom.com"
        )
```

---

## 7. 에러 처리

### 7.1 에러 코드 (공통)

```python
# backend/services/kiwoom/errors.py

class KiwoomErrorCode:
    """Kiwoom API 에러 코드"""
    SUCCESS = 0

    # 인증 관련
    TOKEN_EXPIRED = -100
    INVALID_APP_KEY = -101
    INVALID_SECRET_KEY = -102

    # 종목 관련
    INVALID_STOCK_CODE = -200

    # 주문 관련
    INVALID_ORDER_QTY = -300
    INVALID_ORDER_PRICE = -301
    INSUFFICIENT_BALANCE = -400
    ORDER_NOT_FOUND = -401
    MARKET_CLOSED = -500

class KiwoomError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")
```

---

## 8. 종목 코드 체계

### 8.1 거래소별 종목코드 형식

| 거래소 | 형식 | 예시 |
|--------|------|------|
| KRX (한국거래소) | 6자리 숫자 | 005930 |
| NXT (대체거래소) | 6자리_NX | 005930_NX |
| SOR (스마트오더라우팅) | 6자리_AL | 005930_AL |

### 8.2 인기 종목 (한국)

```python
POPULAR_KR_TICKERS = {
    # KOSPI 대형주
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스",
    "005380": "현대차",
    "000270": "기아",
    "068270": "셀트리온",
    "035420": "NAVER",
    "035720": "카카오",
    "051910": "LG화학",
    "006400": "삼성SDI",
    "003670": "포스코홀딩스",

    # KOSDAQ
    "247540": "에코프로비엠",
    "086520": "에코프로",
    "377300": "카카오페이",

    # ETF
    "069500": "KODEX 200",
    "229200": "KODEX 코스닥150",
    "114800": "KODEX 인버스",
    "122630": "KODEX 레버리지",
    "305540": "TIGER 2차전지테마",
}
```

---

## 9. 테스트 계획

### 9.1 단위 테스트

```python
# tests/services/kiwoom/test_client.py

import pytest
from backend.services.kiwoom.client import KiwoomClient

@pytest.fixture
def mock_client():
    return KiwoomClient(is_mock=True)

@pytest.mark.asyncio
async def test_get_stock_info(mock_client):
    """삼성전자 기본정보 조회"""
    info = await mock_client.get_stock_info("005930")
    assert info.stk_nm == "삼성전자"
    assert info.cur_prc > 0

@pytest.mark.asyncio
async def test_get_daily_chart(mock_client):
    """일봉 차트 조회"""
    df = await mock_client.get_daily_chart("005930", cnt=30)
    assert len(df) > 0
    assert "clos_prc" in df.columns

@pytest.mark.asyncio
async def test_place_buy_order(mock_client):
    """매수 주문 테스트"""
    result = await mock_client.place_buy_order(
        stk_cd="005930",
        qty=1,
        order_type="3"  # 시장가
    )
    assert result.return_code == 0
    assert result.ord_no is not None
```

### 9.2 통합 테스트 체크리스트

- [ ] OAuth 인증 → 토큰 발급 성공
- [ ] 토큰 만료 → 자동 갱신
- [ ] 종목 기본정보 조회
- [ ] 호가 조회
- [ ] 일봉 차트 조회 → DataFrame 변환
- [ ] 계좌 잔고 조회
- [ ] 매수 주문 (모의투자)
- [ ] 매도 주문 (모의투자)
- [ ] 주문 취소
- [ ] 에이전트 분석 → 거래 제안 → 주문 실행

---

## 10. 마이그레이션 체크리스트

### 10.1 모의투자 검증

- [ ] Kiwoom 개발자 등록 완료
- [ ] 앱키/시크릿키 발급
- [ ] 모의투자 계좌 신청
- [ ] OAuth 인증 테스트
- [ ] 시세 조회 테스트
- [ ] 주문 테스트

### 10.2 실서버 전환

- [ ] 모의투자 전체 테스트 통과
- [ ] KIWOOM_IS_MOCK=false 설정
- [ ] 소액 테스트 (1주 매매)
- [ ] Rate Limiting 모니터링
- [ ] 에러 로깅 확인

---

## 11. 참고

### 11.1 API 문서
- [키움 REST API 포털](https://openapi.kiwoom.com/)
- [API 가이드](https://openapi.kiwoom.com/guide/apiguide)
- [모의투자 신청](https://www.kiwoom.com) > 모의투자 > 상시모의투자

### 11.2 Excel 명세서
- 파일: `docs/KiwoomRESTAPI.xlsx`
- 시트: 207개 API 상세 스펙

### 11.3 주요 제한사항
- 모의투자: KRX 종목만 지원
- 3개월 미사용 시 서비스 종료 (재등록 필요)
- Rate Limiting: 공식 문서 확인 필요
