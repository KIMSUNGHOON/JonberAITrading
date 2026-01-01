"""
Data Collection Node for Korean Stock Trading

Fetches market data and portfolio context from Kiwoom API.
"""

import time

import structlog
from langchain_core.messages import AIMessage

from agents.graph.kr_stock_state import (
    KRStockAnalysisStage,
    add_kr_stock_reasoning_log,
)
from agents.tools.kr_market_data import (
    get_kr_daily_chart,
    get_kr_orderbook,
    get_kr_stock_info,
)
from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
from .helpers import _get_stk_cd_safely

logger = structlog.get_logger()


async def kr_stock_data_collection_node(state: dict) -> dict:
    """
    Fetch market data and portfolio context from Kiwoom API.
    This is the first node that gathers all necessary data including existing positions.
    """
    start_time = time.perf_counter()
    stk_cd = _get_stk_cd_safely(state, "data_collection")

    logger.info(
        "node_started",
        node="kr_stock_data_collection",
        stk_cd=stk_cd,
    )

    try:
        # Fetch stock info
        stock_info = await get_kr_stock_info(stk_cd)

        # Fetch daily chart
        chart_df = await get_kr_daily_chart(stk_cd)

        # Fetch orderbook
        orderbook = await get_kr_orderbook(stk_cd)

        # Fetch portfolio to check for existing position
        existing_position = None
        portfolio_summary = None
        try:
            client = await get_shared_kiwoom_client_async()
            account_balance = await client.get_account_balance()

            # Find existing position for this stock
            for holding in account_balance.holdings:
                if holding.stk_cd == stk_cd:
                    existing_position = {
                        "stk_cd": holding.stk_cd,
                        "stk_nm": holding.stk_nm,
                        "quantity": holding.hldg_qty,
                        "avg_buy_price": holding.avg_buy_prc,
                        "current_price": holding.cur_prc,
                        "eval_amount": holding.evlu_amt,
                        "profit_loss": holding.evlu_pfls_amt,
                        "profit_loss_pct": holding.evlu_pfls_rt,
                    }
                    logger.info(
                        "existing_position_found",
                        stk_cd=stk_cd,
                        quantity=holding.hldg_qty,
                        avg_price=holding.avg_buy_prc,
                        pnl_pct=holding.evlu_pfls_rt,
                    )
                    break

            # Portfolio summary for context
            portfolio_summary = {
                "total_purchase": account_balance.pchs_amt,
                "total_eval": account_balance.evlu_amt,
                "total_pnl": account_balance.evlu_pfls_amt,
                "total_pnl_pct": account_balance.evlu_pfls_rt,
                "available_cash": account_balance.d2_ord_psbl_amt,
                "holdings_count": len(account_balance.holdings),
            }

        except Exception as e:
            logger.warning(
                "portfolio_fetch_failed",
                stk_cd=stk_cd,
                error=str(e),
            )
            # Continue without portfolio data

        # Convert chart DataFrame to list of dicts for serialization
        chart_data = []
        if not chart_df.empty:
            for idx, row in chart_df.iterrows():
                chart_data.append({
                    "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
                    "open": int(row["open"]),
                    "high": int(row["high"]),
                    "low": int(row["low"]),
                    "close": int(row["close"]),
                    "volume": int(row["volume"]),
                })

        stk_nm = stock_info.get("stk_nm", "")
        cur_prc = stock_info.get("cur_prc", 0)
        prdy_ctrt = stock_info.get("prdy_ctrt", 0)

        # Build reasoning with position context
        position_info = ""
        if existing_position:
            position_info = (
                f"\n[포지션] {existing_position['quantity']}주 보유 중, "
                f"평균단가={existing_position['avg_buy_price']:,}원, "
                f"수익률={existing_position['profit_loss_pct']:+.2f}%"
            )

        reasoning = (
            f"[데이터 수집] {stk_nm} ({stk_cd}): "
            f"현재가={cur_prc:,}원, "
            f"전일대비={prdy_ctrt:+.2f}%, "
            f"차트 {len(chart_data)}일치"
            f"{position_info}"
        )

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "node_completed",
            node="kr_stock_data_collection",
            stk_cd=stk_cd,
            stk_nm=stk_nm,
            has_position=existing_position is not None,
            duration_ms=round(duration_ms, 2),
        )

        return {
            "stk_nm": stk_nm,
            "market_data": stock_info,
            "chart_df": chart_data,
            "orderbook": orderbook,
            "existing_position": existing_position,
            "portfolio_summary": portfolio_summary,
            "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
            "messages": [AIMessage(content=reasoning)],
            "current_stage": KRStockAnalysisStage.DATA_COLLECTION,
        }

    except Exception as e:
        error_msg = f"데이터 수집 실패 ({stk_cd}): {str(e)}"
        logger.error("kr_stock_data_collection_failed", stk_cd=stk_cd, error=str(e))
        return {
            "error": error_msg,
            "reasoning_log": add_kr_stock_reasoning_log(state, f"[오류] {error_msg}"),
            "current_stage": KRStockAnalysisStage.COMPLETE,
        }
