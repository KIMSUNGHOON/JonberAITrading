"""
Decision Nodes for Korean Stock Trading

Contains Risk Assessment, Strategic Decision, Human Approval, and Re-analyze nodes.
"""

import time
import uuid

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.graph.kr_stock_state import (
    KRStockAnalysisResult,
    KRStockAnalysisStage,
    KRStockTradeProposal,
    SignalType,
    TradeAction,
    add_kr_stock_reasoning_log,
    calculate_kr_stock_consensus_signal,
    get_all_kr_stock_analyses,
    kr_stock_analysis_dict_to_context_string,
)
from agents.llm_provider import get_llm_provider
from agents.prompts import (
    KR_STOCK_RISK_ASSESSOR_PROMPT,
    KR_STOCK_STRATEGIC_DECISION_PROMPT,
)
from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
from .helpers import (
    _get_stk_cd_safely,
    _calculate_kr_stock_risk_score,
    _signal_to_action_with_position,
    _extract_key_factors,
    _extract_bull_case,
    _extract_bear_case,
)

logger = structlog.get_logger()


async def kr_stock_risk_assessment_node(state: dict) -> dict:
    """
    Korean stock risk assessment.
    Evaluates volatility, liquidity, and position sizing.
    """
    start_time = time.perf_counter()
    stk_cd = _get_stk_cd_safely(state, "risk_assessment")
    stk_nm = state.get("stk_nm", stk_cd)
    llm = get_llm_provider()

    logger.info("node_started", node="kr_stock_risk_assessment", stk_cd=stk_cd)

    # Gather all previous analyses
    analyses = get_all_kr_stock_analyses(state)
    analyses_context = "\n\n".join(kr_stock_analysis_dict_to_context_string(a) for a in analyses)

    market_data = state.get("market_data", {})
    current_price = market_data.get("cur_prc", 0)

    messages = [
        SystemMessage(content=KR_STOCK_RISK_ASSESSOR_PROMPT),
        HumanMessage(
            content=f"{stk_nm} ({stk_cd}) 리스크 평가 (현재가: {current_price:,}원):\n\n{analyses_context}"
        ),
    ]

    logger.debug("llm_request", node="kr_stock_risk_assessment")
    response = await llm.generate(messages)

    # Calculate risk score
    risk_score = _calculate_kr_stock_risk_score(analyses, market_data)

    # Korean stock stop-loss calculation (typically 5-8%)
    stop_loss_pct = 0.05 if risk_score < 0.5 else 0.08
    take_profit_pct = 0.10 if risk_score < 0.5 else 0.08

    result = KRStockAnalysisResult(
        agent_type="risk",
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        signal=SignalType.HOLD,
        confidence=0.80,
        summary=response[:500] if len(response) > 500 else response,
        reasoning=response,
        key_factors=_extract_key_factors(response),
        signals={
            "risk_score": risk_score,
            "max_position_pct": 5.0 if risk_score < 0.5 else 3.0,
            "suggested_stop_loss": int(current_price * (1 - stop_loss_pct)),
            "suggested_take_profit": int(current_price * (1 + take_profit_pct)),
        },
    )

    reasoning = f"[리스크 평가] {stk_nm}: 리스크 점수 {risk_score:.0%}, 최대 포지션 {result.signals['max_position_pct']}%"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info("node_completed", node="kr_stock_risk_assessment", stk_cd=stk_cd, risk_score=risk_score, duration_ms=round(duration_ms, 2))

    # Send Telegram notification for sub-agent decision
    try:
        from services.telegram import get_telegram_notifier
        telegram = await get_telegram_notifier()
        if telegram.is_ready:
            # Map risk score to risk level signal
            risk_level = "low" if risk_score < 0.4 else ("high" if risk_score > 0.7 else "medium")
            risk_key_factors = [
                f"리스크 점수: {risk_score:.0%}",
                f"최대 포지션: {result.signals['max_position_pct']}%",
                f"손절가: ₩{result.signals.get('suggested_stop_loss', 0):,}",
                f"목표가: ₩{result.signals.get('suggested_take_profit', 0):,}",
            ]
            await telegram.send_subagent_decision(
                ticker=stk_cd,
                stock_name=stk_nm,
                agent_type="risk",
                signal=risk_level,
                confidence=1 - risk_score,  # Higher confidence = lower risk
                key_factors=risk_key_factors,
            )
    except Exception as te:
        logger.warning("telegram_subagent_notification_failed", agent="risk", error=str(te))

    return {
        "risk_assessment": result.model_dump(),
        "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": KRStockAnalysisStage.RISK,
    }


