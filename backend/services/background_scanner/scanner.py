"""
Background Stock Scanner

Scans and analyzes all KOSPI/KOSDAQ stocks in background.
Features:
- Semaphore-controlled parallel analysis (3 concurrent slots)
- Progress tracking with ETA
- Result storage in SQLite
- Telegram notifications for progress
- Monthly reminder system
"""

import asyncio
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Callable, Awaitable
from pydantic import BaseModel, Field

import structlog

logger = structlog.get_logger()


# Full KOSPI/KOSDAQ stock list (major stocks)
# This can be expanded or loaded from external source
KOREAN_STOCKS_FULL = [
    # 시가총액 상위 (KOSPI)
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("035420", "NAVER"),
    ("005380", "현대차"),
    ("051910", "LG화학"),
    ("006400", "삼성SDI"),
    ("207940", "삼성바이오로직스"),
    ("005490", "POSCO홀딩스"),
    ("035720", "카카오"),
    ("068270", "셀트리온"),
    ("003670", "포스코퓨처엠"),
    ("028260", "삼성물산"),
    ("055550", "신한지주"),
    ("012330", "현대모비스"),
    ("105560", "KB금융"),
    ("096770", "SK이노베이션"),
    ("066570", "LG전자"),
    ("003550", "LG"),
    ("086790", "하나금융지주"),
    ("017670", "SK텔레콤"),
    ("034730", "SK"),
    ("015760", "한국전력"),
    ("032830", "삼성생명"),
    ("009150", "삼성전기"),
    ("033780", "KT&G"),
    ("090430", "아모레퍼시픽"),
    ("018260", "삼성에스디에스"),
    ("010130", "고려아연"),
    ("000810", "삼성화재"),
    ("030200", "KT"),
    ("003490", "대한항공"),
    ("011200", "HMM"),
    ("036570", "엔씨소프트"),
    ("259960", "크래프톤"),
    ("047050", "포스코인터내셔널"),
    ("034020", "두산에너빌리티"),
    ("323410", "카카오뱅크"),
    ("011070", "LG이노텍"),
    ("010950", "S-Oil"),
    ("010140", "삼성중공업"),
    ("326030", "SK바이오팜"),
    ("402340", "SK스퀘어"),
    ("000100", "유한양행"),
    ("097950", "CJ제일제당"),
    ("009540", "한국조선해양"),
    ("016360", "삼성증권"),
    ("000880", "한화"),
    ("161390", "한국타이어앤테크놀로지"),
    ("138040", "메리츠금융지주"),
    ("011790", "SKC"),
    # KOSDAQ 인기 종목
    ("247540", "에코프로비엠"),
    ("086520", "에코프로"),
    ("041510", "에스엠"),
    ("035900", "JYP Ent."),
    ("122870", "와이지엔터테인먼트"),
    ("293490", "카카오게임즈"),
    ("112040", "위메이드"),
    ("263750", "펄어비스"),
    ("357780", "솔브레인"),
    ("039030", "이오테크닉스"),
    ("196170", "알테오젠"),
    ("091990", "셀트리온헬스케어"),
    ("068760", "셀트리온제약"),
    ("214150", "클래시스"),
    ("145020", "휴젤"),
    ("328130", "루닛"),
    ("336370", "솔루스첨단소재"),
    ("058470", "리노공업"),
    ("067630", "HLB생명과학"),
    ("352820", "하이브"),
]


class ScanStatus(str, Enum):
    """Background scan status"""
    IDLE = "idle"                # Not running
    RUNNING = "running"          # Currently scanning
    PAUSED = "paused"            # Paused by user
    COMPLETED = "completed"      # Completed
    FAILED = "failed"            # Failed with error


