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
import { getOperations } from '@/api/client';
import type { KRStockTradeProposal, SessionData, SessionStatus } from '@/types';

// -------------------------------------------
// Reasoning delta batching
// -------------------------------------------
//
// Root cause of the streaming perf hit: every reasoning WS delta previously
// called addKiwoomSessionReasoning directly (one store-wide set() per token),
// firing at LLM streaming frequency and re-rendering every store subscriber.
// Buffer deltas per session and flush them as ONE batched store update instead.
//
// Module-scoped (not per-handlers-instance) because it must survive across
// createKiwoomWebSocketHandlers() calls for the same sessionId — flushing is
// keyed purely by sessionId, so a stray call after a session no longer exists
// in the store is harmless (the batch action's session-map .map is a no-op).
const REASONING_FLUSH_MS = 300;
const reasoningBuffers = new Map<string, string[]>();
const reasoningTimers = new Map<string, ReturnType<typeof setTimeout>>();

/**
 * Flush a session's buffered reasoning entries into the store in one batched
 * update, and clear its pending timer (if any). Safe to call with an empty/
 * absent buffer (no-op) — callers invoke this defensively before any other
 * handling for the session so a proposal/status/complete frame can never
 * overtake reasoning lines still sitting in the buffer.
 */
function flushReasoningBuffer(sessionId: string): void {
  const timer = reasoningTimers.get(sessionId);
  if (timer !== undefined) {
    clearTimeout(timer);
    reasoningTimers.delete(sessionId);
  }
  const buffer = reasoningBuffers.get(sessionId);
  if (buffer && buffer.length > 0) {
    reasoningBuffers.delete(sessionId);
    useStore.getState().addKiwoomSessionReasoningBatch(sessionId, buffer);
  } else {
    reasoningBuffers.delete(sessionId);
  }
}