async def kr_stock_strategic_decision_node(state: dict) -> dict:
    """
    Synthesize all analyses into a Korean stock trade proposal.
    Considers existing position context for appropriate action recommendations.
    """
    start_time = time.perf_counter()
    stk_cd = _get_stk_cd_safely(state, "strategic_decision")
    stk_nm = state.get("stk_nm", stk_cd)
    llm = get_llm_provider()

    logger.info("node_started", node="kr_stock_strategic_decision", stk_cd=stk_cd)

    # Get existing position context
    existing_position = state.get("existing_position")
    has_position = existing_position is not None
    position_pnl_pct = existing_position.get("profit_loss_pct", 0.0) if existing_position else 0.0

    # Build position context string for LLM
    position_context = ""
    if existing_position:
        position_context = (
            f"\n## 현재 보유 포지션\n"
            f"- 보유수량: {existing_position['quantity']}주\n"
            f"- 평균매입가: {existing_position['avg_buy_price']:,}원\n"
            f"- 현재가: {existing_position['current_price']:,}원\n"
            f"- 평가손익: {existing_position['profit_loss']:,}원 ({position_pnl_pct:+.2f}%)\n"
        )
    else:
        position_context = "\n## 현재 보유 포지션\n- 미보유 종목입니다.\n"

    # Collect all analyses
    analyses = get_all_kr_stock_analyses(state)
    analyses_context = "\n\n".join(kr_stock_analysis_dict_to_context_string(a) for a in analyses)

    # Calculate consensus
    consensus_signal, avg_confidence = calculate_kr_stock_consensus_signal(analyses)

    # Include position context in LLM prompt
    messages = [
        SystemMessage(content=KR_STOCK_STRATEGIC_DECISION_PROMPT),
        HumanMessage(
            content=f"{stk_nm} ({stk_cd}) 투자 결정:\n\n"
            f"컨센서스 시그널: {consensus_signal.value} (평균 신뢰도: {avg_confidence:.0%})\n"
            f"{position_context}\n"
            f"{analyses_context}"
        ),
    ]

    logger.debug("llm_request", node="kr_stock_strategic_decision")
    response = await llm.generate(messages)

    # Determine action considering existing position
    action = _signal_to_action_with_position(
        signal=consensus_signal,
        has_position=has_position,
        position_pnl_pct=position_pnl_pct,
    )

    logger.info(
        "kr_stock_action_determined",
        stk_cd=stk_cd,
        consensus_signal=consensus_signal.value,
        has_position=has_position,
        position_pnl_pct=position_pnl_pct,
        action=action.value,
    )

    # Get risk parameters
    risk = state.get("risk_assessment", {})
    risk_signals = risk.get("signals", {})

    market_data = state.get("market_data", {})
    current_price = market_data.get("cur_prc", 0)
    position_size_pct = float(risk_signals.get("max_position_pct", 5.0))

    # Calculate quantity based on action type and available balance
    quantity = 0
    if action in (TradeAction.BUY, TradeAction.ADD) and current_price > 0:
        try:
            client = await get_shared_kiwoom_client_async()
            cash_balance = await client.get_cash_balance()
            orderable_amount = cash_balance.ord_psbl_amt

            # Calculate quantity: (orderable * position_size%) / price
            investment_amount = int(orderable_amount * position_size_pct / 100)
            quantity = investment_amount // current_price

            logger.info(
                "kr_stock_quantity_calculated",
                stk_cd=stk_cd,
                orderable_amount=orderable_amount,
                position_size_pct=position_size_pct,
                investment_amount=investment_amount,
                current_price=current_price,
                quantity=quantity,
            )
        except Exception as e:
            logger.warning(
                "kr_stock_quantity_calculation_failed",
                stk_cd=stk_cd,
                error=str(e),
            )
            # quantity remains 0, user can modify in approval dialog

    elif action in (TradeAction.SELL, TradeAction.REDUCE) and existing_position:
        # For sell actions, use existing position quantity
        if action == TradeAction.SELL:
            quantity = existing_position["quantity"]  # Full sell
        else:
            quantity = max(1, existing_position["quantity"] // 2)  # Partial sell (50%)

    # Create trade proposal
    proposal = KRStockTradeProposal(
        id=str(uuid.uuid4()),
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        action=action,
        quantity=quantity,
        entry_price=current_price,
        stop_loss=risk_signals.get("suggested_stop_loss", int(current_price * 0.95)),
        take_profit=risk_signals.get("suggested_take_profit", int(current_price * 1.10)),
        risk_score=float(risk_signals.get("risk_score", 0.5)),
        position_size_pct=position_size_pct,
        rationale=response,
        bull_case=_extract_bull_case(response),
        bear_case=_extract_bear_case(response),
        analyses=analyses,
    )

    # Build reasoning with position context
    position_note = ""
    if has_position:
        position_note = f" (기존 {existing_position['quantity']}주 보유 중)"

    reasoning = f"[투자 결정] 제안: {action.value} {stk_nm} {quantity}주 @ {current_price:,}원{position_note}"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "node_completed",
        node="kr_stock_strategic_decision",
        stk_cd=stk_cd,
        action=action.value,
        duration_ms=round(duration_ms, 2),
    )

    # Handle WATCH action - add to watch list
    if action == TradeAction.WATCH:
        try:
            from app.dependencies import get_trading_coordinator
            coordinator = await get_trading_coordinator()

            # Extract key factors from analyses
            key_factors = []
            for analysis in analyses:
                if analysis.get("key_factors"):
                    key_factors.extend(analysis["key_factors"][:2])
            key_factors = key_factors[:5]  # Limit to 5 factors

            # Build analysis summary
            analysis_summary = f"컨센서스: {consensus_signal.value} (신뢰도: {avg_confidence:.0%})"

            # Add to watch list
            watched = coordinator.add_to_watch_list(
                session_id=state.get("session_id", str(uuid.uuid4())),
                ticker=stk_cd,
                stock_name=stk_nm,
                signal=consensus_signal.value,
                confidence=avg_confidence,
                current_price=current_price,
                target_entry_price=int(current_price * 0.97),  # Suggest 3% below current
                stop_loss=proposal.stop_loss,
                take_profit=proposal.take_profit,
                analysis_summary=analysis_summary,
                key_factors=key_factors,
                risk_score=int(proposal.risk_score * 10),
            )

            logger.info(
                "kr_stock_added_to_watch_list",
                stk_cd=stk_cd,
                watch_id=watched.id,
            )

            # Send Telegram notification for watch list addition
            from services.telegram import get_telegram_notifier
            telegram = await get_telegram_notifier()
            if telegram.is_ready:
                await telegram.send_message(
                    f"👁 *Watch List 추가*\n\n"
                    f"*종목:* {stk_nm} ({stk_cd})\n"
                    f"*현재가:* ₩{current_price:,}\n"
                    f"*시그널:* {consensus_signal.value} (신뢰도: {avg_confidence:.0%})\n\n"
                    f"*분석 요약:*\n{response[:200]}...\n\n"
                    f"_매수 진입점 모니터링 중_"
                )

        except Exception as we:
            logger.warning("watch_list_addition_failed", error=str(we))

    # Send Telegram notification for trade proposal (BUY/SELL only)
    elif action in (TradeAction.BUY, TradeAction.SELL, TradeAction.ADD, TradeAction.REDUCE):
        try:
            from services.telegram import get_telegram_notifier
            telegram = await get_telegram_notifier()
            if telegram.is_ready:
                await telegram.send_trade_proposal(
                    ticker=stk_cd,
                    stock_name=stk_nm,
                    action=action.value,
                    entry_price=current_price,
                    stop_loss=proposal.stop_loss,
                    take_profit=proposal.take_profit,
                    confidence=avg_confidence,
                    rationale=response[:300],
                )
        except Exception as te:
            logger.warning("telegram_proposal_notification_failed", error=str(te))

    # Send Telegram notification for AVOID
    elif action == TradeAction.AVOID:
        try:
            from services.telegram import get_telegram_notifier
            telegram = await get_telegram_notifier()
            if telegram.is_ready:
                await telegram.send_message(
                    f"⛔ *매수 회피*\n\n"
                    f"*종목:* {stk_nm} ({stk_cd})\n"
                    f"*현재가:* ₩{current_price:,}\n"
                    f"*시그널:* {consensus_signal.value} (신뢰도: {avg_confidence:.0%})\n\n"
                    f"*사유:*\n{response[:200]}..."
                )
        except Exception as te:
            logger.warning("telegram_avoid_notification_failed", error=str(te))

    return {
        "trade_proposal": proposal.model_dump(),
        "synthesis": {
            "consensus_signal": consensus_signal.value,
            "average_confidence": avg_confidence,
            "decision_rationale": response[:500],
        },
        "awaiting_approval": True,
        "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": KRStockAnalysisStage.SYNTHESIS,
    }


