/**
 * useStartAnalysis
 *
 * Shared "start an analysis for a ticker" flow. Originally lived inline in
 * BasketWidget.handleAnalyze; extracted so the ⌘K command palette can start
 * the exact same flow (API call + session bookkeeping + Kiwoom multi-session
 * WebSocket wiring) without duplicating it.
 *
 * P4 T3 (re-analysis dedup + held-position awareness): the backend's
 * /analysis/start now returns two additive flags (T1 52eadd0 + T2 f0c18bf):
 *   - `duplicate`: true when an active (running/awaiting_approval) session
 *     for the ticker already existed — the response IS that pre-existing
 *     session, no new graph run was started. `start()` must NOT add a
 *     second store session in this case; it focuses the existing one
 *     instead (injecting minimal bookkeeping first if the local store never
 *     saw it — e.g. started from another tab).
 *   - `position_exists`: true when the ticker is already held, meaning the
 *     analysis is position-aware (ADD/REDUCE/HOLD), not a fresh BUY entry.
 *     `start()` surfaces this via the app-wide `infoNotice` toast so the
 *     user isn't left assuming a plain new-entry analysis just started.
 *
 * NOTE on error handling: `start()` does NOT catch/swallow errors — it lets
 * them propagate so callers can attach their own UX (e.g. BasketWidget shows
 * a per-item error message via `setBasketItemError`). Callers that just want
 * a safe `sessionId | null` should wrap the call in their own try/catch.
 */

import { useStore, type MarketType, type SessionData } from '@/store';
import { startKRStockAnalysis } from '@/api/client';
import { wsManager } from '@/api/websocket';
import { createKiwoomWebSocketHandlers } from '@/api/kiwoomSessionHandlers';

/**
 * Result of `start()`. `sessionId` always identifies the session now showing
 * — either freshly created, or (P4 dedup) the pre-existing in-progress
 * session for the same ticker that `start()` focused instead of duplicating.
 * Callers that only need to navigate/reference the session can keep treating
 * this like a plain id (`result.sessionId`); `duplicate`/`positionExists` let
 * a caller react to the P4 outcome without re-deriving it from the raw API
 * response.
 */
export interface StartAnalysisResult {
  sessionId: string;
  /** True when this reused an already-running/awaiting-approval session for
   * the ticker instead of starting a new graph run (P4 T1 dedup). */
  duplicate: boolean;
  /** True when the ticker is already held — the analysis is position-aware
   * (ADD/REDUCE/HOLD), not a fresh BUY entry (P4 T2). */
  positionExists: boolean;
}

function heldPositionNotice(label: string): string {
  return `${label} — 이미 보유 중 · 포지션 관리 분석 (ADD/REDUCE/HOLD)`;
}

export function useStartAnalysis() {
  const setActiveMarket = useStore((state) => state.setActiveMarket);

  // Multi-session actions for Kiwoom. The per-session WS handler factory lives
  // in api/kiwoomSessionHandlers (shared with SessionBridge) so every path that
  // opens a Kiwoom session streams identically.
  const addKiwoomSession = useStore((state) => state.addKiwoomSession);
  const setActiveKiwoomSession = useStore((state) => state.setActiveKiwoomSession);

  // P4 T3: brief, app-wide informational toast — see store's `infoNotice`
  // doc comment for why this is deliberately NOT the `error`/setError slot.
  const setInfoNotice = useStore((state) => state.setInfoNotice);

  /**
   * Start an analysis for a ticker on the given market. Switches the active
   * market, calls the matching start-analysis API, wires up session state
   * (and, for Kiwoom, the multi-session WebSocket), and returns the
   * resulting session's id plus the P4 dedup/held-position outcome. Throws
   * on failure — callers own their own error handling.
   */
  const start = async (
    marketType: MarketType,
    ticker: string,
    displayName?: string
  ): Promise<StartAnalysisResult> => {
    console.log(`[useStartAnalysis] start(${marketType}, ${ticker})`);

    // Switch to the correct market
    setActiveMarket(marketType);

    const response = await startKRStockAnalysis({ stk_cd: ticker });
    const sessionId = response.session_id;
    const label = displayName || response.stk_nm || ticker;
    const positionExists = response.position_exists ?? false;

    if (response.duplicate) {
      // P4 T1 dedup hit: the backend returned an ALREADY in-progress
      // session for this stk_cd instead of starting a new graph run.
      // addKiwoomSession is a no-op (returns false) when the session id
      // already exists locally, so it's only worth calling — and only
      // worth opening a WS connection for — when the local store never
      // saw this session at all (e.g. it was started from another tab).
      // Either way, focus it: the user must land on the real running
      // analysis, not a duplicate or a stale previously-active session.
      const alreadyCached = useStore
        .getState()
        .kiwoom.sessions.some((s) => s.sessionId === sessionId);
      if (!alreadyCached) {
        const isAwaiting = response.status === 'awaiting_approval';
        const sessionData: SessionData = {
          sessionId,
          ticker,
          displayName: label,
          marketType: 'kiwoom',
          status: isAwaiting ? 'awaiting_approval' : 'running',
          currentStage: null,
          reasoningLog: [],
          analyses: [],
          tradeProposal: null,
          awaitingApproval: isAwaiting,
          autoApproveAt: null,
          activePosition: null,
          error: null,
          createdAt: new Date(),
          updatedAt: new Date(),
        };
        addKiwoomSession(sessionData);
        if (!wsManager.has(sessionId)) {
          wsManager.connect(sessionId, createKiwoomWebSocketHandlers(sessionId));
        }
      }
      setActiveKiwoomSession(sessionId);
      if (positionExists) setInfoNotice(heldPositionNotice(label));
      return { sessionId, duplicate: true, positionExists };
    }

    // Fresh session — unchanged behavior.
    const sessionData: SessionData = {
      sessionId,
      ticker,
      displayName: label,
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

    if (positionExists) setInfoNotice(heldPositionNotice(label));

    return { sessionId, duplicate: false, positionExists };
  };

  return start;
}
