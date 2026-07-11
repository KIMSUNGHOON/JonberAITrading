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
import { wsManager, type WebSocketHandlers } from '@/api/websocket';
import type { KRStockTradeProposal, SessionStatus } from '@/types';

export function useStartAnalysis() {
  const setActiveMarket = useStore((state) => state.setActiveMarket);

  // Legacy session actions (single-session mode for coin)
  const startCoinSession = useStore((state) => state.startCoinSession);

  // Multi-session actions for Kiwoom
  const addKiwoomSession = useStore((state) => state.addKiwoomSession);
  const updateKiwoomSessionStatus = useStore((state) => state.updateKiwoomSessionStatus);
  const updateKiwoomSessionStage = useStore((state) => state.updateKiwoomSessionStage);
  const addKiwoomSessionReasoning = useStore((state) => state.addKiwoomSessionReasoning);
  const setKiwoomSessionProposal = useStore((state) => state.setKiwoomSessionProposal);
  const setKiwoomSessionAwaitingApproval = useStore(
    (state) => state.setKiwoomSessionAwaitingApproval
  );
  const setKiwoomSessionError = useStore((state) => state.setKiwoomSessionError);
  const setActiveKiwoomSession = useStore((state) => state.setActiveKiwoomSession);

  // Create WebSocket handlers for a Kiwoom session. Self-contained: only
  // touches multi-session store actions keyed by sessionId (no component
  // -local state — the original BasketWidget version also referenced its
  // local `analyzingItems` set here, but keyed by sessionId, which never
  // matches an `analyzingItems` entry since those are keyed by basket item
  // id; that reference was inert and is intentionally dropped here).
  const createKiwoomWebSocketHandlers = (sessionId: string): WebSocketHandlers => ({
    onReasoning: (entry) => {
      addKiwoomSessionReasoning(sessionId, entry);
    },
    onStatus: (data) => {
      updateKiwoomSessionStatus(sessionId, data.status as SessionStatus);
      updateKiwoomSessionStage(sessionId, data.stage);
      setKiwoomSessionAwaitingApproval(sessionId, data.awaiting_approval);
    },
    onProposal: (data) => {
      const proposal: KRStockTradeProposal = {
        id: data.id,
        stk_cd: data.ticker,
        stk_nm: null,
        action: data.action.toUpperCase() as 'BUY' | 'SELL' | 'HOLD',
        quantity: data.quantity,
        entry_price: data.entry_price,
        stop_loss: data.stop_loss,
        take_profit: data.take_profit,
        risk_score: data.risk_score,
        position_size_pct: 0,
        rationale: data.rationale,
        bull_case: '',
        bear_case: '',
        created_at: new Date().toISOString(),
      };
      setKiwoomSessionProposal(sessionId, proposal);
    },
    onComplete: (data) => {
      if (data.error) {
        setKiwoomSessionError(sessionId, data.error);
      }
      updateKiwoomSessionStatus(sessionId, data.status as SessionStatus);
    },
    onError: () => {
      setKiwoomSessionError(sessionId, 'WebSocket connection error');
    },
  });

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
