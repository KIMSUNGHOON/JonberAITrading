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
from agents.graph.decision_policy import decide_action, position_feasible_set
from agents.llm.tasks import DECISION_SCHEMA, TaskType
from agents.llm_provider import get_llm_provider
from agents.prompts import (
    KR_STOCK_RISK_ASSESSOR_PROMPT,
    KR_STOCK_STRATEGIC_DECISION_PROMPT,
)
from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
from services.trading.r_sizing import apply_liquidity_cap, r_cap_value
from services.trading.strategy_consensus import clamp_knob
from .helpers import (
    _get_stk_cd_safely,
    _calculate_kr_stock_risk_score,
    _signal_to_action_with_position,
    _extract_key_factors,
    _extract_bull_case,
    _extract_bear_case,
)

logger = structlog.get_logger()


async def _get_active_strategy():
    """활성 TradingStrategy 조회 (best-effort — 실패/없음=None, 그래프 노드를
    절대 막지 않는다). lazy import는 agent_chat coordinator와 동일 패턴."""
    try:
        from app.dependencies import get_trading_coordinator

        return (await get_trading_coordinator()).get_strategy()
    except Exception:
        return None


async def _get_risk_budget_pct() -> float:
    """활성 RiskParameters.risk_budget_pct 조회 (best-effort — 실패/
    coordinator 미가동 시 모델 기본값, 그래프 노드를 절대 막지 않는다).
    lazy import는 _get_active_strategy와 동일 패턴 — S-4(생존 규율) R 캡이
    strategy_apply의 전략-적응/수동 PUT 값과 동일한 SSOT(공유 RiskParameters
    인스턴스)를 읽도록 한다."""
    from services.trading.models import RiskParameters

    default = RiskParameters.model_fields["risk_budget_pct"].default
    try:
        from app.dependencies import get_trading_coordinator

        coordinator = await get_trading_coordinator()
        return coordinator.risk_params.risk_budget_pct
    except Exception:
        return default


