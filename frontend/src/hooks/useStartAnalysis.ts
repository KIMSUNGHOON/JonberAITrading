/**
 * useStartAnalysis
 *
 * Shared "start an analysis for a ticker" flow. Originally lived inline in
 * BasketWidget.handleAnalyze; extracted so the ⌘K command palette can start
 * the exact same flow (API call + session bookkeeping + Kiwoom multi-session
 * WebSocket wiring) without duplicating it.
 *
 * NOTE on error handling: `start()` does NOT catch/swallow errors — it lets
 * them propagate so callers can attach their own UX (e.g. BasketWidget shows
 * a per-item error message via `setBasketItemError`). Callers that just want
 * a safe `sessionId | null` should wrap the call in their own try/catch.
 */

import { useStore, type MarketType, type SessionData } from '@/store';
import { startKRStockAnalysis, startCoinAnalysis } from '@/api/client';
import { wsManager } from '@/api/websocket';
import { createKiwoomWebSocketHandlers } from '@/api/kiwoomSessionHandlers';

export function useStartAnalysis() {
  const setActiveMarket = useStore((state) => state.setActiveMarket);

  // Legacy session actions (single-session mode for coin)
  const startCoinSession = useStore((state) => state.startCoinSession);

  // Multi-session actions for Kiwoom. The per-session WS handler factory lives
  // in api/kiwoomSessionHandlers (shared with SessionBridge) so every path that
  // opens a Kiwoom session streams identically.
  const addKiwoomSession = useStore((state) => state.addKiwoomSession);
  const setActiveKiwoomSession = useStore((state) => state.setActiveKiwoomSession);

  /**
   * Start an analysis for a ticker on the given market. Switches the active
   * market, calls the matching start-analysis API, wires up session state
   * (and, for Kiwoom, the multi-session WebSocket), and returns the new
   * sessionId. Throws on failure — callers own their own error handling.
   */
  const start = async (
    marketType: MarketType,
    ticker: string,
    displayName?: string
  ): Promise<string | null> => {
    console.log(`[useStartAnalysis] start(${marketType}, ${ticker})`);

    // Switch to the correct market
    setActiveMarket(marketType);

    if (marketType === 'kiwoom') {
      const response = await startKRStockAnalysis({ stk_cd: ticker });
      const sessionId = response.session_id;

      // Create session data for multi-session store
      const sessionData: SessionData = {
        sessionId,
        ticker,
        displayName: displayName || response.stk_nm || ticker,
        marketType: 'kiwoom',
        status: 'running',
        currentStage: null,
        reasoningLog: [],
        analyses: [],
        tradeProposal: null,
        awaitingApproval: false,
        autoApproveAt: null,
        activePosition: null,
        error: null,
        createdAt: new Date(),
        updatedAt: new Date(),
      };

      // Add to multi-session store - check if it was successful
      const sessionAdded = addKiwoomSession(sessionData);
      if (!sessionAdded) {
        throw new Error('세션 추가 실패: 동시 분석 한도에 도달했습니다.');
      }

      // Connect WebSocket with handlers
      const handlers = createKiwoomWebSocketHandlers(sessionId);
      wsManager.connect(sessionId, handlers);

      // Set as active session
      setActiveKiwoomSession(sessionId);

      return sessionId;
    } else {
      // For coin, use legacy single-session mode for now
      const response = await startCoinAnalysis({ market: ticker });
      const sessionId = response.session_id;
      startCoinSession(sessionId, ticker, displayName);
      return sessionId;
    }
  };

  return start;
}