export function createKiwoomWebSocketHandlers(sessionId: string): WebSocketHandlers {
  const store = () => useStore.getState();
  // Tracks whether this session's socket has passed through 'reconnecting'
  // since the last 'connected' state — i.e. distinguishes a genuine drop+
  // recover cycle from the initial connect (which goes straight from
  // 'connecting' to 'connected' and must NOT re-trigger a rehydrate).
  let droppedConnection = false;
  return {
    onReasoning: (entry) => {
      let buffer = reasoningBuffers.get(sessionId);
      if (!buffer) {
        buffer = [];
        reasoningBuffers.set(sessionId, buffer);
      }
      buffer.push(entry);
      // First entry in a window arms the flush timer; later entries in the
      // same window just append (no immediate store call).
      if (!reasoningTimers.has(sessionId)) {
        reasoningTimers.set(
          sessionId,
          setTimeout(() => flushReasoningBuffer(sessionId), REASONING_FLUSH_MS),
        );
      }
    },
    onStatus: (data) => {
      // Ordering: buffered reasoning lines must land before this status update
      // (a mid-window status frame must not overtake reasoning still buffered).
      flushReasoningBuffer(sessionId);
      store().updateKiwoomSessionStatus(sessionId, data.status as SessionStatus);
      store().updateKiwoomSessionStage(sessionId, data.stage);
      store().setKiwoomSessionAwaitingApproval(sessionId, data.awaiting_approval);
      // R3: autonomous approval countdown deadline (absent = no pending auto-approve)
      store().setKiwoomSessionAutoApproveAt(sessionId, data.auto_approve_at ?? null);
    },
    onProposal: (data) => {
      flushReasoningBuffer(sessionId);
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
      flushReasoningBuffer(sessionId);
      if (data.error) {
        store().setKiwoomSessionError(sessionId, data.error);
      }
      store().updateKiwoomSessionStatus(sessionId, data.status as SessionStatus);
    },
    onError: () => {
      flushReasoningBuffer(sessionId);
      store().setKiwoomSessionError(sessionId, 'WebSocket connection error');
    },
    onDisconnect: () => {
      // The WS core's onClose fires this on every close (clean disconnect AND
      // a dropped connection ahead of a reconnect attempt) — flushing here is
      // harmless in the reconnect case (buffer is just already empty) and is
      // the only lifecycle hook TradingWebSocket exposes for "socket closed".
      flushReasoningBuffer(sessionId);
    },
    onConnectionStateChange: (state) => {
      // A dropped socket (backend restart, network blip, etc.) means the FE
      // was out of sync with the server for a stretch — the session may have
      // finished, been cancelled, or vanished entirely while we couldn't hear
      // about it. Re-running the same server-truth reconciliation used on
      // page load (rehydrateKiwoomSessions) on RECOVERY from a drop catches
      // that without requiring a manual page refresh. Gated on having seen
      // 'reconnecting' first so the initial connect (which never passes
      // through that state) doesn't fire a redundant rehydrate.
      if (state === 'reconnecting') {
        droppedConnection = true;
      } else if (state === 'connected' && droppedConnection) {
        droppedConnection = false;
        void rehydrateKiwoomSessions();
      }
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

/**
 * Rehydrate running/awaiting Kiwoom sessions from the server (session_manager
 * SQLite) into the store after a page refresh, and reconnect their WebSocket
 * streams. Also PURGES the reverse case: store sessions the server no longer
 * lists at all.
 *
 * Why the purge matters: the store can hold a session the server has since
 * forgotten (backend restart, in-memory session lost, etc.) — that renders as
 * a zombie proposal/analysis card that 404s the moment the user clicks it.
 * Only non-terminal sessions (running/awaiting_approval) are purged; terminal
 * ones (completed/cancelled/error) are legitimate local history and are never
 * touched here, server-known or not.
 *
 * Ordering matters: running sessions are added FIRST, awaiting sessions LAST.
 * addKiwoomSession sets activeSessionId to whatever it just added and mirrors
 * that session's fields into the legacy single-session store fields, which
 * OrderTicketRail (the HITL approval rail) reads exclusively. Adding awaiting
 * sessions last — and calling the proposal/awaiting/autoApprove setters after
 * that — makes the restored proposal show up in the rail. The purge sweep
 * runs against a snapshot of the store taken BEFORE any of these additions,
 * so it can never race with (or delete) a session this same call just added.
 *
 * Silent on failure: a broken /trading/operations call must not crash the app
 * on load, it just means sessions aren't rehydrated (the operations board
 * surfaces its own error state).
 */
export async function rehydrateKiwoomSessions(): Promise<void> {
  let ops;
  try {
    ops = await getOperations('kiwoom');
  } catch {
    return;
  }
  const store = useStore.getState();
  const priorSessions = store.kiwoom.sessions;
  const known = new Set(priorSessions.map((s) => s.sessionId));
  const serverKnown = new Set<string>([
    ...(ops.analyzing ?? []).map((a) => a.session_id),
    ...(ops.awaiting ?? []).map((w) => w.session_id),
  ]);
  const now = new Date();

  const build = (
    sid: string, ticker: string, name: string | null,
    status: SessionStatus, stage: string | null, awaiting: boolean,
  ): SessionData => ({
    sessionId: sid, ticker, displayName: name || ticker,
    marketType: 'kiwoom', status, currentStage: stage,
    reasoningLog: [], analyses: [], tradeProposal: null,
    awaitingApproval: awaiting, autoApproveAt: null, activePosition: null,
    error: null, createdAt: now, updatedAt: now,
  });

  for (const a of ops.analyzing ?? []) {
    if (known.has(a.session_id)) continue;
    if (!store.addKiwoomSession(build(a.session_id, a.ticker, a.name,
        'running', a.current_stage, false))) break; // max concurrent reached
    ensureKiwoomSessionStreaming(a.session_id);
  }

  for (const w of ops.awaiting ?? []) {
    if (known.has(w.session_id)) continue;
    if (!store.addKiwoomSession(build(w.session_id, w.ticker, w.name,
        'awaiting_approval', null, true))) break;
    if (w.proposal) {
      const p = w.proposal as Record<string, unknown>;
      const proposal: KRStockTradeProposal = {
        id: String(p.id ?? w.session_id),
        stk_cd: w.ticker,
        stk_nm: w.name,
        action: String(p.action ?? 'HOLD') as KRStockTradeProposal['action'],
        quantity: Number(p.quantity ?? 0),
        // number|null fields: preserve null (unknown) instead of coercing to 0
        entry_price: p.entry_price != null ? Number(p.entry_price) : null,
        stop_loss: p.stop_loss != null ? Number(p.stop_loss) : null,
        take_profit: p.take_profit != null ? Number(p.take_profit) : null,
        risk_score: Number(p.risk_score ?? 0),
        position_size_pct: Number(p.position_size_pct ?? 0),
        rationale: String(p.rationale ?? ''),
        bull_case: String(p.bull_case ?? ''),
        bear_case: String(p.bear_case ?? ''),
        created_at: String(p.created_at ?? now.toISOString()),
      };
      store.setKiwoomSessionProposal(w.session_id, proposal);
    }
    store.setKiwoomSessionAwaitingApproval(w.session_id, true);
    store.setKiwoomSessionAutoApproveAt(w.session_id, w.auto_approve_at ?? null);
    ensureKiwoomSessionStreaming(w.session_id); // rejection→re-analysis needs the stream
  }

  // Purge: drop non-terminal store sessions the server no longer lists at
  // all. Swept from the pre-add snapshot (priorSessions), so a session this
  // same call just added (always serverKnown by construction) can never be
  // caught here. Terminal sessions are never purged — they're kept as history
  // regardless of whether the server still lists them.
  for (const session of priorSessions) {
    const isNonTerminal = session.status === 'running' || session.status === 'awaiting_approval';
    if (isNonTerminal && !serverKnown.has(session.sessionId)) {
      store.removeKiwoomSession(session.sessionId);
    }
  }
}