async def kr_stock_human_approval_node(state: dict) -> dict:
    """
    Human-in-the-loop approval checkpoint for Korean stock trades.
    """
    stk_cd = _get_stk_cd_safely(state, "human_approval")
    stk_nm = state.get("stk_nm", stk_cd)
    proposal = state.get("trade_proposal", {})

    proposal_id = proposal.get("id", "")[:8]
    proposal_action = proposal.get("action")

    logger.info(
        "node_started",
        node="kr_stock_human_approval",
        stk_cd=stk_cd,
        proposal_id=proposal_id,
    )

    reasoning = f"[HITL] {stk_nm} {proposal_action} 거래 승인 대기 중..."

    return {
        "awaiting_approval": True,
        "current_stage": KRStockAnalysisStage.APPROVAL,
        "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
    }


async def kr_stock_re_analyze_node(state: dict) -> dict:
    """
    Prepare for re-analysis after rejection.
    """
    stk_cd = _get_stk_cd_safely(state, "re_analyze")
    stk_nm = state.get("stk_nm", stk_cd)
    user_feedback = state.get("user_feedback", "")
    re_analyze_count = state.get("re_analyze_count", 0) + 1

    logger.info(
        "node_started",
        node="kr_stock_re_analyze",
        stk_cd=stk_cd,
        re_analyze_count=re_analyze_count,
    )

    reasoning = f"[재분석] 사용자 요청에 따른 재분석 (시도 #{re_analyze_count})"
    if user_feedback:
        reasoning += f"\n사용자 피드백: {user_feedback}"

    return {
        "current_stage": KRStockAnalysisStage.DATA_COLLECTION,
        "technical_analysis": None,
        "fundamental_analysis": None,
        "sentiment_analysis": None,
        "risk_assessment": None,
        "synthesis": None,
        "trade_proposal": None,
        "awaiting_approval": False,
        "approval_status": None,
        "re_analyze_count": re_analyze_count,
        "re_analyze_feedback": user_feedback,
        "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
    }
