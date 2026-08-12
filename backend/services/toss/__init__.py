"""토스증권 Open API 연동 (2026-08-12).

Kiwoom과 병행한다 — 대체가 아니다. 토스가 나은 것과 못 하는 것이 뚜렷하다:

  ✅ KOSPI/KOSDAQ 지수 일봉을 **지연 없이** 준다
     (yfinance는 구조적으로 1거래일 뒤진다 — 08:05 수집 시점에 전일 종가가 없다)
  ✅ 레이트리밋 MARKET_DATA 15/s · CHART 20/s (Kiwoom ~1.4/s의 10배)
  ✅ `warnings` — 투자경고·투자위험·단기과열·정리매매·VI
  ❌ PER·PBR·EPS가 없다 — 펀더멘탈은 Kiwoom `ka10001`을 계속 쓴다

문서: docs/TOSS_OPENAPI_GUIDE.md
"""
from services.toss.client import TossClient, TossIpBlockedError

__all__ = ["TossClient", "TossIpBlockedError"]


_client = None


def get_toss_client():
    """프로세스 싱글턴. 호출마다 새로 만들면 토큰 캐시가 무의미해진다.

    자격증명이 없어도 **객체는 돌려준다**(`enabled=False`). `None`을
    돌려주면 호출자가 매번 None 검사를 해야 하고, 한 곳이라도 빠뜨리면
    `AttributeError`로 EOD 체인이 죽는다 — 비활성 객체가 더 안전하다.
    """
    global _client
    if _client is None:
        import httpx

        from app.config import get_settings

        s = get_settings()
        _client = TossClient(
            client_id=getattr(s, "TOSS_CLIENT_ID", None),
            client_secret=getattr(s, "TOSS_CLIENT_SECRET", None),
            http=httpx.AsyncClient(timeout=15.0),
        )
    return _client
