/**
 * Shared Kiwoom multi-session WebSocket wiring.
 *
 * Both the start path (useStartAnalysis) and the route bridge (SessionBridge)
 * need to stream a Kiwoom analysis session. Previously the handler factory lived
 * only inside useStartAnalysis, so start paths that did NOT go through that hook
 * (watchlist reanalyze, scanner "analyze", re-viewing a running session) added a
 * session and navigated to /workflow but never opened the /ws/session stream —
 * the page then only ever showed the initial empty session while the analysis
 * ran server-side (Telegram fired, UI stayed blank). Centralizing the factory
 * here and having SessionBridge ensure the connection fixes every such path.
 *
 * Handlers dispatch purely through useStore.getState() (store actions are stable
 * references), so they are usable outside a React render.
 */
import { useStore } from '@/store';
import { wsManager, type WebSocketHandlers } from '@/api/websocket';
import type { KRStockTradeProposal, SessionStatus } from '@/types';

export function createKiwoomWebSocketHandlers(sessionId: string): WebSocketHandlers {
  const store = () => useStore.getState();
  return {
    onReasoning: (entry) => {
      store().addKiwoomSessionReasoning(sessionId, entry);
    },
    onStatus: (data) => {
      store().updateKiwoomSessionStatus(sessionId, data.status as SessionStatus);
      store().updateKiwoomSessionStage(sessionId, data.stage);
      store().setKiwoomSessionAwaitingApproval(sessionId, data.awaiting_approval);
      // R3: autonomous approval countdown deadline (absent = no pending auto-approve)
      store().setKiwoomSessionAutoApproveAt(sessionId, data.auto_approve_at ?? null);
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
      store().setKiwoomSessionProposal(sessionId, proposal);
    },
    onComplete: (data) => {
      if (data.error) {
        store().setKiwoomSessionError(sessionId, data.error);
      }
      store().updateKiwoomSessionStatus(sessionId, data.status as SessionStatus);
    },
    onError: () => {
      store().setKiwoomSessionError(sessionId, 'WebSocket connection error');
    },
  };
}

/**
 * Ensure the per-session WebSocket stream is connected for a Kiwoom session.
 *
 * Safe to call on any navigation to a session's detail/workflow route: it only
 * connects when the session exists in the store and is NOT already streaming
 * (wsManager.connect would otherwise tear down and replace a live connection).
 */
export function ensureKiwoomSessionStreaming(sessionId: string): void {
  const session = useStore
    .getState()
    .kiwoom.sessions.find((s) => s.sessionId === sessionId);
  if (session && !wsManager.has(sessionId)) {
    wsManager.connect(sessionId, createKiwoomWebSocketHandlers(sessionId));
  }
}
