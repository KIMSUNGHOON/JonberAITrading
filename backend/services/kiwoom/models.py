"""
Kiwoom REST API Pydantic Models

Data models for Kiwoom Securities REST API requests and responses.
Based on KiwoomRESTAPI.xlsx specification.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class OrderType(str, Enum):
    """주문 유형 (trde_tp)"""

    LIMIT = "0"  # 보통 (지정가)
    MARKET = "3"  # 시장가
    CONDITIONAL = "5"  # 조건부지정가
    BEST_LIMIT = "6"  # 최유리지정가
    FIRST_LIMIT = "7"  # 최우선지정가
    LIMIT_IOC = "10"  # 보통(IOC)
    MARKET_IOC = "13"  # 시장가(IOC)
    BEST_IOC = "16"  # 최유리(IOC)
    LIMIT_FOK = "20"  # 보통(FOK)
    MARKET_FOK = "23"  # 시장가(FOK)
    BEST_FOK = "26"  # 최유리(FOK)
    STOP_LIMIT = "28"  # 스톱지정가
    MID_PRICE = "29"  # 중간가
    MID_IOC = "30"  # 중간가(IOC)
    MID_FOK = "31"  # 중간가(FOK)
    PRE_MARKET = "61"  # 장시작전시간외
    AFTER_SINGLE = "62"  # 시간외단일가
    AFTER_MARKET = "81"  # 장마감후시간외


class Exchange(str, Enum):
    """거래소 구분 (dmst_stex_tp)"""

    KRX = "KRX"  # 한국거래소
    NXT = "NXT"  # 대체거래소
    SOR = "SOR"  # 스마트오더라우팅


class KiwoomToken(BaseModel):
    """OAuth 접근 토큰 (au10001 응답)"""

    token: str = Field(..., description="접근토큰")
    token_type: str = Field(default="Bearer", description="토큰 타입")
    expires_dt: datetime = Field(..., description="만료 일시")

    @property
    def is_expired(self) -> bool:
        """토큰 만료 여부 확인"""
        return datetime.now() >= self.expires_dt

    @property
    def authorization_header(self) -> str:
        """Authorization 헤더 값"""
        return f"{self.token_type} {self.token}"


class StockBasicInfo(BaseModel):
    """주식 기본 정보 (ka10001 응답)"""

    stk_cd: str = Field(..., description="종목코드")
    stk_nm: str = Field(..., description="종목명")
    cur_prc: int = Field(..., description="현재가")
    prdy_vrss: int = Field(default=0, description="전일대비")
    prdy_ctrt: float = Field(default=0.0, description="전일대비율 (%)")
    acml_vol: int = Field(default=0, description="누적거래량")
    acml_tr_pbmn: int = Field(default=0, description="누적거래대금")
    strt_prc: int = Field(default=0, description="시가")
    high_prc: int = Field(default=0, description="고가")
    low_prc: int = Field(default=0, description="저가")
    stk_hgpr: int = Field(default=0, description="상한가")
    stk_lwpr: int = Field(default=0, description="하한가")
    per: Optional[float] = Field(default=None, description="PER")
    pbr: Optional[float] = Field(default=None, description="PBR")
    eps: Optional[int] = Field(default=None, description="EPS")
    bps: Optional[int] = Field(default=None, description="BPS")
    lstg_stqt: Optional[int] = Field(default=None, description="상장주수")
    mrkt_tot_amt: Optional[int] = Field(default=None, description="시가총액")

    @property
    def change_sign(self) -> str:
        """등락 부호"""
        if self.prdy_vrss > 0:
            return "+"
        elif self.prdy_vrss < 0:
            return "-"
        return ""


class OrderbookUnit(BaseModel):
    """호가 단위"""

    price: int = Field(..., description="호가")
    quantity: int = Field(..., description="잔량")


class Orderbook(BaseModel):
    """주식 호가 정보 (ka10004 응답)"""

    stk_cd: str = Field(..., description="종목코드")
    sell_hogas: list[OrderbookUnit] = Field(default_factory=list, description="매도호가 (1~10)")
    buy_hogas: list[OrderbookUnit] = Field(default_factory=list, description="매수호가 (1~10)")
    tot_sell_qty: int = Field(default=0, description="총매도잔량")
    tot_buy_qty: int = Field(default=0, description="총매수잔량")

    @property
    def spread(self) -> int:
        """스프레드 (매도1호가 - 매수1호가)"""
        if self.sell_hogas and self.buy_hogas:
            return self.sell_hogas[0].price - self.buy_hogas[0].price
        return 0

    @property
    def bid_ask_ratio(self) -> float:
        """매수/매도 잔량 비율"""
        if self.tot_sell_qty > 0:
            return self.tot_buy_qty / self.tot_sell_qty
        return 0.0


class ChartData(BaseModel):
    """차트 데이터 (ka10081 등 응답)"""

    stk_cd: str = Field(..., description="종목코드")
    dt: str = Field(..., description="일자 (YYYYMMDD)")
    open_prc: int = Field(..., description="시가")
    high_prc: int = Field(..., description="고가")
    low_prc: int = Field(..., description="저가")
    clos_prc: int = Field(..., description="종가")
    acml_vol: int = Field(..., description="거래량")
    acml_tr_pbmn: Optional[int] = Field(default=None, description="거래대금")

    @property
    def ohlcv(self) -> dict:
        """OHLCV 딕셔너리"""
        return {
            "open": self.open_prc,
            "high": self.high_prc,
            "low": self.low_prc,
            "close": self.clos_prc,
            "volume": self.acml_vol,
        }


class OrderRequest(BaseModel):
    """주문 요청 (kt10000, kt10001)"""

    dmst_stex_tp: Exchange = Field(default=Exchange.KRX, description="거래소구분")
    stk_cd: str = Field(..., description="종목코드", min_length=6, max_length=12)
    ord_qty: int = Field(..., description="주문수량", gt=0)
    ord_uv: Optional[int] = Field(default=None, description="주문단가 (시장가시 생략)")
    trde_tp: OrderType = Field(default=OrderType.MARKET, description="매매구분")
    cond_uv: Optional[int] = Field(default=None, description="조건단가")

    def to_api_dict(self) -> dict:
        """API 요청용 딕셔너리 변환"""
        return {
            "dmst_stex_tp": self.dmst_stex_tp.value,
            "stk_cd": self.stk_cd,
            "ord_qty": str(self.ord_qty),
            "ord_uv": str(self.ord_uv) if self.ord_uv else "",
            "trde_tp": self.trde_tp.value,
            "cond_uv": str(self.cond_uv) if self.cond_uv else "",
        }


class OrderResponse(BaseModel):
    """주문 응답 (kt10000~kt10003)"""

    ord_no: str = Field(..., description="주문번호")
    dmst_stex_tp: Optional[str] = Field(default=None, description="거래소구분")
    return_code: int = Field(..., description="응답코드")
    return_msg: str = Field(..., description="응답메시지")

    @property
    def is_success(self) -> bool:
        """주문 성공 여부"""
        return self.return_code == 0


class Holding(BaseModel):
    """보유 종목 (kt00004 응답 내 종목별 상세)"""

    stk_cd: str = Field(..., description="종목코드")
    stk_nm: str = Field(..., description="종목명")
    hldg_qty: int = Field(..., description="보유수량")
    avg_buy_prc: int = Field(..., description="평균매입가")
    cur_prc: int = Field(..., description="현재가")
    evlu_amt: int = Field(..., description="평가금액")
    evlu_pfls_amt: int = Field(..., description="평가손익")
    evlu_pfls_rt: float = Field(..., description="평가손익률 (%)")

    @property
    def total_cost(self) -> int:
        """총 매입금액"""
        return self.avg_buy_prc * self.hldg_qty


class AccountBalance(BaseModel):
    """계좌 평가 현황 (kt00004 응답)"""

    pchs_amt: int = Field(default=0, description="매입금액")
    evlu_amt: int = Field(default=0, description="평가금액")
    evlu_pfls_amt: int = Field(default=0, description="평가손익")
    evlu_pfls_rt: float = Field(default=0.0, description="평가손익률 (%)")
    d2_ord_psbl_amt: int = Field(default=0, description="D+2 주문가능금액")
    holdings: list[Holding] = Field(default_factory=list, description="보유종목")

    @property
    def total_value(self) -> int:
        """총 자산가치 (평가금액 + 주문가능금액)"""
        return self.evlu_amt + self.d2_ord_psbl_amt


class CashBalance(BaseModel):
    """예수금 상세 현황 (kt00001 응답)"""

    dnca_tot_amt: int = Field(default=0, description="예수금총액")
    ord_psbl_amt: int = Field(default=0, description="주문가능금액")
    sttl_psbk_amt: int = Field(default=0, description="출금가능금액")
    d1_ord_psbl_amt: int = Field(default=0, description="D+1 주문가능금액")
    d2_ord_psbl_amt: int = Field(default=0, description="D+2 주문가능금액")


class PendingOrder(BaseModel):
    """미체결 주문 (ka10075 응답)"""

    ord_no: str = Field(..., description="주문번호")
    stk_cd: str = Field(..., description="종목코드")
    stk_nm: str = Field(..., description="종목명")
    ord_qty: int = Field(..., description="주문수량")
    ord_uv: int = Field(..., description="주문단가")
    ccld_qty: int = Field(default=0, description="체결수량")
    rmn_qty: int = Field(default=0, description="미체결수량")
    ord_dt: str = Field(..., description="주문일자")
    ord_tm: str = Field(..., description="주문시간")
    buy_sell_tp: str = Field(..., description="매수매도구분")

    @property
    def is_partial_filled(self) -> bool:
        """부분 체결 여부"""
        return self.ccld_qty > 0 and self.rmn_qty > 0


class FilledOrder(BaseModel):
    """체결 내역 (ka10076 응답)"""

    ord_no: str = Field(..., description="주문번호")
    stk_cd: str = Field(..., description="종목코드")
    stk_nm: str = Field(..., description="종목명")
    ccld_qty: int = Field(..., description="체결수량")
    ccld_uv: int = Field(..., description="체결단가")
    ccld_amt: int = Field(..., description="체결금액")
    ccld_dt: str = Field(..., description="체결일자")
    ccld_tm: str = Field(..., description="체결시간")
    buy_sell_tp: str = Field(..., description="매수매도구분")


class MarketType(str, Enum):
    """시장 구분 (ka10099 mrkt_tp)"""

    KOSPI = "0"       # 코스피
    KOSDAQ = "10"     # 코스닥
    ELW = "3"         # ELW
    ETF = "8"         # ETF
    KOTC = "30"       # K-OTC
    KONEX = "50"      # 코넥스
    WARRANT = "5"     # 신주인수권
    FUND = "4"        # 투자펀드
    REITS = "6"       # 리츠
    HIFUND = "9"      # 하이펀드


class StockListItem(BaseModel):
    """종목 정보 리스트 아이템 (ka10099 응답)"""

    code: str = Field(..., description="종목코드")
    name: str = Field(..., description="종목명")
    market_code: str = Field(default="", description="시장구분코드")
    market_name: str = Field(default="", description="시장명")
    list_count: Optional[int] = Field(default=None, description="상장주식수")
    state: str = Field(default="", description="종목상태")
    order_warning: str = Field(default="0", description="투자주의여부")

    @property
    def is_kospi(self) -> bool:
        """코스피 종목 여부"""
        return self.market_code in ("10", "0") or "코스피" in self.market_name

    @property
    def is_kosdaq(self) -> bool:
        """코스닥 종목 여부"""
        return self.market_code == "20" or "코스닥" in self.market_name

    @property
    def is_normal(self) -> bool:
        """정상 거래 종목 여부 (투자주의/경고 제외)"""
        return self.order_warning == "0"


# 인기 종목 상수
POPULAR_KR_TICKERS: dict[str, str] = {
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
    "105560": "KB금융",
    "055550": "신한지주",
    "012330": "현대모비스",
    # KOSDAQ
    "247540": "에코프로비엠",
    "086520": "에코프로",
    "377300": "카카오페이",
    "293490": "카카오게임즈",
    # ETF
    "069500": "KODEX 200",
    "229200": "KODEX 코스닥150",
    "114800": "KODEX 인버스",
    "122630": "KODEX 레버리지",
    "305540": "TIGER 2차전지테마",
    "381180": "TIGER 미국나스닥100",
}