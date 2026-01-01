"""
Korean Stock Constants and Cache

Contains:
- KOREAN_STOCKS: Extended list of KOSPI/KOSDAQ stocks
- POPULAR_STOCKS: Subset for quick access
- Cache variables for popular stocks
- Session store for analysis
"""

from datetime import datetime
from typing import Optional

from app.api.schemas.kr_stocks import KRStockInfo

# In-memory session store for Korean stock analysis
kr_stock_sessions: dict[str, dict] = {}

# Cached stock list (popular stocks for quick access)
_cached_popular_stocks: list[KRStockInfo] = []
_stocks_cache_time: Optional[datetime] = None
CACHE_TTL_SECONDS = 300  # 5 minutes


def get_cached_popular_stocks() -> list[KRStockInfo]:
    """Get cached popular stocks list."""
    return _cached_popular_stocks


def set_cached_popular_stocks(stocks: list[KRStockInfo], cache_time: datetime) -> None:
    """Set cached popular stocks list."""
    global _cached_popular_stocks, _stocks_cache_time
    _cached_popular_stocks = stocks
    _stocks_cache_time = cache_time


def get_stocks_cache_time() -> Optional[datetime]:
    """Get cache timestamp."""
    return _stocks_cache_time


# Korean stocks list (KOSPI/KOSDAQ major stocks)
# Extended list for better search functionality
KOREAN_STOCKS = [
    # 시가총액 상위 (KOSPI)
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("035420", "NAVER"),
    ("005380", "현대차"),
    ("051910", "LG화학"),
    ("006400", "삼성SDI"),
    ("035720", "카카오"),
    ("068270", "셀트리온"),
    ("028260", "삼성물산"),
    ("105560", "KB금융"),
    ("005490", "POSCO홀딩스"),
    ("055550", "신한지주"),
    ("003670", "포스코퓨처엠"),
    ("000270", "기아"),
    ("012330", "현대모비스"),
    ("066570", "LG전자"),
    ("003550", "LG"),
    ("096770", "SK이노베이션"),
    ("086790", "하나금융지주"),
    ("032830", "삼성생명"),
    ("015760", "한국전력"),
    ("033780", "KT&G"),
    ("034730", "SK"),
    ("017670", "SK텔레콤"),
    ("018260", "삼성에스디에스"),
    ("000810", "삼성화재"),
    ("030200", "KT"),
    ("316140", "우리금융지주"),
    ("009150", "삼성전기"),
    ("010950", "S-Oil"),
    ("036570", "엔씨소프트"),
    ("090430", "아모레퍼시픽"),
    ("011170", "롯데케미칼"),
    ("034020", "두산에너빌리티"),
    ("024110", "기업은행"),
    ("009540", "한국조선해양"),
    ("032640", "LG유플러스"),
    ("010130", "고려아연"),
    ("021240", "코웨이"),
    ("047050", "포스코인터내셔널"),
    ("003490", "대한항공"),
    ("009830", "한화솔루션"),
    ("088350", "한화생명"),
    ("010620", "현대미포조선"),
    ("000100", "유한양행"),
    ("326030", "SK바이오팜"),
    ("011200", "HMM"),
    ("329180", "현대중공업"),
    ("267250", "HD현대"),
    ("004020", "현대제철"),
    # 추가 인기 종목
    ("352820", "하이브"),
    ("003410", "쌍용C&E"),
    ("002790", "아모레G"),
    ("000720", "현대건설"),
    ("047810", "한국항공우주"),
    ("010140", "삼성중공업"),
    ("051900", "LG생활건강"),
    ("011780", "금호석유"),
    ("034220", "LG디스플레이"),
    ("001450", "현대해상"),
    ("004370", "농심"),
    ("139480", "이마트"),
    ("007070", "GS리테일"),
    ("004990", "롯데지주"),
    ("003230", "삼양식품"),
    ("097950", "CJ제일제당"),
    ("009240", "한샘"),
    ("035250", "강원랜드"),
    ("000880", "한화"),
    ("161390", "한국타이어앤테크놀로지"),
    # KOSDAQ 인기 종목
    ("247540", "에코프로비엠"),
    ("086520", "에코프로"),
    ("041510", "에스엠"),
    ("035900", "JYP Ent."),
    ("122870", "와이지엔터테인먼트"),
    ("263750", "펄어비스"),
    ("293490", "카카오게임즈"),
    ("112040", "위메이드"),
    ("251270", "넷마블"),
    ("053800", "안랩"),
    ("145020", "휴젤"),
    ("028300", "HLB"),
    ("196170", "알테오젠"),
    ("091990", "셀트리온헬스케어"),
    ("068760", "셀트리온제약"),
    ("357780", "솔브레인"),
    ("036830", "솔브레인홀딩스"),
    ("000120", "CJ대한통운"),
    ("078930", "GS"),
    ("034730", "SK"),
    ("006360", "GS건설"),
    ("069960", "현대백화점"),
    ("004170", "신세계"),
    ("001040", "CJ"),
    ("272210", "한화시스템"),
    ("042700", "한미반도체"),
    ("336260", "두산퓨얼셀"),
    ("298050", "효성첨단소재"),
    ("241560", "두산밥캣"),
]

# Popular Korean stocks for default list (subset for quick access)
POPULAR_STOCKS = KOREAN_STOCKS[:10]
