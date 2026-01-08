"""
Chat Coordinator

Manages multiple chat rooms and coordinates with the trading system.
Handles watch list monitoring, opportunity detection, and trade execution.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from services.agent_chat.models import (
    ChatSession,
    DecisionAction,
    MarketContext,
    SessionStatus,
    TradeDecision,
)
from services.agent_chat.chat_room import ChatRoom
from services.agent_chat.position_manager import (
    PositionManager,
    get_position_manager,
)

logger = structlog.get_logger()


class ChatCoordinator:
    """
    Coordinates agent chat discussions for trading decisions.

    Responsibilities:
    - Monitor watch list stocks for opportunities
    - Create and manage chat rooms for discussions
    - Execute approved trades
    - Track session history
    """

    def __init__(
        self,
        check_interval_minutes: int = 5,
        max_concurrent_discussions: int = 3,
        min_discussion_interval_minutes: int = 30,
    ):
        """
        Initialize chat coordinator.

        Args:
            check_interval_minutes: How often to check watch list
            max_concurrent_discussions: Max simultaneous discussions
            min_discussion_interval_minutes: Min time between discussions for same stock
        """
        self.check_interval = check_interval_minutes
        self.max_concurrent = max_concurrent_discussions
        self.min_interval = timedelta(minutes=min_discussion_interval_minutes)

        # Active chat rooms
        self._active_rooms: Dict[str, ChatRoom] = {}  # ticker -> room

        # Session history
        self._session_history: List[ChatSession] = []
        self._last_discussion: Dict[str, datetime] = {}  # ticker -> last discussion time

        # Scheduler for periodic checks
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._running = False

        # Callbacks
        self._on_decision_callbacks: List[Callable] = []
        self._on_session_complete_callbacks: List[Callable] = []

        # Position manager (will be initialized in start())
        self._position_manager: Optional[PositionManager] = None

        logger.info(
            "chat_coordinator_initialized",
            check_interval=check_interval_minutes,
            max_concurrent=max_concurrent_discussions,
        )

    def on_decision(self, callback: Callable) -> None:
        """Register callback for trading decisions."""
        self._on_decision_callbacks.append(callback)

    def on_session_complete(self, callback: Callable) -> None:
        """Register callback for completed sessions."""
        self._on_session_complete_callbacks.append(callback)

    async def start(self) -> None:
        """Start the coordinator with scheduled monitoring."""
        if self._running:
            logger.warning("chat_coordinator_already_running")
            return

        logger.info("chat_coordinator_starting")

        self._running = True
        self._scheduler = AsyncIOScheduler()

        # Initialize and start position manager
        self._position_manager = await get_position_manager()
        self._position_manager.set_chat_coordinator(self)
        await self._position_manager.start()

        # Sync positions from account
        await self._position_manager.sync_from_account()

        # Schedule periodic watch list check
        self._scheduler.add_job(
            self._check_watch_list,
            'interval',
            minutes=self.check_interval,
            id='watch_list_check',
            next_run_time=datetime.now(),  # Run immediately
        )

        self._scheduler.start()

        logger.info(
            "chat_coordinator_started",
            check_interval=self.check_interval,
            positions_monitored=len(self._position_manager.get_all_positions()),
        )

    async def stop(self) -> None:
        """Stop the coordinator."""
        if not self._running:
            return

        logger.info("chat_coordinator_stopping")

        self._running = False

        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

        # Stop position manager
        if self._position_manager:
            await self._position_manager.stop()

        # Cancel active rooms
        for ticker, room in list(self._active_rooms.items()):
            await room.cancel()

        self._active_rooms.clear()

        logger.info("chat_coordinator_stopped")

    @property
    def position_manager(self) -> Optional[PositionManager]:
        """Get position manager instance."""
        return self._position_manager

    async def _check_watch_list(self) -> None:
        """Check watch list for discussion opportunities."""
        if not self._running:
            return

        logger.debug("checking_watch_list")

        try:
            # Get active watch list stocks
            watch_list = await self._get_watch_list()

            if not watch_list:
                logger.debug("watch_list_empty")
                return

            # Check each stock for opportunity
            opportunities = []
            for stock in watch_list:
                ticker = stock.get("ticker")
                if not ticker:
                    continue

                # Skip if already discussing
                if ticker in self._active_rooms:
                    continue

                # Skip if recently discussed
                if self._was_recently_discussed(ticker):
                    continue

                # Check if opportunity exists
                should_discuss = await self._detect_opportunity(stock)
                if should_discuss:
                    opportunities.append(stock)

            # Start discussions for opportunities (up to max concurrent)
            available_slots = self.max_concurrent - len(self._active_rooms)
            for stock in opportunities[:available_slots]:
                await self._start_discussion(stock)

        except Exception as e:
            logger.error("watch_list_check_failed", error=str(e))

    async def _get_watch_list(self) -> List[dict]:
        """Get active watch list stocks from trading coordinator."""
        try:
            from app.dependencies import get_trading_coordinator
            trading_coord = await get_trading_coordinator()
            watch_items = trading_coord.get_watch_list()

            return [
                {
                    "ticker": w.ticker,
                    "stock_name": w.stock_name,
                    "signal": w.signal,
                    "confidence": w.confidence,
                    "current_price": w.current_price,
                    "target_entry_price": w.target_entry_price,
                    "stop_loss": w.stop_loss,
                    "take_profit": w.take_profit,
                }
                for w in watch_items
                if w.status.value == "active"
            ]
        except Exception as e:
            logger.warning("get_watch_list_failed", error=str(e))
            return []

    def _was_recently_discussed(self, ticker: str) -> bool:
        """Check if stock was discussed recently."""
        last_time = self._last_discussion.get(ticker)
        if not last_time:
            return False
        return datetime.now() - last_time < self.min_interval

    async def _detect_opportunity(self, stock: dict) -> bool:
        """
        Detect if a stock presents a trading opportunity.

        Criteria:
        - Price near target entry
        - Significant price movement
        - High confidence signal
        """
        ticker = stock.get("ticker")
        current_price = stock.get("current_price", 0)
        target_price = stock.get("target_entry_price")
        confidence = stock.get("confidence", 0)

        # Check if price is near target (within 3%)
        if target_price and current_price:
            price_diff = abs(current_price - target_price) / target_price
            if price_diff <= 0.03:
                logger.info(
                    "opportunity_detected_target_reached",
                    ticker=ticker,
                    current=current_price,
                    target=target_price,
                )
                return True

        # Check for high confidence
        if confidence >= 0.75:
            logger.info(
                "opportunity_detected_high_confidence",
                ticker=ticker,
                confidence=confidence,
            )
            return True

        return False

    async def _start_discussion(self, stock: dict) -> None:
        """Start a new discussion for a stock."""
        ticker = stock["ticker"]
        stock_name = stock.get("stock_name", ticker)

        logger.info(
            "starting_discussion",
            ticker=ticker,
            stock_name=stock_name,
        )

        try:
            # Fetch market context
            context = await self._fetch_market_context(ticker, stock_name)

            # Create chat room
            room = ChatRoom(
                ticker=ticker,
                stock_name=stock_name,
                context=context,
            )

            # Register callbacks
            room.on_status_change(self._on_room_status_change)

            self._active_rooms[ticker] = room

            # Start discussion in background
            asyncio.create_task(self._run_discussion(ticker, room))

        except Exception as e:
            logger.error(
                "start_discussion_failed",
                ticker=ticker,
                error=str(e),
            )

    async def _run_discussion(self, ticker: str, room: ChatRoom) -> None:
        """Run a discussion and handle the result."""
        try:
            session = await room.start()

            # Record last discussion time
            self._last_discussion[ticker] = datetime.now()

            # Store in history
            self._session_history.append(session)
            if len(self._session_history) > 100:  # Keep last 100
                self._session_history = self._session_history[-100:]

            # Handle decision
            if session.decision:
                await self._handle_decision(ticker, session.decision)

            # Notify callbacks
            for callback in self._on_session_complete_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(session)
                    else:
                        callback(session)
                except Exception as e:
                    logger.warning("session_complete_callback_failed", error=str(e))

        except Exception as e:
            logger.error(
                "discussion_failed",
                ticker=ticker,
                error=str(e),
            )
        finally:
            # Remove from active rooms
            self._active_rooms.pop(ticker, None)

    async def _on_room_status_change(
        self,
        status: SessionStatus,
        session: ChatSession,
    ) -> None:
        """Handle room status changes."""
        logger.info(
            "room_status_changed",
            ticker=session.ticker,
            status=status.value,
        )

    async def _handle_decision(
        self,
        ticker: str,
        decision: TradeDecision,
    ) -> None:
        """Handle a trading decision from the discussion."""
        logger.info(
            "handling_decision",
            ticker=ticker,
            action=decision.action.value,
            confidence=decision.confidence,
            consensus=decision.consensus_level,
        )

        # Notify decision callbacks
        for callback in self._on_decision_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(ticker, decision)
                else:
                    callback(ticker, decision)
            except Exception as e:
                logger.warning("decision_callback_failed", error=str(e))

        # Execute trade if action required
        if decision.action in (
            DecisionAction.BUY,
            DecisionAction.SELL,
            DecisionAction.ADD,
            DecisionAction.REDUCE,
        ):
            await self._execute_trade(ticker, decision)

        # Send Telegram notification
        await self._notify_decision(ticker, decision)

    async def _execute_trade(
        self,
        ticker: str,
        decision: TradeDecision,
    ) -> None:
        """Execute the trading decision."""
        logger.info(
            "executing_trade",
            ticker=ticker,
            action=decision.action.value,
            quantity=decision.quantity,
        )

        try:
            from app.dependencies import get_trading_coordinator
            trading_coord = await get_trading_coordinator()

            # Map decision action to trade action
            action_map = {
                DecisionAction.BUY: "BUY",
                DecisionAction.SELL: "SELL",
                DecisionAction.ADD: "ADD",
                DecisionAction.REDUCE: "REDUCE",
            }
            action = action_map.get(decision.action)

            if action:
                # Execute via trading coordinator
                await trading_coord.on_trade_approved(
                    session_id=f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    ticker=ticker,
                    stock_name=None,  # Will be looked up
                    action=action,
                    entry_price=decision.entry_price,
                    stop_loss=decision.stop_loss,
                    take_profit=decision.take_profit,
                    risk_score=int((1 - decision.confidence) * 10),
                    quantity_override=decision.quantity,
                )

                logger.info(
                    "trade_executed",
                    ticker=ticker,
                    action=action,
                )

        except Exception as e:
            logger.error(
                "trade_execution_failed",
                ticker=ticker,
                error=str(e),
            )

    async def _notify_decision(
        self,
        ticker: str,
        decision: TradeDecision,
    ) -> None:
        """Send Telegram notification for decision."""
        try:
            from services.telegram import get_telegram_notifier
            telegram = await get_telegram_notifier()

            if telegram.is_ready:
                action_emoji = {
                    DecisionAction.BUY: "🟢",
                    DecisionAction.SELL: "🔴",
                    DecisionAction.ADD: "🟢➕",
                    DecisionAction.REDUCE: "🔴➖",
                    DecisionAction.HOLD: "⏸️",
                    DecisionAction.WATCH: "👁",
                    DecisionAction.NO_ACTION: "⏹️",
                }

                emoji = action_emoji.get(decision.action, "📋")

                message = f"""{emoji} *Agent Group Chat 결정*

