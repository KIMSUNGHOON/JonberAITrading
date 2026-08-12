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