def _strategy_stop_params(strategy, risk_score: float) -> tuple[float, float, float]:
    """전략 exit/sizing 노브 + risk_score 감산 → (stop_pct 분율, take_pct 분율,
    max_position_pct 퍼센트). 고리스크(>=0.5)는 손절 거리 확대(완화, ×1.15 캡
    0.50 — 레거시 5%→8% 방향 준용), 익절 보수(×0.8 플로어 0.01), 포지션 축소
    (×0.6 — 기존 5.0→3.0 비율 준용).

    Phase4 최종리뷰 Fix2: 전략 원본 노브는 `clamp_knob`로 KNOB_BOUNDS 클램프한
    뒤 사용 — 수동 PUT /strategy가 Pydantic 필드 범위(예: stop_loss_pct 0.50)
    까지 허용해도, T2(strategy_apply)와 다른 무클램프 수치가 이 그래프 경로에
    유입되지 않도록 한다."""
    base_stop = clamp_knob("stop_loss_pct", strategy.exit_conditions.stop_loss_pct)
    base_take = clamp_knob("take_profit_pct", strategy.exit_conditions.take_profit_pct)
    base_position = (
        clamp_knob("max_position_pct", strategy.position_sizing.max_position_pct) * 100.0
    )
    if risk_score < 0.5:
        return base_stop, base_take, base_position
    return (
        min(0.50, base_stop * 1.15),
        max(0.01, base_take * 0.8),
        base_position * 0.6,
    )


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

    # Korean stock stop-loss calculation — 활성 전략이 있으면 전략 노브,
    # 없으면 기존 하드코딩(5-8%) 유지 (Phase4).
    strategy = await _get_active_strategy()
    if strategy is not None:
        stop_loss_pct, take_profit_pct, max_position_pct = _strategy_stop_params(
            strategy, risk_score
        )
    else:
        stop_loss_pct = 0.05 if risk_score < 0.5 else 0.08
        take_profit_pct = 0.10 if risk_score < 0.5 else 0.08
        max_position_pct = 5.0 if risk_score < 0.5 else 3.0

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
            "max_position_pct": max_position_pct,
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
    strategy = await _get_active_strategy()

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

    # Phase 3: the LLM decides the action (structured), guarded by position
    # feasibility, with the existing rule signal as the fallback.
    rule_action = _signal_to_action_with_position(
        signal=consensus_signal,
        has_position=has_position,
        position_pnl_pct=position_pnl_pct,
    )
    action, response, decision_source, bull_case, bear_case = await decide_action(
        llm,
        messages,
        trade_action_cls=TradeAction,
        rule_action=rule_action,
        feasible=position_feasible_set(has_position),
        decision_schema=DECISION_SCHEMA,
        task=TaskType.STRATEGIC_DECISION,
    )
    if not response:
        response = (
            f"[룰 기반 결정] 컨센서스 {consensus_signal.value} → {action.value} (LLM 실패)"
        )
    if bull_case is None:
        bull_case = _extract_bull_case(response)
    if bear_case is None:
        bear_case = _extract_bear_case(response)

    logger.info(
        "kr_stock_action_determined",
        stk_cd=stk_cd,
        consensus_signal=consensus_signal.value,
        has_position=has_position,
        position_pnl_pct=position_pnl_pct,
        action=action.value,
        decision_source=decision_source,
    )

    # T2 MAJOR hard-gate: when market data could not be fetched this cycle
    # (market_data_stale set by the data-collection node — get_kr_* returned
    # None instead of fabricating random-mock data, CRITICAL fix 2026-07-14),
    # the analyses/consensus above ran on empty/neutral defaults with a
    # fabricated-absent price ("현재가: 0원"). An actionable proposal from that
    # context could be auto-approved by the 60s autonomy injector and — for a
    # real held position — execute a real SELL/REDUCE (which uses the position's
    # REAL quantity) on absent data. Force any actionable trade to HOLD
    # (no-trade) with floored confidence, as an override AFTER the LLM/consensus
    # produced its action, so stale data can NEVER yield an auto-executable
    # proposal. HOLD/WATCH/AVOID are already no-trade and pass through unchanged.
    if state.get("market_data_stale") and action in (
        TradeAction.BUY,
        TradeAction.ADD,
        TradeAction.SELL,
        TradeAction.REDUCE,
    ):
        logger.warning(
            "kr_stock_decision_hard_gated_stale",
            stk_cd=stk_cd,
            original_action=action.value,
        )
        stale_note = (
            f"[시세 데이터 불가로 결정 보류] 시세 조회 실패(stale)로 원래 제안 "
            f"{action.value}을(를) HOLD로 강제 전환했습니다. 신뢰할 수 있는 "
            f"현재가 없이는 매매를 실행하지 않습니다."
        )
        action = TradeAction.HOLD
        decision_source = "stale_hard_gate"
        avg_confidence = min(avg_confidence, 0.1)
        response = f"{stale_note}\n\n{response}"

    # Get risk parameters
    risk = state.get("risk_assessment", {})
    risk_signals = risk.get("signals", {})

    market_data = state.get("market_data", {})
    current_price = market_data.get("cur_prc", 0)
    position_size_pct = float(risk_signals.get("max_position_pct", 5.0))

    # S-4 (생존 규율, decision D4): stop_loss/take_profit 산출을 수량 계산
    # 앞으로 재배치 — 산식·폴백 자체는 완전히 불변(byte-identical), R 캡이
    # Proposal이 실제로 갖게 될 그 stop_loss 값을 그대로 수량 계산에서 쓸 수
    # 있도록 순서만 바뀐다.
    suggested_stop_loss = risk_signals.get(
        "suggested_stop_loss",
        int(current_price * (1 - strategy.exit_conditions.stop_loss_pct))
        if strategy else int(current_price * 0.95),
    )
    suggested_take_profit = risk_signals.get(
        "suggested_take_profit",
        int(current_price * (1 + strategy.exit_conditions.take_profit_pct))
        if strategy else int(current_price * 1.10),
    )

    # Calculate quantity based on action type and available balance
    quantity = 0
    if action in (TradeAction.BUY, TradeAction.ADD) and current_price > 0:
        try:
            client = await get_shared_kiwoom_client_async()
            cash_balance = await client.get_cash_balance()
            orderable_amount = cash_balance.ord_psbl_amt

            # Calculate quantity: (orderable * position_size%) / price
            investment_amount = int(orderable_amount * position_size_pct / 100)

            # S-4: R 기반 사이징 — 예산 risk_budget_pct%(계좌 적응 [0.25,1.5])
            # ÷ 손절거리 캡을 기존 notional 캡과 min() 결합(더 작은 쪽 채택).
            # r_cap_value 가드(거리<0.5% 등) 미충족 시 None -> 기존 값 유지.
            # equity는 이 사이징 경로가 애초에 쓰는 가용현금(orderable_amount)
            # 기준 — portfolio_agent의 계좌 총평가액 기준과는 이 경로가 원래
            # 갖고 있던 로컬 자본 베이스가 다르므로 의도적으로 그대로 둔다
            # (spec §1 "(a) 가용현금×pct").
            risk_budget_pct = await _get_risk_budget_pct()
            r_cap = r_cap_value(
                equity=orderable_amount,
                risk_budget_pct=risk_budget_pct,
                entry_price=current_price,
                stop_price=suggested_stop_loss,
            )
            if r_cap is not None and r_cap < investment_amount:
                logger.debug(
                    "kr_stock_r_cap_applied",
                    stk_cd=stk_cd,
                    investment_amount=investment_amount,
                    r_cap=r_cap,
                    risk_budget_pct=risk_budget_pct,
                )
                investment_amount = int(r_cap)

            # C1(유동성 인지): R-cap 결합 직후 유동성 참여율 캡을 적용한다.
            # equity 베이스는 이 경로가 원래 쓰는 orderable_amount 그대로 —
            # r_cap_value와 동일한 기준을 쓴다. ADTV 재조회는 별도 try/except로
            # 감싼다(never-raise) — 실패해도 R-cap까지 산정된 investment_amount를
            # 그대로 살리고 캡만 건너뛴다(fail-open); 바깥 큰 try에 맡기면
            # ADTV 조회 실패만으로 quantity가 통째로 0이 되어버린다.
            _adtv = None
            try:
                from services.discovery.liquidity import adtv_median
                _adtv = adtv_median(await client.get_daily_chart_df(stk_cd))
            except Exception as e:
                logger.warning("liquidity_adtv_fetch_failed", stk_cd=stk_cd, error=str(e))

            investment_amount, _liq_reason = apply_liquidity_cap(
                investment_amount, _adtv, orderable_amount
            )
            investment_amount = int(investment_amount)
            if _liq_reason in ("liquidity_cap", "liquidity_too_thin"):
                logger.info(
                    "liquidity_cap_applied",
                    stk_cd=stk_cd, reason=_liq_reason,
                    adtv=_adtv, investment_amount=investment_amount,
                )

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
        stop_loss=suggested_stop_loss,
        take_profit=suggested_take_profit,
        risk_score=float(risk_signals.get("risk_score", 0.5)),
        position_size_pct=position_size_pct,
        rationale=response,
        bull_case=bull_case,
        bear_case=bear_case,
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

            # Add to watch list. `or`-fallback: the session_id KEY exists with
            # value None when the route forgot to thread it (the dict.get
            # default only covers a missing key) — None here failed WatchedStock
            # validation and silently dropped every WATCH from the watch list.
            watched = coordinator.add_to_watch_list(
                session_id=state.get("session_id") or str(uuid.uuid4()),
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