class ScanProgress(BaseModel):
    """Scan progress information"""
    status: ScanStatus = ScanStatus.IDLE
    total_stocks: int = 0
    completed: int = 0
    in_progress: int = 0
    failed: int = 0

    # Current stocks being analyzed
    current_stocks: List[str] = Field(default_factory=list)

    # Results summary
    buy_count: int = 0
    sell_count: int = 0
    hold_count: int = 0
    watch_count: int = 0
    avoid_count: int = 0

    # Timing
    started_at: Optional[datetime] = None
    estimated_completion: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_scan_date: Optional[datetime] = None

    # Error info
    last_error: Optional[str] = None

    @property
    def progress_pct(self) -> float:
        if self.total_stocks == 0:
            return 0.0
        return (self.completed / self.total_stocks) * 100


class ScanResult(BaseModel):
    """Individual stock scan result"""
    stk_cd: str
    stk_nm: str
    action: str  # BUY, SELL, HOLD, WATCH, AVOID
    signal: str
    confidence: float
    summary: str
    key_factors: List[str] = Field(default_factory=list)
    current_price: int = 0
    scanned_at: datetime = Field(default_factory=datetime.now)


class BackgroundScanner:
    """
    Background stock scanner service.

    Features:
    - Scans all stocks with semaphore-controlled concurrency
    - Stores results in database
    - Sends Telegram notifications
    - Supports pause/resume
    """

    MAX_CONCURRENT_SCANS = 3  # Same as analysis limiter

    def __init__(self):
        self._progress = ScanProgress()
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_SCANS)
        self._running = False
        self._paused = False
        self._cancel_event = asyncio.Event()
        self._results: List[ScanResult] = []
        self._task: Optional[asyncio.Task] = None
        self._stock_list = KOREAN_STOCKS_FULL.copy()

    async def start_scan(
        self,
        stock_list: Optional[List[tuple]] = None,
        notify_progress: bool = True,
    ):
        """
        Start background scanning of all stocks.

        Args:
            stock_list: Optional custom list of (stk_cd, stk_nm) tuples
            notify_progress: Whether to send Telegram notifications
        """
        if self._running:
            logger.warning("scanner_already_running")
            return

        # Use provided list or default
        stocks = stock_list or self._stock_list

        self._progress = ScanProgress(
            status=ScanStatus.RUNNING,
            total_stocks=len(stocks),
            started_at=datetime.now(),
        )
        self._results = []
        self._running = True
        self._paused = False
        self._cancel_event.clear()

        logger.info(
            "background_scan_started",
            total_stocks=len(stocks),
        )

        # Send Telegram notification
        if notify_progress:
            await self._send_telegram_notification(
                f"🔍 *백그라운드 분석 시작*\n\n"
                f"총 {len(stocks)}개 종목 분석 시작\n"
                f"예상 소요 시간: {len(stocks) * 2}분"
            )

        # Start scan task
        self._task = asyncio.create_task(
            self._scan_all_stocks(stocks, notify_progress)
        )

    async def _scan_all_stocks(
        self,
        stocks: List[tuple],
        notify_progress: bool,
    ):
        """Scan all stocks with controlled concurrency."""
        tasks = []

        for stk_cd, stk_nm in stocks:
            if self._cancel_event.is_set():
                break

            # Wait while paused
            while self._paused:
                await asyncio.sleep(1)
                if self._cancel_event.is_set():
                    break

            task = asyncio.create_task(
                self._scan_stock(stk_cd, stk_nm)
            )
            tasks.append(task)

        # Wait for all tasks
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for result in results:
            if isinstance(result, Exception):
                logger.warning("scan_task_failed", error=str(result))
                self._progress.failed += 1
            elif result:
                self._results.append(result)
                self._update_action_count(result.action)

        # Mark complete
        self._progress.status = ScanStatus.COMPLETED
        self._progress.completed_at = datetime.now()
        self._progress.last_scan_date = datetime.now()
        self._running = False

        logger.info(
            "background_scan_completed",
            total=self._progress.total_stocks,
            completed=self._progress.completed,
            failed=self._progress.failed,
        )

        # Send completion notification
        if notify_progress:
            await self._send_scan_summary()

    async def _scan_stock(self, stk_cd: str, stk_nm: str) -> Optional[ScanResult]:
        """Scan a single stock with semaphore control."""
        async with self._semaphore:
            self._progress.in_progress += 1
            self._progress.current_stocks.append(stk_cd)

            try:
                # Import and run a lightweight analysis
                result = await self._run_quick_analysis(stk_cd, stk_nm)

                self._progress.completed += 1
                self._update_eta()

                return result

            except Exception as e:
                logger.error(
                    "stock_scan_failed",
                    stk_cd=stk_cd,
                    error=str(e),
                )
                self._progress.last_error = f"{stk_cd}: {str(e)}"
                return None

            finally:
                self._progress.in_progress -= 1
                if stk_cd in self._progress.current_stocks:
                    self._progress.current_stocks.remove(stk_cd)

    async def _run_quick_analysis(self, stk_cd: str, stk_nm: str) -> ScanResult:
        """
        Run a quick analysis on a stock.

        This is a lightweight version that focuses on key indicators.
        """
        from services.kiwoom.client import KiwoomClient
        from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
        from services.technical_indicators import TechnicalIndicators

        try:
            # Get Kiwoom client
            client = await get_shared_kiwoom_client_async()

            # Get stock info and chart data
            stock_info = await client.get_stock_info(stk_cd)
            chart_df = await client.get_daily_chart_df(stk_cd, limit=60)

            current_price = stock_info.cur_prc

            # Calculate technical indicators
            if len(chart_df) >= 20:
                tech = TechnicalIndicators(chart_df)
                indicators = tech.calculate_all()
                signals = indicators.get("signals", [])
            else:
                signals = []

            # Determine action based on indicators
            action, confidence = self._determine_action_from_signals(
                signals,
                stock_info,
            )

            # Build summary
            signal_descriptions = [s.get("description", "") for s in signals[:3]]
            summary = ", ".join(signal_descriptions) if signal_descriptions else "특이 시그널 없음"

            return ScanResult(
                stk_cd=stk_cd,
                stk_nm=stk_nm,
                action=action,
                signal=action.lower(),
                confidence=confidence,
                summary=f"{stk_nm}: {summary}",
                key_factors=signal_descriptions,
                current_price=current_price,
            )

        except Exception as e:
            logger.warning("quick_analysis_failed", stk_cd=stk_cd, error=str(e))
            # Return default result on error
            return ScanResult(
                stk_cd=stk_cd,
                stk_nm=stk_nm,
                action="HOLD",
                signal="hold",
                confidence=0.5,
                summary=f"분석 실패: {str(e)}",
                key_factors=[],
                current_price=0,
            )

    def _determine_action_from_signals(
        self,
        signals: List[dict],
        stock_info,
    ) -> tuple:
        """Determine action from technical signals."""
        buy_signals = 0
        sell_signals = 0

        for signal in signals:
            signal_type = signal.get("type", "")
            if signal_type in ("bullish", "oversold", "golden_cross"):
                buy_signals += 1
            elif signal_type in ("bearish", "overbought", "death_cross"):
                sell_signals += 1

        # Check price change
        price_change = stock_info.prdy_ctrt if hasattr(stock_info, "prdy_ctrt") else 0

        # Determine action
        if buy_signals >= 3:
            return "BUY", 0.8
        elif sell_signals >= 3:
            return "AVOID", 0.8
        elif buy_signals >= 2:
            return "WATCH", 0.7
        elif sell_signals >= 2:
            return "AVOID", 0.7
        elif buy_signals > sell_signals:
            return "WATCH", 0.6
        elif sell_signals > buy_signals:
            return "AVOID", 0.6
        else:
            return "HOLD", 0.5

    def _update_action_count(self, action: str):
        """Update action count in progress."""
        action_map = {
            "BUY": "buy_count",
            "SELL": "sell_count",
            "HOLD": "hold_count",
            "WATCH": "watch_count",
            "AVOID": "avoid_count",
            "ADD": "buy_count",
            "REDUCE": "sell_count",
        }
        attr = action_map.get(action, "hold_count")
        setattr(self._progress, attr, getattr(self._progress, attr) + 1)

    def _update_eta(self):
        """Update estimated completion time."""
        if self._progress.completed > 0:
            elapsed = (datetime.now() - self._progress.started_at).total_seconds()
            rate = self._progress.completed / elapsed
            remaining = self._progress.total_stocks - self._progress.completed
            eta_seconds = remaining / rate if rate > 0 else 0
            self._progress.estimated_completion = datetime.now() + timedelta(seconds=eta_seconds)

    async def pause_scan(self):
        """Pause the background scan."""
        if self._running and not self._paused:
            self._paused = True
            self._progress.status = ScanStatus.PAUSED
            logger.info("background_scan_paused")

            await self._send_telegram_notification(
                f"⏸ *백그라운드 분석 일시 중지*\n\n"
                f"진행률: {self._progress.completed}/{self._progress.total_stocks}"
            )

    async def resume_scan(self):
        """Resume the background scan."""
        if self._running and self._paused:
            self._paused = False
            self._progress.status = ScanStatus.RUNNING
            logger.info("background_scan_resumed")

            await self._send_telegram_notification(
                f"▶️ *백그라운드 분석 재개*\n\n"
                f"남은 종목: {self._progress.total_stocks - self._progress.completed}개"
            )

    async def stop_scan(self):
        """Stop the background scan."""
        if self._running:
            self._cancel_event.set()
            self._progress.status = ScanStatus.IDLE
            self._running = False
            self._paused = False

            if self._task:
                self._task.cancel()

            logger.info("background_scan_stopped")

            await self._send_telegram_notification(
                f"⏹ *백그라운드 분석 중지*\n\n"
                f"분석 완료: {self._progress.completed}/{self._progress.total_stocks}"
            )

    def get_progress(self) -> ScanProgress:
        """Get current scan progress."""
        return self._progress

    def get_results(self, action_filter: Optional[str] = None) -> List[ScanResult]:
        """
        Get scan results with optional action filter.

        Args:
            action_filter: Filter by action (BUY, SELL, HOLD, WATCH, AVOID)
        """
        if action_filter:
            return [r for r in self._results if r.action == action_filter.upper()]
        return self._results

    async def _send_telegram_notification(self, message: str):
        """Send Telegram notification."""
        try:
            from services.telegram import get_telegram_notifier
            telegram = await get_telegram_notifier()
            if telegram.is_ready:
                await telegram.send_message(message)
        except Exception as e:
            logger.warning("telegram_notification_failed", error=str(e))

    async def _send_scan_summary(self):
        """Send scan completion summary via Telegram."""
        duration = (self._progress.completed_at - self._progress.started_at).total_seconds() / 60

        message = f"""
✅ *백그라운드 분석 완료*

📊 *분석 결과*
• 총 분석: {self._progress.total_stocks}개
• 완료: {self._progress.completed}개
• 실패: {self._progress.failed}개

📈 *추천 분포*
• 매수(BUY): {self._progress.buy_count}개
• 매도(SELL): {self._progress.sell_count}개
• 보유(HOLD): {self._progress.hold_count}개
• 관망(WATCH): {self._progress.watch_count}개
• 회피(AVOID): {self._progress.avoid_count}개

⏱ 소요 시간: {duration:.1f}분

_다음 분석 권장: 1개월 후_
"""
        await self._send_telegram_notification(message.strip())

    async def check_monthly_reminder(self):
        """Check if monthly reminder is needed."""
        if self._progress.last_scan_date:
            days_since_scan = (datetime.now() - self._progress.last_scan_date).days
            if days_since_scan >= 30:
                await self._send_telegram_notification(
                    f"⏰ *분석 리마인더*\n\n"
                    f"마지막 전체 분석이 {days_since_scan}일 전입니다.\n"
                    f"전체 종목 분석을 권장합니다.\n\n"
                    f"_/scan 명령으로 분석 시작_"
                )
                return True
        return False


# Singleton instance
_scanner_instance: Optional[BackgroundScanner] = None


async def get_background_scanner() -> BackgroundScanner:
    """Get or create the background scanner singleton."""
    global _scanner_instance

    if _scanner_instance is None:
        _scanner_instance = BackgroundScanner()

    return _scanner_instance
