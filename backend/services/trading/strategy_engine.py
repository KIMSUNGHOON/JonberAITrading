"""
Strategy Engine

Evaluates trading decisions based on analysis results and strategy configuration.
Uses both rule-based and LLM-based evaluation for optimal decision making.
"""

import json
import logging
import re
from typing import Optional, Dict, Any, List
from datetime import datetime

from .strategy import (
    TradingStrategy,
    EntryDecision,
    ExitDecision,
    RiskTolerance,
)
from .models import ManagedPosition, AllocationPlan

logger = logging.getLogger(__name__)


class StrategyEngine:
    """
    Trading Strategy Engine

    Evaluates entry/exit decisions based on:
    1. Rule-based filters (entry/exit conditions)
    2. LLM-based strategic judgment (using system prompt)
    """

    def __init__(self, strategy: TradingStrategy, llm_provider=None):
        self.strategy = strategy
        self.llm = llm_provider
        self._last_evaluation = None

    def update_strategy(self, strategy: TradingStrategy):
        """Update the active strategy"""
        self.strategy = strategy
        logger.info(f"[StrategyEngine] Strategy updated: {strategy.name}")

    # -------------------------------------------
    # Entry Evaluation
    # -------------------------------------------

    async def evaluate_entry(
        self,
        ticker: str,
        stock_name: str,
        analysis_results: Dict[str, Any],
        current_price: float,
        account_info: Dict[str, Any],
    ) -> EntryDecision:
        """
        Evaluate whether to enter a position based on analysis results.

        Args:
            ticker: Stock code
            stock_name: Stock name
            analysis_results: Results from analysis agents
            current_price: Current stock price
            account_info: Account balance and position info

        Returns:
            EntryDecision with action and rationale
        """
        logger.info(f"[StrategyEngine] Evaluating entry for {ticker} ({stock_name})")

        # Extract scores from analysis
        scores = self._extract_scores(analysis_results)

        # 1. Rule-based filtering
        rule_result = self._check_entry_rules(scores)
        if not rule_result["passed"]:
            return EntryDecision(
                action="SKIP",
                confidence=rule_result.get("confidence", 30),
                rationale=rule_result["reason"],
                key_factors=rule_result.get("failed_rules", []),
                strategy_alignment=0,
            )

        # 2. Calculate position size
        position_size = self._calculate_position_size(
            scores.get("risk_score", 50),
            account_info,
            current_price,
        )

        # 3. Calculate stop-loss and take-profit prices
        stop_loss_price = current_price * (1 - self.strategy.exit_conditions.stop_loss_pct)
        take_profit_price = current_price * (1 + self.strategy.exit_conditions.take_profit_pct)

        # 4. LLM-based strategic evaluation (if available)
        if self.llm:
            llm_decision = await self._llm_entry_evaluation(
                ticker=ticker,
                stock_name=stock_name,
                analysis_results=analysis_results,
                current_price=current_price,
                account_info=account_info,
                scores=scores,
            )
            if llm_decision:
                # Merge LLM decision with rule-based calculation
                return EntryDecision(
                    action=llm_decision.get("action", "HOLD"),
                    confidence=llm_decision.get("confidence", 50),
                    entry_price=llm_decision.get("entry_price", current_price),
                    position_size_pct=llm_decision.get("position_size_pct", position_size),
                    stop_loss_price=llm_decision.get("stop_loss_price", stop_loss_price),
                    take_profit_price=llm_decision.get("take_profit_price", take_profit_price),
                    rationale=llm_decision.get("rationale", ""),
                    key_factors=llm_decision.get("key_factors", []),
                    strategy_alignment=llm_decision.get("strategy_alignment", 70),
                )

        # 5. Rule-based decision (without LLM)
        action = self._determine_action_from_scores(scores)

        return EntryDecision(
            action=action,
            confidence=rule_result.get("confidence", 60),
            entry_price=current_price,
            position_size_pct=position_size,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            rationale=self._generate_rationale(scores, action),
            key_factors=rule_result.get("passed_rules", []),
            strategy_alignment=rule_result.get("alignment", 50),
        )

    def _check_entry_rules(self, scores: Dict[str, int]) -> Dict[str, Any]:
        """Check if analysis scores meet entry conditions"""
        entry = self.strategy.entry_conditions
        failed_rules = []
        passed_rules = []

        # Technical score check
        tech_score = scores.get("technical_score", 0)
        if tech_score >= entry.min_technical_score:
            passed_rules.append(f"기술적 점수 충족 ({tech_score}/{entry.min_technical_score})")
        else:
            failed_rules.append(f"기술적 점수 미달 ({tech_score}/{entry.min_technical_score})")

        # Fundamental score check
        fund_score = scores.get("fundamental_score", 0)
        if fund_score >= entry.min_fundamental_score:
            passed_rules.append(f"펀더멘털 점수 충족 ({fund_score}/{entry.min_fundamental_score})")
        else:
            failed_rules.append(f"펀더멘털 점수 미달 ({fund_score}/{entry.min_fundamental_score})")

        # Sentiment score check
        sent_score = scores.get("sentiment_score", 50)
        if sent_score >= entry.min_sentiment_score:
            passed_rules.append(f"감성 점수 충족 ({sent_score}/{entry.min_sentiment_score})")
        else:
            failed_rules.append(f"감성 점수 미달 ({sent_score}/{entry.min_sentiment_score})")

        # Risk score check (lower is better)
        risk_score = scores.get("risk_score", 50)
        if risk_score <= entry.max_risk_score:
            passed_rules.append(f"리스크 점수 적정 ({risk_score}/{entry.max_risk_score})")
        else:
            failed_rules.append(f"리스크 점수 초과 ({risk_score}/{entry.max_risk_score})")

        # Calculate confidence and alignment
        total_rules = len(passed_rules) + len(failed_rules)
        alignment = int((len(passed_rules) / total_rules) * 100) if total_rules > 0 else 0

        # Determine if passed (at least 3 of 4 rules)
        passed = len(failed_rules) <= 1

        return {
            "passed": passed,
            "confidence": alignment,
            "alignment": alignment,
            "passed_rules": passed_rules,
            "failed_rules": failed_rules,
            "reason": "; ".join(failed_rules) if failed_rules else "모든 조건 충족",
        }

    def _calculate_position_size(
        self,
        risk_score: int,
        account_info: Dict[str, Any],
        current_price: float,
    ) -> float:
        """Calculate optimal position size based on risk and account"""
        sizing = self.strategy.position_sizing

        # Base position size
        base_size = sizing.max_position_pct

        # Adjust by risk score
        if sizing.adjust_by_risk_score:
            # Higher risk = smaller position
            risk_factor = 1 - (risk_score / 100) * sizing.risk_adjustment_factor
            adjusted_size = base_size * risk_factor
        else:
            adjusted_size = base_size

        # Ensure within bounds
        adjusted_size = max(sizing.min_position_pct, min(sizing.max_position_pct, adjusted_size))

        # Check cash constraints
        total_equity = account_info.get("total_equity", 0)
        available_cash = account_info.get("available_cash", 0)
        current_stock_ratio = account_info.get("stock_ratio", 0)

        # Don't exceed max stock ratio
        remaining_stock_capacity = sizing.max_total_stock_pct - current_stock_ratio
        if adjusted_size > remaining_stock_capacity:
            adjusted_size = max(0, remaining_stock_capacity)

        # Ensure minimum cash ratio
        max_investable = (available_cash / total_equity) - sizing.min_cash_ratio if total_equity > 0 else 0
        if adjusted_size > max_investable:
            adjusted_size = max(0, max_investable)

        return round(adjusted_size, 4)

    def _determine_action_from_scores(self, scores: Dict[str, int]) -> str:
        """Determine action based on aggregate scores"""
        tech = scores.get("technical_score", 50)
        fund = scores.get("fundamental_score", 50)
        sent = scores.get("sentiment_score", 50)
        risk = scores.get("risk_score", 50)

        # Weighted average (can be customized)
        weighted_score = (tech * 0.3) + (fund * 0.3) + (sent * 0.2) + ((100 - risk) * 0.2)

        if weighted_score >= 65:
            return "BUY"
        elif weighted_score <= 35:
            return "SELL"
        else:
            return "HOLD"

    def _generate_rationale(self, scores: Dict[str, int], action: str) -> str:
        """Generate rationale text for the decision"""
        parts = []

        if action == "BUY":
            parts.append("매수 추천:")
        elif action == "SELL":
            parts.append("매도 추천:")
        else:
            parts.append("관망 추천:")

        tech = scores.get("technical_score", 0)
        fund = scores.get("fundamental_score", 0)
        sent = scores.get("sentiment_score", 0)
        risk = scores.get("risk_score", 0)

        if tech >= 60:
            parts.append(f"기술적 신호 양호({tech}점)")
        if fund >= 60:
            parts.append(f"펀더멘털 양호({fund}점)")
        if sent >= 55:
            parts.append(f"시장 심리 긍정적({sent}점)")
        if risk <= 40:
            parts.append(f"리스크 낮음({risk}점)")

        return " ".join(parts)

    async def _llm_entry_evaluation(
        self,
        ticker: str,
        stock_name: str,
        analysis_results: Dict[str, Any],
        current_price: float,
        account_info: Dict[str, Any],
        scores: Dict[str, int],
    ) -> Optional[Dict[str, Any]]:
        """Use LLM for strategic entry evaluation"""
        if not self.llm:
            return None

        try:
            prompt = self._build_entry_prompt(
                ticker, stock_name, analysis_results, current_price, account_info, scores
            )

            response = await self.llm.generate(
                prompt,
                temperature=0.3,
                max_tokens=1000,
            )

            return self._parse_llm_response(response)

        except Exception as e:
            logger.error(f"[StrategyEngine] LLM evaluation failed: {e}")
            return None

    def _build_entry_prompt(
        self,
        ticker: str,
        stock_name: str,
        analysis_results: Dict[str, Any],
        current_price: float,
        account_info: Dict[str, Any],
        scores: Dict[str, int],
    ) -> str:
        """Build prompt for LLM entry evaluation"""

        # Get summaries from analysis results
        tech_summary = analysis_results.get("technical", {}).get("summary", "분석 없음")
        fund_summary = analysis_results.get("fundamental", {}).get("summary", "분석 없음")
        sent_summary = analysis_results.get("sentiment", {}).get("summary", "분석 없음")
        risk_summary = analysis_results.get("risk", {}).get("summary", "분석 없음")

        return f"""## 투자 전략 (System Prompt)
{self.strategy.system_prompt}

## 추가 지침
{self.strategy.custom_instructions or "없음"}

## 분석 대상
- 종목코드: {ticker}
- 종목명: {stock_name}
- 현재가: {current_price:,.0f}원

## 분석 결과 요약
1. 기술적 분석 (점수: {scores.get('technical_score', 0)}/100)
   {tech_summary}

2. 펀더멘털 분석 (점수: {scores.get('fundamental_score', 0)}/100)
   {fund_summary}

3. 감성 분석 (점수: {scores.get('sentiment_score', 0)}/100)
   {sent_summary}

4. 리스크 평가 (점수: {scores.get('risk_score', 0)}/100)
   {risk_summary}

## 계좌 현황
- 총 자산: {account_info.get('total_equity', 0):,.0f}원
- 가용 현금: {account_info.get('available_cash', 0):,.0f}원
- 현재 주식 비중: {account_info.get('stock_ratio', 0) * 100:.1f}%

## 전략 파라미터
- 리스크 성향: {self.strategy.risk_tolerance.value}
- 투자 스타일: {self.strategy.trading_style.value}
- 최대 단일 종목 비중: {self.strategy.position_sizing.max_position_pct * 100:.1f}%
- 기본 손절 비율: {self.strategy.exit_conditions.stop_loss_pct * 100:.1f}%
- 기본 익절 비율: {self.strategy.exit_conditions.take_profit_pct * 100:.1f}%

위 투자 전략과 분석 결과를 종합하여 매매 결정을 내려주세요.

응답은 반드시 아래 JSON 형식으로만 해주세요:
```json
{{
    "action": "BUY" | "SELL" | "HOLD" | "SKIP",
    "confidence": 0-100,
    "entry_price": 권장 진입가 (현재가 기준),
    "position_size_pct": 권장 비중 (0.01-0.15),
    "stop_loss_price": 손절가,
    "take_profit_price": 익절가,
    "rationale": "결정 근거 2-3문장",
    "key_factors": ["주요 판단 요인 1", "주요 판단 요인 2", "주요 판단 요인 3"],
    "strategy_alignment": 0-100
}}
```"""

    def _parse_llm_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse LLM response JSON"""
        try:
            # Extract JSON from response
            json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())

            # Try parsing entire response as JSON
            return json.loads(response)

        except json.JSONDecodeError:
            logger.warning(f"[StrategyEngine] Failed to parse LLM response: {response[:200]}")
            return None

    def _extract_scores(self, analysis_results: Dict[str, Any]) -> Dict[str, int]:
        """Extract scores from analysis results"""
        return {
            "technical_score": analysis_results.get("technical", {}).get("score", 50),
            "fundamental_score": analysis_results.get("fundamental", {}).get("score", 50),
            "sentiment_score": analysis_results.get("sentiment", {}).get("score", 50),
            "risk_score": analysis_results.get("risk", {}).get("score", 50),
        }

    # -------------------------------------------
    # Exit Evaluation
    # -------------------------------------------

    async def evaluate_exit(
        self,
        position: ManagedPosition,
        current_price: float,
        latest_news: Optional[List[Dict[str, Any]]] = None,
    ) -> ExitDecision:
        """
        Evaluate whether to exit a position.

        Args:
            position: Current managed position
            current_price: Current stock price
            latest_news: Recent news articles (optional)

        Returns:
            ExitDecision with action and reason
        """
        exit_conditions = self.strategy.exit_conditions

        # Calculate P&L
        pnl_pct = (current_price - position.avg_price) / position.avg_price

        # 1. Stop-loss check
        if pnl_pct <= -exit_conditions.stop_loss_pct:
            return ExitDecision(
                action="STOP_LOSS",
                urgency="high",
                reason=f"손절가 도달 (손실률: {pnl_pct*100:.1f}%)",
                recommended_price=current_price,
            )

        # 2. Take-profit check
        if pnl_pct >= exit_conditions.take_profit_pct:
            return ExitDecision(
                action="TAKE_PROFIT",
                urgency="normal",
                reason=f"익절가 도달 (수익률: {pnl_pct*100:.1f}%)",
                recommended_price=current_price,
            )

        # 3. Trailing stop check
        if exit_conditions.trailing_stop_enabled and position.highest_price:
            trailing_stop_price = position.highest_price * (1 - exit_conditions.trailing_stop_pct)
            if current_price <= trailing_stop_price:
                return ExitDecision(
                    action="TRAILING_STOP",
                    urgency="high",
                    reason=f"추적 손절 발동 (고점 대비 {exit_conditions.trailing_stop_pct*100:.1f}% 하락)",
                    recommended_price=current_price,
                )

        # 4. News-based exit check
        if latest_news and exit_conditions.exit_on_negative_news:
            news_sentiment = self._analyze_news_sentiment(latest_news)
            if news_sentiment <= exit_conditions.news_sentiment_threshold:
                return ExitDecision(
                    action="EMERGENCY_EXIT",
                    urgency="critical",
                    reason=f"부정적 뉴스 감지 (심리지수: {news_sentiment})",
                    recommended_price=current_price,
                )

        # 5. Max holding days check
        if exit_conditions.max_holding_days:
            holding_days = (datetime.now() - position.entry_time).days
            if holding_days >= exit_conditions.max_holding_days:
                return ExitDecision(
                    action="TIME_EXIT",
                    urgency="normal",
                    reason=f"최대 보유 기간 도달 ({holding_days}일)",
                    recommended_price=current_price,
                )

        # No exit signal
        return ExitDecision(
            action="HOLD",
            urgency="normal",
            reason="청산 조건 미충족",
        )

    def _analyze_news_sentiment(self, news: List[Dict[str, Any]]) -> int:
        """Simple news sentiment analysis (returns -100 to 100)"""
        if not news:
            return 0

        # Simple keyword-based sentiment
        negative_keywords = ["하락", "폭락", "급락", "손실", "위기", "적자", "파산", "소송", "불안"]
        positive_keywords = ["상승", "급등", "호재", "이익", "성장", "수주", "신고가", "호실적"]

        total_sentiment = 0
        for article in news[:5]:  # Check latest 5 articles
            title = article.get("title", "").lower()
            sentiment = 0
            for keyword in negative_keywords:
                if keyword in title:
                    sentiment -= 20
            for keyword in positive_keywords:
                if keyword in title:
                    sentiment += 20
            total_sentiment += max(-100, min(100, sentiment))

        return int(total_sentiment / len(news)) if news else 0

    # -------------------------------------------
    # Allocation Calculation
    # -------------------------------------------

    def calculate_allocation(
        self,
        entry_decision: EntryDecision,
        current_price: float,
        account_info: Dict[str, Any],
    ) -> AllocationPlan:
        """
        Calculate allocation based on entry decision.

        Returns:
            AllocationPlan with quantity and rationale
        """
        if entry_decision.action not in ["BUY", "SELL"]:
            return AllocationPlan(
                quantity=0,
                rationale=f"액션 없음: {entry_decision.action}",
            )

        total_equity = account_info.get("total_equity", 0)
        position_size_pct = entry_decision.position_size_pct or self.strategy.position_sizing.max_position_pct

        # Calculate target amount
        target_amount = total_equity * position_size_pct

        # Calculate quantity
        entry_price = entry_decision.entry_price or current_price
        quantity = int(target_amount / entry_price)

        if quantity <= 0:
            return AllocationPlan(
                quantity=0,
                rationale="주문 가능 수량 없음 (자금 부족)",
            )

        return AllocationPlan(
            quantity=quantity,
            rationale=f"전략 기반 비중 {position_size_pct*100:.1f}% ({quantity}주 @ {entry_price:,.0f}원)",
        )


# -------------------------------------------
# Factory Function
# -------------------------------------------

def create_strategy_engine(
    strategy: Optional[TradingStrategy] = None,
    llm_provider=None,
) -> StrategyEngine:
    """Create a strategy engine with optional strategy and LLM"""
    from .strategy import get_strategy_preset, StrategyPreset

    if strategy is None:
        strategy = get_strategy_preset(StrategyPreset.CONSERVATIVE_INCOME)

    return StrategyEngine(strategy=strategy, llm_provider=llm_provider)
