"""
Portfolio Agent

Manages portfolio allocation, position sizing, and rebalancing.
All decisions are based on risk parameters and current account state.
"""

import logging
from typing import Optional, List
from datetime import datetime

from .models import (
    AccountInfo,
    AllocationPlan,
    ManagedPosition,
    OrderRequest,
    OrderSide,
    OrderType,
    RiskParameters,
    TradingState,
)
from .r_sizing import apply_liquidity_cap, r_cap_value

logger = logging.getLogger(__name__)


class PortfolioAgent:
    """
    Portfolio management agent.

    Responsibilities:
    - Calculate optimal position sizes based on risk
    - Determine allocation for new trades
    - Suggest rebalancing when needed
    - Ensure risk limits are maintained
    """

    def __init__(self, risk_params: Optional[RiskParameters] = None):
        """
        Initialize Portfolio Agent.

        Args:
            risk_params: Risk parameters for allocation decisions
        """
        self.risk_params = risk_params or RiskParameters()

    def calculate_allocation(
        self,
        account: AccountInfo,
        ticker: str,
        stock_name: Optional[str],
        side: OrderSide,
        entry_price: float,
        risk_score: int,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        current_positions: Optional[List[ManagedPosition]] = None,
        adtv: Optional[float] = None,
    ) -> AllocationPlan:
        """
        Calculate optimal allocation for a new trade.

        Args:
            account: Current account information
            ticker: Stock ticker
            stock_name: Stock name
            side: Buy or sell
            entry_price: Planned entry price
            risk_score: Risk score from analysis (1-10)
            stop_loss: Stop-loss price
            take_profit: Take-profit price
            current_positions: Existing positions
            adtv: 일평균 거래대금(원). C1(유동성 인지) 사이징 캡의 입력 —
                None(기본)이면 캡 미적용(fail-open). 호출자(coordinator)가
                주문 직전 재계산해 넘긴다; 이 메서드 자체는 동기라 네트워크
                조회를 하지 않는다.

        Returns:
            AllocationPlan with quantity and any needed rebalancing
        """
        logger.info(
            f"[PortfolioAgent] Calculating allocation for {ticker} "
            f"(side={side}, price={entry_price}, risk={risk_score})"
        )

        current_positions = current_positions or []

        # Check if already holding this stock
        existing_position = next(
            (p for p in current_positions if p.ticker == ticker),
            None
        )

        if side == OrderSide.SELL:
            return self._calculate_sell_allocation(
                existing_position, ticker, stock_name, entry_price
            )

        # For BUY: calculate position size
        return self._calculate_buy_allocation(
            account=account,
            ticker=ticker,
            stock_name=stock_name,
            entry_price=entry_price,
            risk_score=risk_score,
            stop_loss=stop_loss,
            take_profit=take_profit,
            existing_position=existing_position,
            current_positions=current_positions,
            adtv=adtv,
        )

    def _calculate_buy_allocation(
        self,
        account: AccountInfo,
        ticker: str,
        stock_name: Optional[str],
        entry_price: float,
        risk_score: int,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        existing_position: Optional[ManagedPosition],
        current_positions: List[ManagedPosition],
        adtv: Optional[float] = None,
    ) -> AllocationPlan:
        """Calculate allocation for a BUY order."""

        # 1. Calculate available capital for this trade
        available_for_trade = self._calculate_available_capital(
            account, current_positions
        )

        if available_for_trade <= 0:
            logger.warning(
                f"[PortfolioAgent] No capital available for {ticker}"
            )
            return AllocationPlan(
                ticker=ticker,
                stock_name=stock_name,
                side=OrderSide.BUY,
                quantity=0,
                entry_price=entry_price,
                estimated_amount=0,
                position_pct=0,
                rationale="Insufficient capital - minimum cash reserve required",
            )

        # 2. Calculate position size based on risk
        # U3 (사이징 계보, 2026-08-05): 어느 캡이 실제로 물었는지 관찰만
        # 한다 — sizing_lineage는 계산에 아무 영향을 주지 않는 out-param
        # 이고, 여기서는 관측성을 위해 로그로만 남긴다. agent_chat_decisions
        # 행 하나로 이 계보를 귀속시키려면 이 지점에 없는 decision_id가
        # 필요한데(calculate_allocation은 동기 함수이고 유일한 호출부인
        # coordinator.on_trade_approved도 그 id를 여기로 넘기지 않는다),
        # 그 배선은 이 태스크의 선언된 파일 범위(portfolio_agent.py/
        # storage_service.py) 밖이라 여기서는 하지 않는다 — 스키마
        # (storage_service.py의 sizing_lineage 컬럼)와 저장 접점
        # (save_agent_chat_decision의 sizing_lineage 키)만 준비해 둔다.
        sizing_lineage: dict = {}
        max_position_value = self._calculate_max_position_value(
            account.total_equity, risk_score,
            entry_price=entry_price, stop_loss=stop_loss,
            adtv=adtv, lineage=sizing_lineage,
        )
        if sizing_lineage:
            logger.debug(f"[PortfolioAgent] sizing lineage: {sizing_lineage}")

        # 3. Consider existing position
        if existing_position:
            current_value = existing_position.quantity * existing_position.current_price
            current_position_pct = (current_value / account.total_equity) * 100 if account.total_equity > 0 else 0

            # Check if already at or above max position
            if current_value >= max_position_value:
                logger.warning(
                    f"[PortfolioAgent] {ticker} already at max position: "
                    f"{existing_position.quantity}주 ({current_position_pct:.1f}%)"
                )
                return AllocationPlan(
                    ticker=ticker,
                    stock_name=stock_name,
                    side=OrderSide.BUY,
                    quantity=0,
                    entry_price=entry_price,
                    estimated_amount=0,
                    position_pct=0,
                    rationale=f"이미 보유 중: {existing_position.quantity}주 ({current_position_pct:.1f}%) - 추가 매수 불가 (최대 포지션 도달)",
                )

            # Calculate remaining allowed position
            max_position_value = max_position_value - current_value

        # 4. Apply constraints
        position_value = min(available_for_trade, max_position_value)

        # 5. Calculate quantity
        quantity = int(position_value / entry_price)

        if quantity <= 0:
            rationale = "Position size too small after risk adjustment"
            if existing_position:
                existing_pct = (existing_position.quantity * existing_position.current_price / account.total_equity) * 100 if account.total_equity > 0 else 0
                rationale = f"추가 매수 불가: 이미 {existing_position.quantity}주 보유 ({existing_pct:.1f}%)"
            return AllocationPlan(
                ticker=ticker,
                stock_name=stock_name,
                side=OrderSide.BUY,
                quantity=0,
                entry_price=entry_price,
                estimated_amount=0,
                position_pct=0,
                rationale=rationale,
            )

        # 6. Final calculations
        estimated_amount = quantity * entry_price
        position_pct = (estimated_amount / account.total_equity) * 100 if account.total_equity > 0 else 0

        # 7. Check if rebalancing is needed
        rebalance_orders = self._check_rebalancing_needed(
            account, current_positions, estimated_amount
        )

        rationale = self._build_rationale(
            risk_score, position_pct, existing_position is not None
        )

        logger.info(
            f"[PortfolioAgent] Allocation: {quantity} shares @ {entry_price} "
            f"= {estimated_amount:,.0f} ({position_pct:.1f}% of equity)"
        )

        return AllocationPlan(
            ticker=ticker,
            stock_name=stock_name,
            side=OrderSide.BUY,
            quantity=quantity,
            entry_price=entry_price,
            estimated_amount=estimated_amount,
            position_pct=position_pct,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_score=risk_score,
            rebalance_orders=rebalance_orders,
            rationale=rationale,
        )

    def _calculate_sell_allocation(
        self,
        existing_position: Optional[ManagedPosition],
        ticker: str,
        stock_name: Optional[str],
        price: float,
    ) -> AllocationPlan:
        """Calculate allocation for a SELL order."""

        if not existing_position:
            return AllocationPlan(
                ticker=ticker,
                stock_name=stock_name,
                side=OrderSide.SELL,
                quantity=0,
                entry_price=price,
                estimated_amount=0,
                position_pct=0,
                rationale="No position to sell",
            )

        return AllocationPlan(
            ticker=ticker,
            stock_name=stock_name,
            side=OrderSide.SELL,
            quantity=existing_position.quantity,
            entry_price=price,
            estimated_amount=existing_position.quantity * price,
            position_pct=0,  # Will be 0 after sell
            rationale="Full position liquidation",
        )

    def _calculate_available_capital(
        self,
        account: AccountInfo,
        current_positions: List[ManagedPosition],
    ) -> float:
        """Calculate capital available for new trades."""

        # Must maintain minimum cash reserve
        min_cash = account.total_equity * self.risk_params.min_cash_ratio
        available = account.available_cash - min_cash

        # Check total stock allocation limit
        current_stock_value = sum(
            p.quantity * p.current_price for p in current_positions
        )
        max_stock_value = account.total_equity * self.risk_params.max_total_stock_pct
        stock_headroom = max_stock_value - current_stock_value

        return max(0, min(available, stock_headroom))

    def _calculate_max_position_value(
        self,
        total_equity: float,
        risk_score: int,
        entry_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        adtv: Optional[float] = None,
        lineage: Optional[dict] = None,
    ) -> float:
        """
        Calculate maximum position value based on risk.

        Higher risk score = smaller position. S-4 (생존 규율, decision D4):
        additionally min()-combined with the R-based risk-budget cap
        (equity * risk_budget_pct% / stop distance) — whichever of the two
        is SMALLER wins, so this can only ever tighten sizing, never loosen
        it. entry_price/stop_loss default to None so existing callers that
        don't have a stop yet stay call-compatible; r_cap_value's own guard
        then simply doesn't apply (returns None -> no change here).

        C1 (유동성 인지, 2026-07-27): R-cap 결합 다음으로 유동성 참여율 캡을
        추가로 결합한다. `adtv`도 기본값 None이라 기존 호출부는 캡 미적용
        (fail-open)으로 동작이 완전히 그대로다.

        U3 (사이징 계보, 2026-08-05): `lineage`는 선택적 out-param dict다 —
        entry_price/stop_loss/adtv와 같은 패턴으로, 넘기지 않으면(기본
        None) 관찰 코드가 전부 스킵되어 기존 호출부는 바이트 단위로 동일하게
        동작한다. 넘기면 이미 계산되는 중간값(base_max/risk_factor/
        risk_bucket_cap/r_cap/liquidity_cap)과 실제로 반환값을 만든 캡의
        이름(binding)을 기록한다 — 계산식/순서/반올림/클램프는 한 글자도
        바꾸지 않는다. 패자 평균 명목이 승자의 1.27배(등가중 +0.92% vs
        자본가중 -0.39%)인 원인이 risk_score 배수인지 유동성 캡인지
        기록이 없어 분리할 수 없었던 것을 이 out-param이 메운다.
        """
        base_max = total_equity * self.risk_params.max_single_position_pct

        # Risk adjustment: reduce position for higher risk
        # Risk 1-3: 100% of max
        # Risk 4-6: 70% of max
        # Risk 7-10: 50% of max
        if risk_score <= 3:
            risk_factor = 1.0
        elif risk_score <= 6:
            risk_factor = 0.7
        else:
            risk_factor = 0.5

        max_value = base_max * risk_factor
        risk_bucket_cap = max_value

        r_cap = r_cap_value(
            equity=total_equity,
            risk_budget_pct=self.risk_params.risk_budget_pct,
            entry_price=entry_price if entry_price is not None else 0,
            stop_price=stop_loss,
        )
        r_cap_applied = False
        if r_cap is not None and r_cap < max_value:
            logger.debug(
                f"[PortfolioAgent] R cap {r_cap:,.0f} tighter than risk-bucket "
                f"cap {max_value:,.0f} — adopting R cap "
                f"(risk_budget_pct={self.risk_params.risk_budget_pct}%)"
            )
            max_value = r_cap
            r_cap_applied = True

        # C1(유동성 인지): 유동성 참여율 캡을 마지막에 결합한다. adtv=None이면
        # 캡 미적용(fail-open) — A1 게이트를 이미 통과한 종목이다.
        max_value, liq_reason = apply_liquidity_cap(max_value, adtv, total_equity)
        if liq_reason in ("liquidity_cap", "liquidity_too_thin"):
            logger.info(
                f"[PortfolioAgent] 유동성 캡 적용: reason={liq_reason} "
                f"adtv={adtv} max_value={max_value:,.0f}"
            )
        elif liq_reason == "adtv_unknown":
            # 리뷰 Important2(b): 캡이 전 주문에서 비활성인데 아무 로그도
            # 없으면 데이터 품질 저하(ADTV 조회 실패/부족)를 아무도 알아채지
            # 못한다 — 여기서만 발생하는 게 아니라 사이징 시점마다 반복되면
            # 그게 바로 알아야 할 신호다.
            logger.warning(
                f"[PortfolioAgent] 유동성 캡 미적용(adtv_unknown): "
                f"max_value={max_value:,.0f} — R-cap/포지션 캡만 적용됨"
            )
        elif liq_reason == "skip_floor_disabled":
            # 최종 리뷰 Blocking3: 계좌 평가액이 0 이하라 skip-floor(과소포지션
            # 진입 포기)를 평가할 수 없었다. 캡 자체는 결합됐지만 방어선 하나가
            # 빠진 상태이므로 조용히 지나가면 안 된다.
            logger.warning(
                f"[PortfolioAgent] skip-floor 미평가(total_equity={total_equity}) "
                f"— 유동성 캡만 결합됨 max_value={max_value:,.0f}"
            )

        if lineage is not None:
            # 순수함수 liquidity_cap_value를 여기서 한 번 더 부르는 것은
            # apply_liquidity_cap 내부가 하는 계산과 완전히 동일한
            # 계산(같은 adtv 입력)이라 max_value에는 아무 영향이 없다 —
            # 관찰 전용 재계산이다. r_cap과 대칭으로 "이겼든 졌든 계산되면
            # 기록"한다: adtv_unknown(ADTV 자체가 없어 계산이 성립하지
            # 않는 경우)만 None이고, 그 밖의 사유(liquidity_cap/
            # liquidity_too_thin/skip_floor_disabled/None)는 실 ADTV로
            # 캡이 계산됐다는 뜻이므로 값을 남긴다.
            from services.discovery.liquidity import liquidity_cap_value

            lineage["base_max"] = base_max
            lineage["risk_factor"] = risk_factor
            lineage["risk_bucket_cap"] = risk_bucket_cap
            lineage["r_cap"] = r_cap
            lineage["liquidity_cap"] = liquidity_cap_value(adtv)

            # 승자 판정: 결합 순서(risk_bucket_cap -> r_cap -> liquidity_cap)
            # 그대로 앞선 캡부터 확인한다. 유동성이 실제로 이 값을 만들었으면
            # (liquidity_cap 또는 liquidity_too_thin — 후자는 반환값이 0.0이라
            # liq 캡 원값과 더 이상 같지 않으므로 값 비교가 아니라 reason으로
            # 판정) 유동성이 승자다. 그렇지 않고 r_cap이 위에서 실제로 채택
            # 됐으면(r_cap_applied) r_cap이 승자다. 둘 다 아니면 risk_bucket_cap
            # 이 처음부터 끝까지 안 바뀐 것이다. 동률(r_cap == risk_bucket_cap)
            # 은 위의 엄격한 '<' 비교 때문에 애초에 r_cap_applied가 False로
            # 남아 risk_bucket_cap 쪽으로 귀속된다 — "동률이면 더 앞선(더
            # 보수적으로 적용된) 캡" 규칙과 실제 결합 코드의 strict-less-than
            # 의미가 정확히 일치한다.
            if liq_reason in ("liquidity_cap", "liquidity_too_thin"):
                lineage["binding"] = "liquidity_cap"
            elif r_cap_applied:
                lineage["binding"] = "r_cap"
            else:
                lineage["binding"] = "risk_bucket_cap"

        return max_value

    async def _resolve_adtv(self, ticker: str) -> Optional[float]:
        """사이징 시점의 ADTV(원). 승격(EOD)과 진입(수일 후) 사이 유동성이
        바뀔 수 있어 최신 일봉으로 재계산하고, 실패하면 승격 당시
        `scan_results.factor_json.adtv20_med`(T3가 저장)로 폴백한다.

        never-raise: 둘 다 실패하면 None을 반환하고 `apply_liquidity_cap`이
        캡 미적용(fail-open)으로 처리한다.

        (2026-07-27 리뷰 수정: 최초 구현 당시 `discovery_candidates`/
        `WatchedStock`에 factor_json 저장 경로가 없어 폴백이 불가능하다고
        판단했었다. 그 판단은 틀렸다 — T3는 `scan_results` 테이블에
        저장하고 있었다(`stk_cd` 인덱스 有). `_stored_adtv`가 그 경로를
        조회한다.)
        """
        from app.config import settings
        from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
        from services.discovery.liquidity import adtv_median

        # C1 킬스위치(설계 §6, 최종 리뷰 Blocking2): off면 ADTV를 아예 구하지
        # 않고 None을 반환해 `apply_liquidity_cap`의 기존 fail-open 경로
        # ("adtv_unknown", 캡 미적용)로 수렴한다. R-cap과 포지션 캡은 계속
        # 작동한다. decision_nodes.py의 다른 사이징 호출부도 같은 스위치를 본다.
        if not getattr(settings, "LIQUIDITY_SIZING_CAP_ENABLED", True):
            logger.warning(
                f"[PortfolioAgent] 유동성 사이징 캡 킬스위치 off "
                f"(LIQUIDITY_SIZING_CAP_ENABLED=False) — {ticker} 캡 미적용"
            )
            return None

        try:
            client = await get_shared_kiwoom_client_async()
            df = await client.get_daily_chart_df(ticker)
            adtv = adtv_median(df)
            if adtv is not None:
                return adtv
            logger.info(
                f"[PortfolioAgent] ADTV 재계산이 None을 반환({ticker}) — "
                f"표본 부족/거래대금 결측. 저장값 폴백을 시도한다."
            )
        except Exception as e:
            logger.warning(f"[PortfolioAgent] ADTV 재계산 실패 {ticker}: {e}")

        try:
            return await self._stored_adtv(ticker)
        except Exception as e:
            logger.warning(f"[PortfolioAgent] 저장 ADTV 폴백 실패 {ticker}: {e}")
            return None

    async def _stored_adtv(self, ticker: str) -> Optional[float]:
        """승격(EOD) 당시 `scan_results.factor_json.adtv20_med`로의 폴백 조회
        (T3가 씀 — `services/background_scanner/scanner.py`). `_resolve_adtv`
        의 라이브 재계산이 실패했을 때만 호출된다. never-raise(호출부인
        `BackgroundScanner.get_latest_adtv` 자체가 never-raise)."""
        from services.background_scanner.scanner import get_background_scanner

        scanner = await get_background_scanner()
        return await scanner.get_latest_adtv(ticker)

    def _check_rebalancing_needed(
        self,
        account: AccountInfo,
        positions: List[ManagedPosition],
        new_trade_amount: float,
    ) -> List[OrderRequest]:
        """Check if rebalancing is needed to accommodate new trade."""
        rebalance_orders = []

        # Check if new trade would exceed max stock allocation
        current_stock_value = sum(p.quantity * p.current_price for p in positions)
        projected_stock_value = current_stock_value + new_trade_amount
        max_stock_value = account.total_equity * self.risk_params.max_total_stock_pct

        if projected_stock_value > max_stock_value:
            excess = projected_stock_value - max_stock_value

            # Find positions to reduce (prioritize worst performers)
            sorted_positions = sorted(
                positions,
                key=lambda p: p.unrealized_pnl_pct
            )

            for pos in sorted_positions:
                if excess <= 0:
                    break

                # Calculate how much to sell
                pos_value = pos.quantity * pos.current_price
                sell_value = min(pos_value, excess)
                sell_qty = int(sell_value / pos.current_price)

                if sell_qty > 0:
                    # L2 (spec D2): decision_id/session_id left unset (NULL)
                    # on purpose — a portfolio-rebalance liquidation has no
                    # upstream decision record to thread; NULL is the
                    # correct lineage state here, not a gap to wire.
                    # S-3 (survival discipline): MARKET, not the
                    # OrderRequest default of LIMIT — a rebalance sell is a
                    # system-initiated liquidation of an UNRELATED position,
                    # same category as a defensive stop-loss/take-profit
                    # exit (risk_monitor.py's P2-4 convention). `price` is
                    # now set explicitly too (previously omitted entirely,
                    # leaving it None) — MARKET orders never send this to
                    # the broker, but it's still the mock/paper broker's
                    # fill-price fallback and the live fill-confirm's
                    # fallback_price, same as every other MARKET site.
                    rebalance_orders.append(OrderRequest(
                        ticker=pos.ticker,
                        stock_name=pos.stock_name,
                        side=OrderSide.SELL,
                        quantity=sell_qty,
                        price=pos.current_price,
                        order_type=OrderType.MARKET,
                        reason=f"Rebalancing to accommodate new position",
                    ))
                    excess -= sell_qty * pos.current_price

        return rebalance_orders

    def _build_rationale(
        self,
        risk_score: int,
        position_pct: float,
        is_addition: bool,
    ) -> str:
        """Build human-readable rationale for allocation."""
        parts = []

        if risk_score <= 3:
            parts.append(f"Low risk (score: {risk_score}/10)")
        elif risk_score <= 6:
            parts.append(f"Medium risk (score: {risk_score}/10)")
        else:
            parts.append(f"High risk (score: {risk_score}/10) - reduced position")

        parts.append(f"Position size: {position_pct:.1f}% of portfolio")

        if is_addition:
            parts.append("Adding to existing position")

        return " | ".join(parts)

    def suggest_rebalancing(
        self,
        state: TradingState,
    ) -> Optional[List[OrderRequest]]:
        """
        Analyze portfolio and suggest rebalancing if needed.

        Returns:
            List of rebalancing orders, or None if not needed
        """
        if not state.positions:
            return None

        rebalance_orders = []
        total_equity = state.account.total_equity

        for position in state.positions:
            pos_value = position.quantity * position.current_price
            pos_pct = (pos_value / total_equity) * 100 if total_equity > 0 else 0

            # Check if position exceeds max single position
            max_pct = self.risk_params.max_single_position_pct * 100

            if pos_pct > max_pct * 1.1:  # 10% tolerance
                excess_pct = pos_pct - max_pct
                excess_value = (excess_pct / 100) * total_equity
                sell_qty = int(excess_value / position.current_price)

                if sell_qty > 0:
                    # L2 (spec D2): decision_id/session_id left unset (NULL)
                    # — same rationale as the rebalance SELL above.
                    # S-3: MARKET + explicit price — same rationale as
                    # _check_rebalancing_needed's rebalance SELL above.
                    rebalance_orders.append(OrderRequest(
                        ticker=position.ticker,
                        stock_name=position.stock_name,
                        side=OrderSide.SELL,
                        quantity=sell_qty,
                        price=position.current_price,
                        order_type=OrderType.MARKET,
                        reason=f"Position exceeds max allocation ({pos_pct:.1f}% > {max_pct:.1f}%)",
                    ))

        return rebalance_orders if rebalance_orders else None

    def get_portfolio_summary(
        self,
        state: TradingState,
    ) -> dict:
        """Get portfolio summary for display."""
        positions_summary = []

        for pos in state.positions:
            pos_value = pos.quantity * pos.current_price
            pos_pct = (pos_value / state.account.total_equity) * 100 if state.account.total_equity > 0 else 0

            positions_summary.append({
                "ticker": pos.ticker,
                "stock_name": pos.stock_name,
                "quantity": pos.quantity,
                "avg_price": pos.avg_price,
                "current_price": pos.current_price,
                "value": pos_value,
                "weight_pct": pos_pct,
                "unrealized_pnl": pos.unrealized_pnl,
                "unrealized_pnl_pct": pos.unrealized_pnl_pct,
                "risk_score": pos.risk_score,
            })

        return {
            "total_equity": state.account.total_equity,
            "cash": state.account.available_cash,
            "cash_ratio": state.account.cash_ratio * 100,
            "stock_value": state.account.total_stock_value,
            "stock_ratio": state.account.stock_ratio * 100,
            "positions": positions_summary,
            "total_unrealized_pnl": state.total_unrealized_pnl,
            "total_unrealized_pnl_pct": state.total_unrealized_pnl_pct,
            "daily_trades": state.daily_trades_count,
            "max_daily_trades": state.risk_params.max_daily_trades,
        }
