"""리포트 데이터 모델.

전부 Optional 기본값을 갖는다 — 수집이 부분 실패해도 렌더가 죽지 않아야
한다. 값이 없는 것과 0인 것은 구별한다(손절 여유 0%는 '즉시 손절'이다).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AgentVote:
    agent_type: str          # technical | fundamental | sentiment | risk
    vote: str                # buy | sell | hold | ...
    confidence: float
    headline: str            # key_factors[0] 또는 reasoning 앞 120자
    is_dissent: bool = False


@dataclass
class NewsItem:
    title: str
    source: str
    published: str           # "2시간 전" 같은 사람 표기
    sentiment: Optional[str] = None
    url: str = ""


@dataclass
class PositionResearch:
    ticker: str
    name: str
    quantity: int
    avg_price: float
    current_price: float
    pnl_pct: float
    stop_loss: Optional[float]
    stop_loss_source: Optional[str]      # 두 엔진이 다른 값을 든다 — 출처 표기
    discussion_count: int = 0
    action: Optional[str] = None
    consensus: Optional[float] = None
    votes: list[AgentVote] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    per: Optional[float] = None
    pbr: Optional[float] = None
    eps: Optional[float] = None
    news: list[NewsItem] = field(default_factory=list)
    news_error: Optional[str] = None

    @property
    def stop_margin_pct(self) -> Optional[float]:
        if not self.stop_loss or not self.current_price:
            return None
        return (self.current_price - self.stop_loss) / self.current_price * 100

    @property
    def dissent_count(self) -> int:
        if not self.action:
            return 0
        target = self.action.strip().lower()
        return sum(1 for v in self.votes if (v.vote or "").strip().lower() != target)


@dataclass
class ReportContext:
    kind: str                # premarket | postmarket | discovery
    trade_date: str
    generated_at: str
    regime: Optional[dict[str, Any]] = None
    positions: list[PositionResearch] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