*종목:* {ticker}
*결정:* {decision.action.value}
*신뢰도:* {decision.confidence:.0%}
*합의 수준:* {decision.consensus_level:.0%}
"""

                if decision.action in (DecisionAction.BUY, DecisionAction.ADD):
                    message += f"""
*매수 계획:*
- 수량: {decision.quantity or 'TBD'}주
- 진입가: ₩{decision.entry_price:,}
- 손절가: ₩{decision.stop_loss:,}
- 익절가: ₩{decision.take_profit:,}
"""

                if decision.key_factors:
                    message += f"\n*핵심 요인:*\n"
                    for factor in decision.key_factors[:3]:
                        message += f"• {factor}\n"

                await telegram.send_message(message)

        except Exception as e:
            logger.warning("telegram_notification_failed", error=str(e))

    async def _fetch_market_context(
        self,
        ticker: str,
        stock_name: str,
    ) -> MarketContext:
        """Fetch market data for discussion context."""
        logger.info(
            "fetching_market_context",
            ticker=ticker,
        )

        try:
            from agents.tools.kr_market_data import (
                get_kr_stock_info,
                get_kr_daily_chart,
                calculate_kr_technical_indicators,
            )
            from app.core.kiwoom_singleton import get_shared_kiwoom_client_async

            # Fetch stock info
            stock_info = await get_kr_stock_info(ticker)

            # Fetch chart data
            chart_df = await get_kr_daily_chart(ticker)

            # Calculate indicators
            import pandas as pd
            if not chart_df.empty:
                indicators = calculate_kr_technical_indicators(chart_df)
                chart_data = [
                    {
                        "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
                        "open": int(row["open"]),
                        "high": int(row["high"]),
                        "low": int(row["low"]),
                        "close": int(row["close"]),
                        "volume": int(row["volume"]),
                    }
                    for idx, row in chart_df.iterrows()
                ]
            else:
                indicators = {}
                chart_data = []

            # Fetch portfolio info
            has_position = False
            position_quantity = None
            position_avg_price = None
            position_pnl_pct = None
            available_cash = None
            total_portfolio = None

            try:
                client = await get_shared_kiwoom_client_async()
                account = await client.get_account_balance()

                available_cash = account.d2_ord_psbl_amt
                total_portfolio = account.evlu_amt + account.d2_ord_psbl_amt

                for holding in account.holdings:
                    if holding.stk_cd == ticker:
                        has_position = True
                        position_quantity = holding.hldg_qty
                        position_avg_price = holding.avg_buy_prc
                        position_pnl_pct = holding.evlu_pfls_rt
                        break
            except Exception as e:
                logger.warning("portfolio_fetch_failed", error=str(e))

            # Fetch news sentiment
            news_sentiment = None
            news_count = 0
            try:
                from app.dependencies import get_news_service
                news_service = await get_news_service()
                if news_service.providers:
                    result = await news_service.search_stock_news(
                        stock_code=ticker,
                        stock_name=stock_name,
                        count=50,
                    )
                    news_count = len(result.articles)

                    # Simple sentiment calculation
                    if news_count > 0:
                        # Use price momentum as proxy if no analyzer
                        change = stock_info.get("prdy_ctrt", 0)
                        if change > 2:
                            news_sentiment = "positive"
                        elif change < -2:
                            news_sentiment = "negative"
                        else:
                            news_sentiment = "neutral"
            except Exception as e:
                logger.warning("news_fetch_failed", error=str(e))

            return MarketContext(
                ticker=ticker,
                stock_name=stock_name or stock_info.get("stk_nm", ticker),
                current_price=stock_info.get("cur_prc", 0),
                price_change_pct=stock_info.get("prdy_ctrt", 0),
                chart_data=chart_data,
                indicators=indicators,
                per=stock_info.get("per"),
                pbr=stock_info.get("pbr"),
                eps=stock_info.get("eps"),
                market_cap=stock_info.get("mrkt_tot_amt"),
                news_sentiment=news_sentiment,
                news_count=news_count,
                has_position=has_position,
                position_quantity=position_quantity,
                position_avg_price=position_avg_price,
                position_pnl_pct=position_pnl_pct,
                available_cash=available_cash,
                total_portfolio_value=total_portfolio,
            )

        except Exception as e:
            logger.error(
                "market_context_fetch_failed",
                ticker=ticker,
                error=str(e),
            )
            # Return minimal context
            return MarketContext(
                ticker=ticker,
                stock_name=stock_name,
                current_price=0,
                price_change_pct=0,
            )

    # -------------------------------------------
    # Manual Discussion API
    # -------------------------------------------

    async def start_manual_discussion(
        self,
        ticker: str,
        stock_name: str,
    ) -> ChatSession:
        """
        Start a manual discussion for a stock (not from watch list).

        Args:
            ticker: Stock ticker
            stock_name: Stock name

        Returns:
            Completed ChatSession
        """
        logger.info(
            "starting_manual_discussion",
            ticker=ticker,
            stock_name=stock_name,
        )

        # Check if already discussing
        if ticker in self._active_rooms:
            raise ValueError(f"Discussion already in progress for {ticker}")

        # Fetch context
        context = await self._fetch_market_context(ticker, stock_name)

        # Create and run room
        room = ChatRoom(
            ticker=ticker,
            stock_name=stock_name,
            context=context,
        )

        self._active_rooms[ticker] = room

        try:
            session = await room.start()

            # Store in history
            self._session_history.append(session)
            self._last_discussion[ticker] = datetime.now()

            return session

        finally:
            self._active_rooms.pop(ticker, None)

    def get_active_discussions(self) -> List[dict]:
        """Get list of active discussions."""
        return [
            {
                "ticker": ticker,
                "stock_name": room.stock_name,
                "session_id": room.session.id,
                "status": room.session.status.value,
                "started_at": room.session.started_at.isoformat() if room.session.started_at else None,
            }
            for ticker, room in self._active_rooms.items()
        ]

    def get_session_history(
        self,
        limit: int = 20,
        ticker: Optional[str] = None,
    ) -> List[ChatSession]:
        """Get session history."""
        sessions = self._session_history

        if ticker:
            sessions = [s for s in sessions if s.ticker == ticker]

        return sessions[-limit:]

    def get_session_by_id(self, session_id: str) -> Optional[ChatSession]:
        """Get a specific session by ID."""
        for session in self._session_history:
            if session.id == session_id:
                return session

        # Check active rooms
        for room in self._active_rooms.values():
            if room.session.id == session_id:
                return room.session

        return None


# -------------------------------------------
# Singleton Instance
# -------------------------------------------

_chat_coordinator: Optional[ChatCoordinator] = None


async def get_chat_coordinator() -> ChatCoordinator:
    """Get or create singleton chat coordinator."""
    global _chat_coordinator
    if _chat_coordinator is None:
        _chat_coordinator = ChatCoordinator()
    return _chat_coordinator


def get_chat_coordinator_sync() -> ChatCoordinator:
    """Get chat coordinator synchronously."""
    global _chat_coordinator
    if _chat_coordinator is None:
        _chat_coordinator = ChatCoordinator()
    return _chat_coordinator
