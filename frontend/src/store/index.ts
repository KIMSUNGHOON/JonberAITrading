/**
 * Zustand Store for Agentic Trading
 *
 * Manages global application state with COMPLETE ISOLATION between:
 * - Kiwoom analysis (Korean stocks via Kiwoom)
 * - Coin analysis (cryptocurrency via Upbit)
 *
 * Each market type has its own:
 * - Session state
 * - Analysis results
 * - Trade proposals
 * - Positions
 * - History
 */

import { create } from 'zustand';
import { devtools, persist, createJSONStorage } from 'zustand/middleware';
import type {
  AnalysisSummary,
  ChatMessage,
  Position,
  SessionStatus,
  ChartConfig,
  TimeFrame,
  CoinTradeProposal,
  KRStockTradeProposal,
  SessionData,
  DetailedAnalysisResults,
  TradingMode,
  TradingModeResponse,
} from '@/types';
import type { TradeNotificationType, TradeNotification } from '@/hooks/useTradeNotifications';
// P0-3: a removed card must take its socket with it (see removeKiwoomSession
// below). No cycle — websocket.ts does not import '@/store'.
import { wsManager } from '@/api/websocket';

// P1-3: how many trade notifications survive a page refresh (bounded, most
// recent first). The live WS stream (useTradeNotifications) can carry far
// more, but only this many are persisted to localStorage.
const MAX_PERSISTED_NOTIFICATIONS = 30;

// UUID 생성 함수 (crypto.randomUUID 폴백)
function generateUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  // Fallback for older browsers or non-secure contexts
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// -------------------------------------------
// Awaiting-row → TradeProposal reconstruction (approval-reachability fix,
// T7 review HIGH #1/#2)
// -------------------------------------------
// The /operations poll (OperationsPanel's AwaitingColumn — see
// backend/app/api/routes/trading.py _slim_proposal/_PROPOSAL_SLIM_KEYS)
// sends a slimmed proposal Record per session that carries every field the
// OrderTicketRail actually renders (action/qty/entry/stop/take/risk/
// rationale/bull/bear/id/created_at) but omits the proposal's OWN symbol
// fields for BOTH markets (kiwoom stk_cd/stk_nm, coin market/korean_name —
// neither pair is in the backend's slim allowlist). The row's OWN top-level
// ticker/name (populated from the SESSION, not the proposal) fill that gap,
// so a clicked row can always be turned into a rail-renderable proposal
// without a round-trip — even for a session never cached locally.
function buildProposalFromAwaitingRow(
  row: { sessionId: string; ticker: string; name: string | null; proposal: Record<string, unknown> | null },
  marketType: 'kiwoom' | 'coin',
): KRStockTradeProposal | CoinTradeProposal | null {
  const p = row.proposal;
  if (!p) return null;
  const base = {
    id: typeof p.id === 'string' ? p.id : row.sessionId,
    action: (typeof p.action === 'string' ? p.action : 'HOLD') as KRStockTradeProposal['action'],
    quantity: typeof p.quantity === 'number' ? p.quantity : 0,
    entry_price: typeof p.entry_price === 'number' ? p.entry_price : null,
    stop_loss: typeof p.stop_loss === 'number' ? p.stop_loss : null,
    take_profit: typeof p.take_profit === 'number' ? p.take_profit : null,
    risk_score: typeof p.risk_score === 'number' ? p.risk_score : 0,
    position_size_pct: typeof p.position_size_pct === 'number' ? p.position_size_pct : 0,
    rationale: typeof p.rationale === 'string' ? p.rationale : '',
    bull_case: typeof p.bull_case === 'string' ? p.bull_case : '',
    bear_case: typeof p.bear_case === 'string' ? p.bear_case : '',
    created_at: typeof p.created_at === 'string' ? p.created_at : new Date().toISOString(),
  };
  if (marketType === 'kiwoom') {
    return { ...base, stk_cd: row.ticker, stk_nm: row.name };
  }
  return { ...base, market: row.ticker, korean_name: row.name };
}

/** Shape a click on an AwaitingColumn row carries — the SAME shape as the
 * server /operations `awaiting[]` entry (camelCased), never the local
 * sessions[] cache. Both `injectAwaitingKiwoomSession` and
 * `focusAwaitingCoinSession` take this so neither market ever needs the
 * clicked session to already be cached locally. */
export interface AwaitingRowSeed {
  sessionId: string;
  ticker: string;
  name: string | null;
  proposal: Record<string, unknown> | null;
  autoApproveAt: string | null;
}

// -------------------------------------------
// Store Types
// -------------------------------------------

interface HistoryItem {
  ticker: string;  // Stock ticker or coin market code
  sessionId: string;
  timestamp: Date;
  status: SessionStatus | 'idle';

  // Phase 9: Extended analysis data (optional for backward compatibility)
  displayName?: string;
  completedAt?: Date | null;
  analysisResults?: DetailedAnalysisResults | null;
  analyses?: AnalysisSummary[];
  tradeProposal?: CoinTradeProposal | KRStockTradeProposal | null;
  reasoningSummary?: string | null;
  duration?: number | null;  // Analysis duration in ms
  dataVersion?: string;  // Schema version: '1.0' = legacy, '2.0' = with detailed results
}

// Coin-specific history
interface CoinHistoryItem extends HistoryItem {
  type: 'coin';
  koreanName?: string;
}

// Kiwoom (Korean stock) specific history
interface KiwoomHistoryItem extends HistoryItem {
  type: 'kiwoom';
  stk_cd: string;
  stk_nm?: string;
  // Phase F: Trade action for display in AnalysisDetailPage
  action?: string;  // 'BUY' | 'SELL' | 'HOLD' | 'ADD' | 'REDUCE' | 'WATCH' | 'AVOID'
}

// Combined ticker history (for backward compatibility)
type TickerHistoryItem = CoinHistoryItem | KiwoomHistoryItem;

// -------------------------------------------
// Notification Center (P1-3)
// -------------------------------------------
// Persisted mirror of the live /ws/trade-notifications stream — captured
// regardless of whether the bell dropdown is open, so a trade fired during
// unattended operation still shows up as unread after the fact (and
// survives a page refresh).
export interface StoredNotification {
  id: string;
  type: TradeNotificationType;
  data: TradeNotification['data'];
  receivedAt: string;  // ISO string — set at capture time
  read: boolean;
}

// Base analysis state (shared structure)
interface BaseAnalysisState {
  activeSessionId: string | null;
  status: SessionStatus | 'idle';
  currentStage: string | null;
  reasoningLog: string[];
  analyses: AnalysisSummary[];
  awaitingApproval: boolean;
  error: string | null;
}

// Coin-specific state
interface CoinState extends BaseAnalysisState {
  market: string;           // e.g., "KRW-BTC"
  koreanName: string | null;
  tradeProposal: CoinTradeProposal | null;
  activePosition: Position | null;
  history: CoinHistoryItem[];
}

// Kiwoom (Korean stock) specific state - Multi-session support
interface KiwoomState {
  // Multi-session support
  sessions: SessionData[];
  activeSessionId: string | null;  // Currently displayed session
  maxConcurrentSessions: number;   // Default: 3

  // Legacy single-session fields (for backward compatibility)
  stk_cd: string;           // e.g., "005930" (Samsung Electronics)
  stk_nm: string | null;    // e.g., "삼성전자"
  status: SessionStatus | 'idle';
  currentStage: string | null;
  reasoningLog: string[];
  analyses: AnalysisSummary[];
  tradeProposal: KRStockTradeProposal | null;
  awaitingApproval: boolean;
  activePosition: Position | null;
  error: string | null;
  history: KiwoomHistoryItem[];
}

interface ChatState {
  messages: ChatMessage[];
  isTyping: boolean;
}

// P1-3: persisted notification-center slice (see StoredNotification above).
interface NotificationState {
  notifications: StoredNotification[];
}

type MarketType = 'coin' | 'kiwoom';
type Language = 'en' | 'ko';

type ChatPopupSize = 'small' | 'medium' | 'large';

interface UIState {
  // Market selection
  activeMarket: MarketType;

  // Panels
  showChartPanel: boolean;
  showSettingsModal: boolean;
  isMobileMenuOpen: boolean;
  sidebarCollapsed: boolean;

  // Chat Popup (Desktop)
  chatPopupOpen: boolean;
  chatPopupSize: ChatPopupSize;
  chatPopupPosition: { x: number; y: number };

  // Notification center dropdown (P1-3). Ephemeral — NOT persisted, mirrors
  // chatPopupOpen's pattern. A new notification captured while this is true
  // is marked read immediately (the user is looking at it).
  notificationPanelOpen: boolean;

  // Upbit API status
  upbitApiConfigured: boolean;

  // Kiwoom API status
  kiwoomApiConfigured: boolean;

  // Chart config
  chartConfig: ChartConfig;

  // Explicitly-picked chart symbol (e.g. a watchlist row click), independent of
  // any running analysis session. null = fall back to the active session ticker.
  // Cleared on market switch. Ephemeral (not persisted).
  chartSymbol: string | null;

  // First visit tracking (persisted to localStorage)
  hasVisited: boolean;

  // Selected session for detail view
  selectedSessionId: string | null;

  // Language preference for UI and analysis reports
  language: Language;

  // R3 trading modes (Autonomous | HITL) per market. null until fetched from
  // GET /settings/trading-mode (components fetch; the store only holds state).
  // NOT persisted.
  tradingModes: { kiwoom: TradingMode; coin: TradingMode } | null;
  autonomyMasterEnabled: boolean;

  // P4 T3: brief, app-wide informational toast (e.g. "이미 보유 중 · 포지션
  // 관리 분석" when useStartAnalysis's start() sees position_exists=true).
  // Deliberately a SEPARATE slot from the per-session `error` field/
  // selectError/setError: setError routes through setKiwoomError/
  // setCoinError, which ALSO flip that session's status to 'error' — wrong
  // for a benign advisory note. Ephemeral, NOT persisted.
  infoNotice: string | null;
}

// -------------------------------------------
// Basket (user-facing label: "Scratchpad", P2-T3) Types
//
// "Watchlist" is reserved for the SERVER watch-list (WATCH decisions /
// scanner promotions — see OperationsPanel's "감시" column, reused by
// FunnelPanel's WATCHLIST section; the standalone /trading WatchListWidget
// was removed in P2 funnel-consolidation Task 8b once its actions were
// backported there). This client-side research-staging slice keeps its
// internal `basket` identifiers (type/action names, persist key) as-is to
// minimize blast radius; only user-facing labels changed.
// -------------------------------------------

export interface BasketItem {
  id: string;
  marketType: MarketType;
  ticker: string;           // 005930, KRW-BTC, AAPL
  displayName: string;      // 삼성전자, 비트코인, Apple Inc.
  price: number;
  prevPrice: number;        // For calculating change
  changeRate: number;       // Percentage change
  change: 'RISE' | 'FALL' | 'EVEN';
  addedAt: Date;
  lastUpdated: Date | null;
  isLoading: boolean;
  error: string | null;     // API error message if any
}

interface BasketState {
  items: BasketItem[];
  maxItems: number;         // Default: 10
  isUpdating: boolean;
}

interface BasketActions {
  addToBasket: (item: Omit<BasketItem, 'id' | 'addedAt' | 'lastUpdated' | 'isLoading' | 'error'>) => boolean;
  removeFromBasket: (id: string) => void;
  clearBasket: () => void;
  updateBasketItemPrice: (ticker: string, price: number, changeRate: number, change: 'RISE' | 'FALL' | 'EVEN') => void;
  setBasketItemLoading: (ticker: string, loading: boolean) => void;
  setBasketItemError: (ticker: string, error: string | null) => void;
}

interface CoinActions {
  // Coin session actions
  startCoinSession: (sessionId: string, market: string, koreanName?: string) => void;
  setCoinStatus: (status: SessionStatus) => void;
  setCoinStage: (stage: string) => void;
  addCoinReasoning: (entry: string) => void;
  setCoinAnalyses: (analyses: AnalysisSummary[]) => void;
  addCoinAnalysis: (analysis: AnalysisSummary) => void;
  setCoinProposal: (proposal: CoinTradeProposal | null) => void;
  setCoinAwaitingApproval: (awaiting: boolean) => void;
  setCoinPosition: (position: Position | null) => void;
  setCoinError: (error: string | null) => void;
  resetCoin: () => void;
  // History management
  removeCoinHistoryItem: (sessionId: string) => void;

  /**
   * Approval-reachability fix (T7 review HIGH #2): coin has no sessions[]
   * array — a single active-session slot. Two concurrent AWAITING_APPROVAL
   * coin sessions both render a row in AwaitingColumn, but only one can ever
   * be reflected here at once. This retargets the single slot to the
   * CLICKED row's own data (id/ticker/name/proposal) rather than trusting
   * whatever the slot already held, so clicking either row reaches it — one
   * at a time, but neither is ever permanently unreachable.
   */
  focusAwaitingCoinSession: (row: AwaitingRowSeed) => void;
}

interface KiwoomActions {
  // Kiwoom (Korean stock) session actions - Legacy (operates on active session)
  startKiwoomSession: (sessionId: string, stk_cd: string, stk_nm?: string) => void;
  setKiwoomStatus: (status: SessionStatus) => void;
  setKiwoomStage: (stage: string) => void;
  addKiwoomReasoning: (entry: string) => void;
  setKiwoomAnalyses: (analyses: AnalysisSummary[]) => void;
  addKiwoomAnalysis: (analysis: AnalysisSummary) => void;
  setKiwoomProposal: (proposal: KRStockTradeProposal | null) => void;
  setKiwoomAwaitingApproval: (awaiting: boolean) => void;
  setKiwoomPosition: (position: Position | null) => void;
  setKiwoomError: (error: string | null) => void;
  resetKiwoom: () => void;

  // Multi-session management
  addKiwoomSession: (session: SessionData) => boolean;
  removeKiwoomSession: (sessionId: string) => void;
  setActiveKiwoomSession: (sessionId: string | null) => void;

  /**
   * Approval-reachability fix (T7 review HIGH #1): the AwaitingColumn's rows
   * come from the server /operations poll, NOT from this local sessions[]
   * cache (which is populated only by rehydrateKiwoomSessions at mount + the
   * live WS handlers for sessions THIS tab started/streamed). A session that
   * reached AWAITING_APPROVAL without this tab's involvement (autonomous
   * auto-trigger, another tab, watch-monitor reanalysis, a long-lived tab)
   * has a row here but no local session — setActiveKiwoomSession silently
   * no-ops on that cache miss, stranding the approval. This upserts a
   * session from the row's OWN data (never trusts local cache presence) and
   * makes it active, so the click always resolves to a rail target.
   */
  injectAwaitingKiwoomSession: (row: AwaitingRowSeed) => void;

  // Multi-session state updates (sessionId-specific)
  updateKiwoomSessionStatus: (sessionId: string, status: SessionStatus) => void;
  updateKiwoomSessionStage: (sessionId: string, stage: string) => void;
  addKiwoomSessionReasoning: (sessionId: string, entry: string) => void;
  // Batched variant: appends N buffered entries in a single set() — used by the
  // WS handler's flush timer to avoid one store-wide re-render per streamed token.
  addKiwoomSessionReasoningBatch: (sessionId: string, entries: string[]) => void;
  setKiwoomSessionProposal: (sessionId: string, proposal: KRStockTradeProposal | null) => void;
  setKiwoomSessionAwaitingApproval: (sessionId: string, awaiting: boolean) => void;
  setKiwoomSessionAutoApproveAt: (sessionId: string, iso: string | null) => void;
  setKiwoomSessionError: (sessionId: string, error: string | null) => void;

  // Phase 9: Complete session with detailed analysis results
  completeKiwoomSession: (
    sessionId: string,
    data: {
      analysisResults?: DetailedAnalysisResults | null;
      tradeProposal?: KRStockTradeProposal | null;
      reasoningSummary?: string;
      completedAt?: Date;
    }
  ) => void;

  // History management
  removeKiwoomHistoryItem: (sessionId: string) => void;
}

interface ChatActions {
  addChatMessage: (message: Omit<ChatMessage, 'id' | 'timestamp'>) => void;
  setIsTyping: (typing: boolean) => void;
  clearChat: () => void;
}

// P1-3 notification center actions.
interface NotificationActions {
  // Captures a live WS notification into the bounded, persisted store.
  // Marked read immediately if the panel is currently open.
  addNotification: (notification: { type: TradeNotificationType; data: TradeNotification['data'] }) => void;
  markNotificationsRead: () => void;
  clearAllNotifications: () => void;
}

interface UIActions {
  setActiveMarket: (market: MarketType) => void;
  setShowChartPanel: (show: boolean) => void;
  setShowSettingsModal: (show: boolean) => void;
  setMobileMenuOpen: (open: boolean) => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
  // Chat Popup actions
  setChatPopupOpen: (open: boolean) => void;
  toggleChatPopup: () => void;
  setChatPopupSize: (size: ChatPopupSize) => void;
  setChatPopupPosition: (position: { x: number; y: number }) => void;
  // Notification panel (P1-3)
  setNotificationPanelOpen: (open: boolean) => void;
  setUpbitApiConfigured: (configured: boolean) => void;
  setKiwoomApiConfigured: (configured: boolean) => void;
  setChartTimeframe: (timeframe: TimeFrame) => void;
  toggleChartIndicator: (indicator: 'showSMA50' | 'showSMA200' | 'showVolume') => void;
  setChartSymbol: (symbol: string | null) => void;
  setHasVisited: (visited: boolean) => void;
  setSelectedSessionId: (sessionId: string | null) => void;
  // Language preference
  setLanguage: (language: Language) => void;
  // R3 trading modes — sync setter fed by callers (fetch stays in components/hooks)
  setTradingModes: (resp: TradingModeResponse) => void;
  // P4 T3 — see UIState.infoNotice doc comment.
  setInfoNotice: (message: string | null) => void;
}

// Legacy actions for backward compatibility
interface LegacyActions {
  startSession: (sessionId: string, ticker: string) => void;
  setStatus: (status: SessionStatus) => void;
  setCurrentStage: (stage: string) => void;
  addReasoningEntry: (entry: string) => void;
  setAnalyses: (analyses: AnalysisSummary[]) => void;
  addAnalysis: (analysis: AnalysisSummary) => void;
  setAwaitingApproval: (awaiting: boolean) => void;
  setActivePosition: (position: Position | null) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

type Store = {
  coin: CoinState;
  kiwoom: KiwoomState;
  basket: BasketState;
} & ChatState & NotificationState & UIState & CoinActions & KiwoomActions & ChatActions &
  NotificationActions & UIActions & BasketActions & LegacyActions;

// -------------------------------------------
// Initial States
// -------------------------------------------

const initialCoinState: CoinState = {
  activeSessionId: null,
  market: '',
  koreanName: null,
  status: 'idle',
  currentStage: null,
  reasoningLog: [],
  analyses: [],
  tradeProposal: null,
  awaitingApproval: false,
  activePosition: null,
  error: null,
  history: [],
};

const initialKiwoomState: KiwoomState = {
  // Multi-session support
  sessions: [],
  activeSessionId: null,
  maxConcurrentSessions: 3,

  // Legacy single-session fields (for backward compatibility)
  stk_cd: '',
  stk_nm: null,
  status: 'idle',
  currentStage: null,
  reasoningLog: [],
  analyses: [],
  tradeProposal: null,
  awaitingApproval: false,
  activePosition: null,
  error: null,
  history: [],
};

const initialBasketState: BasketState = {
  items: [],
  maxItems: 10,
  isUpdating: false,
};

const initialChatState: ChatState = {
  messages: [],
  isTyping: false,
};

const initialNotificationState: NotificationState = {
  notifications: [],
};

// Note: hasVisited is now persisted via zustand persist middleware
// No need for manual localStorage reading

const initialUIState: UIState = {
  activeMarket: 'kiwoom',
  showChartPanel: true,
  showSettingsModal: false,
  isMobileMenuOpen: false,
  sidebarCollapsed: false,
  // Chat Popup (Desktop) - default values
  chatPopupOpen: false,
  chatPopupSize: 'medium',
  chatPopupPosition: { x: -1, y: -1 }, // -1 = use default position (bottom-right)
  notificationPanelOpen: false,
  upbitApiConfigured: false,
  kiwoomApiConfigured: false,
  chartConfig: {
    timeframe: '1d',
    showSMA50: true,
    showSMA200: true,
    showVolume: true,
  },
  chartSymbol: null,
  hasVisited: false, // Will be restored from persist middleware
  selectedSessionId: null,
  // Language preference (default: Korean)
  language: 'ko',
  // R3 trading modes — unknown until fetched
  tradingModes: null,
  autonomyMasterEnabled: false,
  infoNotice: null,
};

// -------------------------------------------
// Store Implementation
// -------------------------------------------

// Type for persisted state (partial)
interface PersistedState {
  coin: { history: CoinHistoryItem[] };
  kiwoom: { history: KiwoomHistoryItem[] };
  basket: BasketState;
  hasVisited: boolean;
  chartConfig: ChartConfig;
  sidebarCollapsed: boolean;
  language: Language;
  notifications: StoredNotification[];
}

export const useStore = create<Store>()(
  devtools(
    persist(
      (set, get) => ({
      // Initial states
      coin: initialCoinState,
      kiwoom: initialKiwoomState,
      basket: initialBasketState,
      ...initialChatState,
      ...initialNotificationState,
      ...initialUIState,

      // -------------------------------------------
      // Coin Actions
      // -------------------------------------------
      startCoinSession: (sessionId, market, koreanName) =>
        set((state) => {
          const upperMarket = market.toUpperCase();
          const existingIndex = state.coin.history.findIndex(
            (h) => h.sessionId === sessionId
          );
          let newHistory = [...state.coin.history];
          if (existingIndex === -1) {
            newHistory = [
              {
                type: 'coin' as const,
                ticker: upperMarket,
                koreanName,
                sessionId,
                timestamp: new Date(),
                status: 'running' as const,
              },
              ...state.coin.history,
            ].slice(0, 20);
          }
          return {
            coin: {
              ...initialCoinState,
              activeSessionId: sessionId,
              market: upperMarket,
              koreanName: koreanName || null,
              status: 'running',
              history: newHistory,
            },
          };
        }),

      setCoinStatus: (status) =>
        set((state) => {
          const newHistory = state.coin.history.map((h) =>
            h.sessionId === state.coin.activeSessionId ? { ...h, status } : h
          );
          return {
            coin: { ...state.coin, status, history: newHistory },
          };
        }),

      setCoinStage: (stage) =>
        set((state) => ({
          coin: { ...state.coin, currentStage: stage },
        })),

      addCoinReasoning: (entry) =>
        set((state) => ({
          coin: {
            ...state.coin,
            reasoningLog: [...state.coin.reasoningLog, entry],
          },
        })),

      setCoinAnalyses: (analyses) =>
        set((state) => ({
          coin: { ...state.coin, analyses },
        })),

      addCoinAnalysis: (analysis) =>
        set((state) => ({
          coin: {
            ...state.coin,
            analyses: [...state.coin.analyses, analysis],
          },
        })),

      setCoinProposal: (proposal) =>
        set((state) => {
          // Add proposal message to chat if proposal exists
          const newMessages = proposal
            ? [
                ...state.messages,
                {
                  id: generateUUID(),
                  role: 'proposal' as const,
                  content: `Trade Proposal for ${proposal.korean_name || proposal.market}`,
                  timestamp: new Date(),
                  metadata: { proposal },
                },
              ]
            : state.messages;

          return {
            coin: { ...state.coin, tradeProposal: proposal },
            messages: newMessages,
            chatPopupOpen: proposal !== null ? true : state.chatPopupOpen,
          };
        }),

      setCoinAwaitingApproval: (awaiting) =>
        set((state) => {
          // NOTE: Dialog opening is handled ONLY by setCoinProposal to prevent race conditions
          // When both status and proposal messages arrive close together, only proposal setter opens dialog
          return {
            coin: { ...state.coin, awaitingApproval: awaiting },
          };
        }),

      // T7 review HIGH #2 — see interface doc comment. Reusing the same
      // session (already the active one) only patches the fields the row
      // carries; switching to a DIFFERENT session resets the rest of the
      // slot (reasoningLog/analyses/activePosition) exactly like
      // startCoinSession already does, since this single-slot state was
      // never designed to hold two sessions' data at once — that's the very
      // limitation this fix works around by re-targeting the slot per click
      // instead of leaving the second session's row un-clickable.
      focusAwaitingCoinSession: (row) =>
        set((state) => {
          const proposal = buildProposalFromAwaitingRow(row, 'coin') as CoinTradeProposal | null;
          const sameSession = state.coin.activeSessionId === row.sessionId;
          const base = sameSession ? state.coin : { ...initialCoinState, history: state.coin.history };
          return {
            coin: {
              ...base,
              activeSessionId: row.sessionId,
              market: row.ticker,
              koreanName: row.name,
              status: 'awaiting_approval',
              tradeProposal: proposal ?? base.tradeProposal,
              awaitingApproval: true,
            },
          };
        }),

      setCoinPosition: (position) =>
        set((state) => ({
          coin: { ...state.coin, activePosition: position },
        })),

      setCoinError: (error) =>
        set((state) => ({
          coin: {
            ...state.coin,
            error,
            status: error ? 'error' : state.coin.status,
          },
        })),

      resetCoin: () =>
        set((state) => ({
          coin: {
            ...initialCoinState,
            history: state.coin.history,
          },
        })),

      removeCoinHistoryItem: (sessionId) =>
        set((state) => ({
          coin: {
            ...state.coin,
            history: state.coin.history.filter(h => h.sessionId !== sessionId),
          },
        })),

      // -------------------------------------------
      // Kiwoom (Korean Stock) Actions
      // -------------------------------------------
      startKiwoomSession: (sessionId, stk_cd, stk_nm) =>
        set((state) => {
          console.log('[Store] startKiwoomSession called', {
            sessionId,
            stk_cd,
            stk_nm,
            existingSessions: state.kiwoom.sessions.map(s => s.sessionId),
          });

          // Add to history if not exists
          const existingIndex = state.kiwoom.history.findIndex(
            (h) => h.sessionId === sessionId
          );
          let newHistory = [...state.kiwoom.history];
          if (existingIndex === -1) {
            newHistory = [
              {
                type: 'kiwoom' as const,
                ticker: stk_cd,
                stk_cd,
                stk_nm,
                sessionId,
                timestamp: new Date(),
                status: 'running' as const,
              },
              ...state.kiwoom.history,
            ].slice(0, 20);
          }

          // Create new SessionData object and add to sessions[] array
          const now = new Date();
          const newSession: SessionData = {
            sessionId,
            ticker: stk_cd,
            displayName: stk_nm || stk_cd,
            marketType: 'kiwoom' as const,
            status: 'running' as SessionStatus,
            currentStage: null,
            reasoningLog: [],
            analyses: [],
            tradeProposal: null,
            awaitingApproval: false,
            autoApproveAt: null,
            activePosition: null,
            error: null,
            createdAt: now,
            updatedAt: now,
          };

          // Add to sessions array if not already exists
          const existingSessionIndex = state.kiwoom.sessions.findIndex(
            s => s.sessionId === sessionId
          );
          const newSessions = existingSessionIndex === -1
            ? [...state.kiwoom.sessions, newSession]
            : state.kiwoom.sessions;

          console.log('[Store] startKiwoomSession - session added', {
            sessionId,
            totalSessions: newSessions.length,
            allSessionIds: newSessions.map(s => s.sessionId),
          });

          return {
            kiwoom: {
              ...initialKiwoomState,
              // Include the new session in the sessions array
              sessions: newSessions,
              activeSessionId: sessionId,
              stk_cd,
              stk_nm: stk_nm || null,
              status: 'running',
              history: newHistory,
            },
          };
        }),

      setKiwoomStatus: (status) =>
        set((state) => {
          // Update history
          const newHistory = state.kiwoom.history.map((h) =>
            h.sessionId === state.kiwoom.activeSessionId ? { ...h, status } : h
          );
          // Also update sessions[] array to keep in sync. A status change away
          // from awaiting_approval invalidates any pending auto-approve countdown.
          const newSessions = state.kiwoom.sessions.map((s) =>
            s.sessionId === state.kiwoom.activeSessionId
              ? {
                  ...s,
                  status: status as SessionStatus,
                  autoApproveAt: status === 'awaiting_approval' ? s.autoApproveAt : null,
                  updatedAt: new Date(),
                }
              : s
          );
          return {
            kiwoom: { ...state.kiwoom, status, history: newHistory, sessions: newSessions },
          };
        }),

      setKiwoomStage: (stage) =>
        set((state) => {
          // Also update sessions[] array to keep in sync
          const newSessions = state.kiwoom.sessions.map((s) =>
            s.sessionId === state.kiwoom.activeSessionId
              ? { ...s, currentStage: stage, updatedAt: new Date() }
              : s
          );
          return {
            kiwoom: { ...state.kiwoom, currentStage: stage, sessions: newSessions },
          };
        }),

      addKiwoomReasoning: (entry) =>
        set((state) => {
          // Also update sessions[] array to keep in sync
          const newSessions = state.kiwoom.sessions.map((s) =>
            s.sessionId === state.kiwoom.activeSessionId
              ? { ...s, reasoningLog: [...s.reasoningLog, entry], updatedAt: new Date() }
              : s
          );
          return {
            kiwoom: {
              ...state.kiwoom,
              reasoningLog: [...state.kiwoom.reasoningLog, entry],
              sessions: newSessions,
            },
          };
        }),

      setKiwoomAnalyses: (analyses) =>
        set((state) => {
          // Also update sessions[] array to keep in sync
          const newSessions = state.kiwoom.sessions.map((s) =>
            s.sessionId === state.kiwoom.activeSessionId
              ? { ...s, analyses, updatedAt: new Date() }
              : s
          );
          return {
            kiwoom: { ...state.kiwoom, analyses, sessions: newSessions },
          };
        }),

      addKiwoomAnalysis: (analysis) =>
        set((state) => {
          const newAnalyses = [...state.kiwoom.analyses, analysis];
          // Also update sessions[] array to keep in sync
          const newSessions = state.kiwoom.sessions.map((s) =>
            s.sessionId === state.kiwoom.activeSessionId
              ? { ...s, analyses: [...s.analyses, analysis], updatedAt: new Date() }
              : s
          );
          return {
            kiwoom: {
              ...state.kiwoom,
              analyses: newAnalyses,
              sessions: newSessions,
            },
          };
        }),

      setKiwoomProposal: (proposal) =>
        set((state) => {
          // Add proposal message to chat if proposal exists
          const newMessages = proposal
            ? [
                ...state.messages,
                {
                  id: generateUUID(),
                  role: 'proposal' as const,
                  content: `Trade Proposal for ${proposal.stk_nm || proposal.stk_cd}`,
                  timestamp: new Date(),
                  metadata: { proposal },
                },
              ]
            : state.messages;

          // Also update sessions[] array to keep in sync
          const newSessions = state.kiwoom.sessions.map((s) =>
            s.sessionId === state.kiwoom.activeSessionId
              ? { ...s, tradeProposal: proposal, updatedAt: new Date() }
              : s
          );

          return {
            kiwoom: { ...state.kiwoom, tradeProposal: proposal, sessions: newSessions },
            messages: newMessages,
            chatPopupOpen: proposal !== null ? true : state.chatPopupOpen,
          };
        }),

      setKiwoomAwaitingApproval: (awaiting) =>
        set((state) => {
          // Also update sessions[] array to keep in sync
          const newSessions = state.kiwoom.sessions.map((s) =>
            s.sessionId === state.kiwoom.activeSessionId
              ? { ...s, awaitingApproval: awaiting, updatedAt: new Date() }
              : s
          );

          // NOTE: Dialog opening is handled ONLY by setKiwoomProposal to prevent race conditions
          // When both status and proposal messages arrive close together, only proposal setter opens dialog
          return {
            kiwoom: { ...state.kiwoom, awaitingApproval: awaiting, sessions: newSessions },
          };
        }),

      setKiwoomPosition: (position) =>
        set((state) => {
          // Also update sessions[] array to keep in sync
          const newSessions = state.kiwoom.sessions.map((s) =>
            s.sessionId === state.kiwoom.activeSessionId
              ? { ...s, activePosition: position, updatedAt: new Date() }
              : s
          );
          return {
            kiwoom: { ...state.kiwoom, activePosition: position, sessions: newSessions },
          };
        }),

      setKiwoomError: (error) =>
        set((state) => {
          const newStatus = error ? 'error' : state.kiwoom.status;
          // Also update sessions[] array to keep in sync
          const newSessions = state.kiwoom.sessions.map((s) =>
            s.sessionId === state.kiwoom.activeSessionId
              ? { ...s, error, status: (error ? 'error' : s.status) as SessionStatus, updatedAt: new Date() }
              : s
          );
          return {
            kiwoom: {
              ...state.kiwoom,
              error,
              status: newStatus,
              sessions: newSessions,
            },
          };
        }),

      resetKiwoom: () =>
        set((state) => ({
          kiwoom: {
            ...initialKiwoomState,
            sessions: state.kiwoom.sessions,
            history: state.kiwoom.history,
          },
        })),

      // -------------------------------------------
      // Kiwoom Multi-Session Actions
      // -------------------------------------------
      addKiwoomSession: (session) => {
        const state = get();
        console.log('[Store] addKiwoomSession called', {
          newSessionId: session.sessionId,
          ticker: session.ticker,
          existingSessions: state.kiwoom.sessions.map(s => ({ id: s.sessionId, ticker: s.ticker })),
          currentCount: state.kiwoom.sessions.length,
        });

        // Check if session already exists
        if (state.kiwoom.sessions.some(s => s.sessionId === session.sessionId)) {
          console.warn('[Store] Session already exists, skipping', session.sessionId);
          return false;
        }
        // Check max concurrent limit
        const runningSessions = state.kiwoom.sessions.filter(
          s => s.status === 'running' || s.status === 'awaiting_approval'
        );
        if (runningSessions.length >= state.kiwoom.maxConcurrentSessions) {
          console.warn('[Store] Max concurrent sessions reached', {
            running: runningSessions.length,
            max: state.kiwoom.maxConcurrentSessions,
          });
          return false;
        }

        const newSessions = [...state.kiwoom.sessions, session];
        console.log('[Store] Session added successfully', {
          newSessionId: session.sessionId,
          totalSessions: newSessions.length,
          allSessionIds: newSessions.map(s => s.sessionId),
        });

        // Also add to history if not already there
        const existingHistoryIndex = state.kiwoom.history.findIndex(
          h => h.sessionId === session.sessionId
        );
        let newHistory = [...state.kiwoom.history];
        if (existingHistoryIndex === -1) {
          newHistory = [
            {
              type: 'kiwoom' as const,
              ticker: session.ticker,
              stk_cd: session.ticker,
              stk_nm: session.displayName,
              sessionId: session.sessionId,
              timestamp: new Date(),
              status: session.status as 'running' | 'completed' | 'cancelled' | 'error',
            },
            ...state.kiwoom.history,
          ].slice(0, 20);
        }

        set({
          kiwoom: {
            ...state.kiwoom,
            sessions: newSessions,
            history: newHistory,
            activeSessionId: session.sessionId,
            // Update legacy fields to match active session
            stk_cd: session.ticker,
            stk_nm: session.displayName,
            status: session.status,
            currentStage: session.currentStage,
            reasoningLog: session.reasoningLog,
            analyses: session.analyses,
            tradeProposal: session.tradeProposal as KRStockTradeProposal | null,
            awaitingApproval: session.awaitingApproval,
            activePosition: session.activePosition,
            error: session.error,
          },
        });
        return true;
      },

      removeKiwoomSession: (sessionId) => {
        // P0-3: a removed card must take its socket with it — the rehydrate
        // purge and every UI close path funnel through this action, and a
        // socket left behind reconnects forever against a dead session.
        wsManager.disconnect(sessionId);
        return set((state) => {
          const newSessions = state.kiwoom.sessions.filter(s => s.sessionId !== sessionId);
          const wasActive = state.kiwoom.activeSessionId === sessionId;
          const newActiveId = wasActive
            ? (newSessions.length > 0 ? newSessions[0].sessionId : null)
            : state.kiwoom.activeSessionId;
          const activeSession = newSessions.find(s => s.sessionId === newActiveId);

          return {
            kiwoom: {
              ...state.kiwoom,
              sessions: newSessions,
              activeSessionId: newActiveId,
              // Update legacy fields if active session changed
              ...(wasActive && activeSession ? {
                stk_cd: activeSession.ticker,
                stk_nm: activeSession.displayName,
                status: activeSession.status,
                currentStage: activeSession.currentStage,
                reasoningLog: activeSession.reasoningLog,
                analyses: activeSession.analyses,
                tradeProposal: activeSession.tradeProposal as KRStockTradeProposal | null,
                awaitingApproval: activeSession.awaitingApproval,
                activePosition: activeSession.activePosition,
                error: activeSession.error,
              } : {}),
              ...(wasActive && !activeSession ? {
                stk_cd: '',
                stk_nm: null,
                status: 'idle' as const,
                currentStage: null,
                reasoningLog: [],
                analyses: [],
                tradeProposal: null,
                awaitingApproval: false,
                activePosition: null,
                error: null,
              } : {}),
            },
          };
        });
      },

      setActiveKiwoomSession: (sessionId) =>
        set((state) => {
          const session = state.kiwoom.sessions.find(s => s.sessionId === sessionId);
          if (!session && sessionId !== null) {
            return state;
          }
          return {
            kiwoom: {
              ...state.kiwoom,
              activeSessionId: sessionId,
              // Sync legacy fields with active session
              ...(session ? {
                stk_cd: session.ticker,
                stk_nm: session.displayName,
                status: session.status,
                currentStage: session.currentStage,
                reasoningLog: session.reasoningLog,
                analyses: session.analyses,
                tradeProposal: session.tradeProposal as KRStockTradeProposal | null,
                awaitingApproval: session.awaitingApproval,
                activePosition: session.activePosition,
                error: session.error,
              } : {}),
            },
          };
        }),

      // T7 review HIGH #1 — see interface doc comment. Upserts rather than
      // requiring the session to pre-exist (unlike setActiveKiwoomSession
      // above, which this deliberately does NOT reuse for that reason: its
      // cache-miss no-op is exactly the bug). An existing session's OWN
      // tradeProposal is preferred over the row's slimmed reconstruction
      // when both exist (the live WS-fed copy may carry more than the
      // slim allowlist) — the row only fills in when the local copy is
      // absent (proposal null) or the session itself doesn't exist yet.
      injectAwaitingKiwoomSession: (row) =>
        set((state) => {
          const idx = state.kiwoom.sessions.findIndex(s => s.sessionId === row.sessionId);
          const proposal = buildProposalFromAwaitingRow(row, 'kiwoom') as KRStockTradeProposal | null;
          const now = new Date();
          let session: SessionData;
          let newSessions: SessionData[];
          if (idx === -1) {
            session = {
              sessionId: row.sessionId,
              ticker: row.ticker,
              displayName: row.name || row.ticker,
              marketType: 'kiwoom',
              status: 'awaiting_approval',
              currentStage: null,
              reasoningLog: [],
              analyses: [],
              tradeProposal: proposal,
              awaitingApproval: true,
              autoApproveAt: row.autoApproveAt,
              activePosition: null,
              error: null,
              createdAt: now,
              updatedAt: now,
            };
            newSessions = [...state.kiwoom.sessions, session];
          } else {
            const existing = state.kiwoom.sessions[idx];
            session = {
              ...existing,
              status: 'awaiting_approval',
              tradeProposal: (existing.tradeProposal as KRStockTradeProposal | null) ?? proposal,
              awaitingApproval: true,
              autoApproveAt: row.autoApproveAt,
              updatedAt: now,
            };
            newSessions = state.kiwoom.sessions.map((s, i) => (i === idx ? session : s));
          }
          return {
            kiwoom: {
              ...state.kiwoom,
              sessions: newSessions,
              activeSessionId: row.sessionId,
              stk_cd: session.ticker,
              stk_nm: session.displayName,
              status: session.status,
              currentStage: session.currentStage,
              reasoningLog: session.reasoningLog,
              analyses: session.analyses,
              tradeProposal: session.tradeProposal as KRStockTradeProposal | null,
              awaitingApproval: session.awaitingApproval,
              activePosition: session.activePosition,
              error: session.error,
            },
          };
        }),

      updateKiwoomSessionStatus: (sessionId, status) =>
        set((state) => {
          console.log('[Store] updateKiwoomSessionStatus called:', {
            sessionId,
            status,
            existingSessions: state.kiwoom.sessions.map(s => ({ id: s.sessionId, status: s.status })),
            activeSessionId: state.kiwoom.activeSessionId,
          });
          // A status change away from awaiting_approval invalidates any pending
          // auto-approve countdown (manual decision / completion / error).
          const newSessions = state.kiwoom.sessions.map(s =>
            s.sessionId === sessionId
              ? {
                  ...s,
                  status,
                  autoApproveAt: status === 'awaiting_approval' ? s.autoApproveAt : null,
                  updatedAt: new Date(),
                }
              : s
          );
          // Also update history to keep status in sync
          const newHistory = state.kiwoom.history.map(h =>
            h.sessionId === sessionId ? { ...h, status } : h
          );
          const isActive = state.kiwoom.activeSessionId === sessionId;
          console.log('[Store] updateKiwoomSessionStatus result:', {
            sessionFound: state.kiwoom.sessions.some(s => s.sessionId === sessionId),
            newSessions: newSessions.map(s => ({ id: s.sessionId, status: s.status })),
            isActive,
          });
          return {
            kiwoom: {
              ...state.kiwoom,
              sessions: newSessions,
              history: newHistory,
              ...(isActive ? { status } : {}),
            },
          };
        }),

      updateKiwoomSessionStage: (sessionId, stage) =>
        set((state) => {
          const newSessions = state.kiwoom.sessions.map(s =>
            s.sessionId === sessionId
              ? { ...s, currentStage: stage, updatedAt: new Date() }
              : s
          );
          const isActive = state.kiwoom.activeSessionId === sessionId;
          return {
            kiwoom: {
              ...state.kiwoom,
              sessions: newSessions,
              ...(isActive ? { currentStage: stage } : {}),
            },
          };
        }),

      addKiwoomSessionReasoning: (sessionId, entry) =>
        set((state) => {
          const newSessions = state.kiwoom.sessions.map(s =>
            s.sessionId === sessionId
              ? { ...s, reasoningLog: [...s.reasoningLog, entry], updatedAt: new Date() }
              : s
          );
          const isActive = state.kiwoom.activeSessionId === sessionId;
          const session = newSessions.find(s => s.sessionId === sessionId);
          return {
            kiwoom: {
              ...state.kiwoom,
              sessions: newSessions,
              ...(isActive && session ? { reasoningLog: session.reasoningLog } : {}),
            },
          };
        }),

      // Batched: appends every buffered entry in ONE set() call (one subscriber
      // notification instead of N) — see addKiwoomSessionReasoning above for the
      // per-entry semantics this mirrors (session-map update + legacy mirror).
      addKiwoomSessionReasoningBatch: (sessionId, entries) =>
        set((state) => {
          const newSessions = state.kiwoom.sessions.map(s =>
            s.sessionId === sessionId
              ? { ...s, reasoningLog: [...s.reasoningLog, ...entries], updatedAt: new Date() }
              : s
          );
          const isActive = state.kiwoom.activeSessionId === sessionId;
          const session = newSessions.find(s => s.sessionId === sessionId);
          return {
            kiwoom: {
              ...state.kiwoom,
              sessions: newSessions,
              ...(isActive && session ? { reasoningLog: session.reasoningLog } : {}),
            },
          };
        }),

      setKiwoomSessionProposal: (sessionId, proposal) =>
        set((state) => {
          // Idempotency: re-delivery of the SAME proposal (same id) updates the
          // stored fields silently — no new chat message, no popup force.
          // Happens on refresh rehydration (rehydrateKiwoomSessions sets the
          // proposal, then the fresh WS snapshot re-emits the proposal frame)
          // and on /workflow route re-entry reconnecting the stream.
          const currentProposal = state.kiwoom.sessions.find(
            s => s.sessionId === sessionId
          )?.tradeProposal;
          const isSameProposal =
            proposal !== null && currentProposal != null && currentProposal.id === proposal.id;

          const newSessions = state.kiwoom.sessions.map(s =>
            s.sessionId === sessionId
              ? { ...s, tradeProposal: proposal, updatedAt: new Date() }
              : s
          );
          const isActive = state.kiwoom.activeSessionId === sessionId;

          // Add proposal message to chat if a NEW proposal exists
          const newMessages = proposal && !isSameProposal
            ? [
                ...state.messages,
                {
                  id: generateUUID(),
                  role: 'proposal' as const,
                  content: `Trade Proposal for ${(proposal as KRStockTradeProposal).stk_nm || (proposal as KRStockTradeProposal).stk_cd}`,
                  timestamp: new Date(),
                  metadata: { proposal },
                },
              ]
            : state.messages;

          return {
            kiwoom: {
              ...state.kiwoom,
              sessions: newSessions,
              ...(isActive ? { tradeProposal: proposal } : {}),
            },
            messages: newMessages,
            chatPopupOpen: proposal !== null && !isSameProposal ? true : state.chatPopupOpen,
          };
        }),

      setKiwoomSessionAwaitingApproval: (sessionId, awaiting) =>
        set((state) => {
          const newSessions = state.kiwoom.sessions.map(s =>
            s.sessionId === sessionId
              ? { ...s, awaitingApproval: awaiting, updatedAt: new Date() }
              : s
          );
          const isActive = state.kiwoom.activeSessionId === sessionId;

          // NOTE: Dialog opening is handled ONLY by setKiwoomSessionProposal to prevent race conditions
          // When both status and proposal messages arrive close together, only proposal setter opens dialog
          return {
            kiwoom: {
              ...state.kiwoom,
              sessions: newSessions,
              ...(isActive ? { awaitingApproval: awaiting } : {}),
            },
          };
        }),

      setKiwoomSessionAutoApproveAt: (sessionId, iso) =>
        set((state) => ({
          kiwoom: {
            ...state.kiwoom,
            sessions: state.kiwoom.sessions.map(s =>
              s.sessionId === sessionId
                ? { ...s, autoApproveAt: iso, updatedAt: new Date() }
                : s
            ),
          },
        })),

      setKiwoomSessionError: (sessionId, error) =>
        set((state) => {
          const newSessions = state.kiwoom.sessions.map(s =>
            s.sessionId === sessionId
              ? {
                  ...s,
                  error,
                  status: error ? 'error' as const : s.status,
                  // An error ends the approval wait — drop any auto-approve countdown.
                  autoApproveAt: error ? null : s.autoApproveAt,
                  updatedAt: new Date(),
                }
              : s
          );
          const isActive = state.kiwoom.activeSessionId === sessionId;
          const session = newSessions.find(s => s.sessionId === sessionId);
          return {
            kiwoom: {
              ...state.kiwoom,
              sessions: newSessions,
              ...(isActive && session ? { error, status: session.status } : {}),
            },
          };
        }),

      // Phase 9: Complete session with detailed analysis results
      completeKiwoomSession: (sessionId, data) =>
        set((state) => {
          const session = state.kiwoom.sessions.find(s => s.sessionId === sessionId);
          const startTime = session?.createdAt;
          const now = new Date();
          const duration = startTime ? now.getTime() - new Date(startTime).getTime() : null;

          // Generate reasoning summary from log
          const reasoningSummary = data.reasoningSummary ||
            (session?.reasoningLog?.slice(-3).join('\n') || null);

          // Update sessions array
          const newSessions = state.kiwoom.sessions.map(s =>
            s.sessionId === sessionId
              ? {
                  ...s,
                  status: 'completed' as const,
                  tradeProposal: data.tradeProposal ?? s.tradeProposal,
                  // Completion ends the approval wait — drop any auto-approve countdown.
                  autoApproveAt: null,
                  updatedAt: now,
                }
              : s
          );

          // Update history with detailed analysis results
          const proposal = data.tradeProposal ?? session?.tradeProposal ?? null;
          const newHistory = state.kiwoom.history.map(h =>
            h.sessionId === sessionId
              ? {
                  ...h,
                  status: 'completed' as const,
                  completedAt: now,
                  analysisResults: data.analysisResults || null,
                  analyses: session?.analyses || [],
                  tradeProposal: proposal,
                  // Phase F: Extract action from trade proposal for display
                  action: proposal?.action,
                  reasoningSummary,
                  duration,
                  dataVersion: '2.0',
                }
              : h
          );

          const isActive = state.kiwoom.activeSessionId === sessionId;

          console.log('[Store] completeKiwoomSession:', {
            sessionId,
            hasAnalysisResults: !!data.analysisResults,
            hasProposal: !!data.tradeProposal,
            duration,
          });

          return {
            kiwoom: {
              ...state.kiwoom,
              sessions: newSessions,
              history: newHistory,
              ...(isActive ? {
                status: 'completed' as const,
                tradeProposal: data.tradeProposal ?? state.kiwoom.tradeProposal,
              } : {}),
            },
          };
        }),

      removeKiwoomHistoryItem: (sessionId) =>
        set((state) => ({
          kiwoom: {
            ...state.kiwoom,
            history: state.kiwoom.history.filter(h => h.sessionId !== sessionId),
          },
        })),

      // -------------------------------------------
      // Chat Actions
      // -------------------------------------------
      addChatMessage: (message) =>
        set((state) => ({
          messages: [
            ...state.messages,
            {
              ...message,
              id: generateUUID(),
              timestamp: new Date(),
            },
          ],
        })),

      setIsTyping: (typing) => set({ isTyping: typing }),

      clearChat: () => set({ messages: [] }),

      // -------------------------------------------
      // Notification Center Actions (P1-3)
      // -------------------------------------------
      addNotification: (notification) =>
        set((state) => {
          const item: StoredNotification = {
            id: generateUUID(),
            type: notification.type,
            data: notification.data,
            receivedAt: new Date().toISOString(),
            // Already visible to the user if the panel is open right now.
            read: state.notificationPanelOpen,
          };
          return {
            notifications: [item, ...state.notifications].slice(0, MAX_PERSISTED_NOTIFICATIONS),
          };
        }),

      markNotificationsRead: () =>
        set((state) => ({
          notifications: state.notifications.map((n) => (n.read ? n : { ...n, read: true })),
        })),

      clearAllNotifications: () => set({ notifications: [] }),

      // -------------------------------------------
      // UI Actions
      // -------------------------------------------
      setActiveMarket: (market) => set(() => ({
        activeMarket: market,
        // Clear any explicitly-picked chart symbol so the chart falls back to
        // the newly-active market's session ticker instead of a stale symbol.
        chartSymbol: null,
      })),

      setShowChartPanel: (show) => set({ showChartPanel: show }),

      setShowSettingsModal: (show) => set({ showSettingsModal: show }),

      setMobileMenuOpen: (open) => set({ isMobileMenuOpen: open }),

      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),

      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),

      // Chat Popup actions
      setChatPopupOpen: (open) => set({ chatPopupOpen: open }),

      toggleChatPopup: () => set((state) => ({ chatPopupOpen: !state.chatPopupOpen })),

      setChatPopupSize: (size) => set({ chatPopupSize: size }),

      setChatPopupPosition: (position) => set({ chatPopupPosition: position }),

      setNotificationPanelOpen: (open) => set({ notificationPanelOpen: open }),

      setUpbitApiConfigured: (configured) => set({ upbitApiConfigured: configured }),

      setKiwoomApiConfigured: (configured) => set({ kiwoomApiConfigured: configured }),

      setHasVisited: (visited) => set({ hasVisited: visited }),

      setSelectedSessionId: (sessionId) => set({ selectedSessionId: sessionId }),

      setLanguage: (language) => set({ language }),

      setInfoNotice: (message) => set({ infoNotice: message }),

      setTradingModes: (resp) =>
        set({
          tradingModes: { kiwoom: resp.kiwoom, coin: resp.coin },
          autonomyMasterEnabled: resp.master_enabled,
        }),

      setChartTimeframe: (timeframe) =>
        set((state) => ({
          chartConfig: { ...state.chartConfig, timeframe },
        })),

      toggleChartIndicator: (indicator) =>
        set((state) => ({
          chartConfig: {
            ...state.chartConfig,
            [indicator]: !state.chartConfig[indicator],
          },
        })),

      setChartSymbol: (symbol) => set({ chartSymbol: symbol }),

      // -------------------------------------------
      // Basket Actions
      // -------------------------------------------
      addToBasket: (item) => {
        const state = get();
        // Check if basket is full
        if (state.basket.items.length >= state.basket.maxItems) {
          return false;
        }
        // Check if item already exists
        if (state.basket.items.some((i) => i.ticker === item.ticker && i.marketType === item.marketType)) {
          return false;
        }
        const newItem: BasketItem = {
          ...item,
          id: generateUUID(),
          addedAt: new Date(),
          lastUpdated: null,
          isLoading: false,
          error: null,
        };
        set((state) => ({
          basket: {
            ...state.basket,
            items: [...state.basket.items, newItem],
          },
        }));
        return true;
      },

      removeFromBasket: (id) =>
        set((state) => ({
          basket: {
            ...state.basket,
            items: state.basket.items.filter((i) => i.id !== id),
          },
        })),

      clearBasket: () =>
        set((state) => ({
          basket: {
            ...state.basket,
            items: [],
          },
        })),

      updateBasketItemPrice: (ticker, price, changeRate, change) =>
        set((state) => ({
          basket: {
            ...state.basket,
            items: state.basket.items.map((item) =>
              item.ticker === ticker
                ? {
                    ...item,
                    prevPrice: item.price,
                    price,
                    changeRate,
                    change,
                    lastUpdated: new Date(),
                    isLoading: false,
                    error: null,
                  }
                : item
            ),
          },
        })),

      setBasketItemLoading: (ticker, loading) =>
        set((state) => ({
          basket: {
            ...state.basket,
            items: state.basket.items.map((item) =>
              item.ticker === ticker
                ? { ...item, isLoading: loading }
                : item
            ),
          },
        })),

      setBasketItemError: (ticker, error) =>
        set((state) => ({
          basket: {
            ...state.basket,
            items: state.basket.items.map((item) =>
              item.ticker === ticker
                ? { ...item, error, isLoading: false }
                : item
            ),
          },
        })),

      // -------------------------------------------
      // Legacy Actions (for backward compatibility)
      // These delegate to coin or kiwoom based on activeMarket
      // -------------------------------------------
      startSession: (sessionId, ticker) => {
        const market = get().activeMarket;
        if (market === 'coin') {
          get().startCoinSession(sessionId, ticker);
        } else {
          get().startKiwoomSession(sessionId, ticker);
        }
      },

      setStatus: (status) => {
        const market = get().activeMarket;
        if (market === 'coin') {
          get().setCoinStatus(status);
        } else {
          get().setKiwoomStatus(status);
        }
      },

      setCurrentStage: (stage) => {
        const market = get().activeMarket;
        if (market === 'coin') {
          get().setCoinStage(stage);
        } else {
          get().setKiwoomStage(stage);
        }
      },

      addReasoningEntry: (entry) => {
        const market = get().activeMarket;
        if (market === 'coin') {
          get().addCoinReasoning(entry);
        } else {
          get().addKiwoomReasoning(entry);
        }
      },

      setAnalyses: (analyses) => {
        const market = get().activeMarket;
        if (market === 'coin') {
          get().setCoinAnalyses(analyses);
        } else {
          get().setKiwoomAnalyses(analyses);
        }
      },

      addAnalysis: (analysis) => {
        const market = get().activeMarket;
        if (market === 'coin') {
          get().addCoinAnalysis(analysis);
        } else {
          get().addKiwoomAnalysis(analysis);
        }
      },

      setAwaitingApproval: (awaiting) => {
        const market = get().activeMarket;
        if (market === 'coin') {
          get().setCoinAwaitingApproval(awaiting);
        } else {
          get().setKiwoomAwaitingApproval(awaiting);
        }
      },

      setActivePosition: (position) => {
        const market = get().activeMarket;
        if (market === 'coin') {
          get().setCoinPosition(position);
        } else {
          get().setKiwoomPosition(position);
        }
      },

      setError: (error) => {
        const market = get().activeMarket;
        if (market === 'coin') {
          get().setCoinError(error);
        } else {
          get().setKiwoomError(error);
        }
      },

      reset: () => {
        const market = get().activeMarket;
        if (market === 'coin') {
          get().resetCoin();
        } else {
          get().resetKiwoom();
        }
      },
      }),
      {
        name: 'agentic-trading-storage',
        version: 1,
        storage: createJSONStorage(() => localStorage),
        // Only persist history and settings, not active sessions
        // NOTE: activeMarket is deliberately NOT persisted, and `merge` below
        // only picks known keys — so a stale `stock` slice (or a 'stock'
        // activeMarket) left in localStorage by old sessions is ignored.
        partialize: (state): PersistedState => ({
          coin: { history: state.coin.history },
          kiwoom: { history: state.kiwoom.history },
          basket: state.basket,
          hasVisited: state.hasVisited,
          chartConfig: state.chartConfig,
          sidebarCollapsed: state.sidebarCollapsed,
          language: state.language,
          notifications: state.notifications,
        }),
        // Merge persisted state with initial state
        merge: (persistedState, currentState) => {
          const persisted = persistedState as PersistedState | undefined;
          if (!persisted) return currentState;

          // Convert date strings back to Date objects in history
          const parseHistoryDates = <T extends HistoryItem>(history: T[]): T[] =>
            history.map((h) => ({
              ...h,
              timestamp: new Date(h.timestamp),
              completedAt: h.completedAt ? new Date(h.completedAt) : null,
            }));

          return {
            ...currentState,
            coin: {
              ...currentState.coin,
              history: persisted.coin?.history
                ? parseHistoryDates(persisted.coin.history as CoinHistoryItem[])
                : [],
            },
            kiwoom: {
              ...currentState.kiwoom,
              history: persisted.kiwoom?.history
                ? parseHistoryDates(persisted.kiwoom.history as KiwoomHistoryItem[])
                : [],
            },
            // Drop basket items whose market no longer exists (the US 'stock'
            // market was removed; items persisted before that would misroute
            // their Analyze action and poison activeMarket).
            basket: persisted.basket
              ? {
                  ...persisted.basket,
                  items: (persisted.basket.items ?? []).filter(
                    (item) => item.marketType === 'coin' || item.marketType === 'kiwoom'
                  ),
                }
              : currentState.basket,
            hasVisited: persisted.hasVisited ?? currentState.hasVisited,
            chartConfig: persisted.chartConfig ?? currentState.chartConfig,
            sidebarCollapsed: persisted.sidebarCollapsed ?? currentState.sidebarCollapsed,
            language: persisted.language ?? currentState.language,
            // Bounded defensively even on rehydrate — a payload written by a
            // future version (or hand-edited localStorage) shouldn't grow the
            // in-memory list past the cap.
            notifications: Array.isArray(persisted.notifications)
              ? persisted.notifications.slice(0, MAX_PERSISTED_NOTIFICATIONS)
              : currentState.notifications,
          };
        },
      }
    ),
    { name: 'agentic-trading-store' }
  )
);

// -------------------------------------------
// Selectors
// -------------------------------------------

// Helper to get current market data
const getMarketData = (state: Store) => {
  if (state.activeMarket === 'coin') return state.coin;
  return state.kiwoom;
};

// Get current market's session info
export const selectSession = (state: Store) => {
  const market = state.activeMarket;
  const data = getMarketData(state);
  let ticker: string;
  if (market === 'coin') {
    ticker = state.coin.market;
  } else {
    ticker = state.kiwoom.stk_cd;
  }
  return {
    sessionId: data.activeSessionId,
    ticker,
    status: data.status,
  };
};

// Get current market's analysis state
export const selectAnalysis = (state: Store) => {
  const data = getMarketData(state);
  return {
    analyses: data.analyses,
    currentStage: data.currentStage,
    reasoningLog: data.reasoningLog,
  };
};

// Get current market's proposal
export const selectProposal = (state: Store) => {
  const data = getMarketData(state);
  return {
    proposal: data.tradeProposal,
    awaitingApproval: data.awaitingApproval,
  };
};

export const selectChat = (state: Store) => ({
  messages: state.messages,
  isTyping: state.isTyping,
});

// Notification center (P1-3)
export const selectNotifications = (state: Store) => state.notifications;
export const selectUnreadNotificationCount = (state: Store) =>
  state.notifications.reduce((count, n) => (n.read ? count : count + 1), 0);

export const selectChartConfig = (state: Store) => state.chartConfig;
export const selectChartSymbol = (state: Store) => state.chartSymbol;

// Get current market's history
export const selectTickerHistory = (state: Store): TickerHistoryItem[] => {
  if (state.activeMarket === 'coin') return state.coin.history;
  return state.kiwoom.history;
};

// Select coin-specific state
export const selectCoin = (state: Store) => state.coin;

// Select kiwoom-specific state
export const selectKiwoom = (state: Store) => state.kiwoom;

// -------------------------------------------
// Kiwoom Multi-Session Selectors
// -------------------------------------------

// Get all Kiwoom sessions
export const selectKiwoomSessions = (state: Store) => state.kiwoom.sessions;

// Get active Kiwoom session ID
export const selectActiveKiwoomSessionId = (state: Store) => state.kiwoom.activeSessionId;

// Get active Kiwoom session data
export const selectActiveKiwoomSession = (state: Store): SessionData | null => {
  const activeId = state.kiwoom.activeSessionId;
  if (!activeId) return null;
  return state.kiwoom.sessions.find(s => s.sessionId === activeId) || null;
};

// Get Kiwoom session by ID
export const selectKiwoomSessionById = (state: Store, sessionId: string): SessionData | null => {
  return state.kiwoom.sessions.find(s => s.sessionId === sessionId) || null;
};

// Phase 9: Get Kiwoom history item by session ID (with detailed analysis results)
export const selectKiwoomHistoryById = (state: Store, sessionId: string): KiwoomHistoryItem | null => {
  return state.kiwoom.history.find(h => h.sessionId === sessionId) || null;
};

// Get running Kiwoom sessions count
export const selectKiwoomRunningSessionsCount = (state: Store): number => {
  return state.kiwoom.sessions.filter(
    s => s.status === 'running' || s.status === 'awaiting_approval'
  ).length;
};

// Get available Kiwoom session slots
export const selectKiwoomAvailableSlots = (state: Store): number => {
  const running = selectKiwoomRunningSessionsCount(state);
  return state.kiwoom.maxConcurrentSessions - running;
};

// Check if max Kiwoom sessions reached
export const selectIsKiwoomMaxSessionsReached = (state: Store): boolean => {
  return selectKiwoomAvailableSlots(state) <= 0;
};

// Get Kiwoom sessions as ActiveSession format (for UI compatibility)
export const selectKiwoomActiveSessions = (state: Store): ActiveSession[] => {
  return state.kiwoom.sessions
    .filter(s => s.status !== 'completed' && s.status !== 'cancelled' && s.status !== 'error')
    .map(s => ({
      sessionId: s.sessionId,
      ticker: s.ticker,
      displayName: s.displayName,
      marketType: 'kiwoom' as const,
      status: s.status,
      currentStage: s.currentStage,
      reasoningLog: s.reasoningLog,
    }));
};

// Legacy selectors for backward compatibility
export const selectActiveSessionId = (state: Store) => {
  return getMarketData(state).activeSessionId;
};

export const selectTicker = (state: Store) => {
  if (state.activeMarket === 'coin') return state.coin.market;
  return state.kiwoom.stk_cd;
};

export const selectStatus = (state: Store) => {
  return getMarketData(state).status;
};

export const selectCurrentStage = (state: Store) => {
  return getMarketData(state).currentStage;
};

export const selectAnalyses = (state: Store) => {
  return getMarketData(state).analyses;
};

export const selectReasoningLog = (state: Store) => {
  return getMarketData(state).reasoningLog;
};

export const selectTradeProposal = (state: Store) => {
  return getMarketData(state).tradeProposal;
};

export const selectAwaitingApproval = (state: Store) => {
  return getMarketData(state).awaitingApproval;
};

export const selectActivePosition = (state: Store) => {
  return getMarketData(state).activePosition;
};

export const selectError = (state: Store) => {
  return getMarketData(state).error;
};

// Active session type for cross-market tracking
export interface ActiveSession {
  sessionId: string;
  ticker: string;
  displayName: string;
  marketType: MarketType;
  status: SessionStatus | 'idle';
  currentStage: string | null;
  reasoningLog: string[];
}

// Get ALL active sessions from ALL markets (for main dashboard)
export const selectAllActiveSessions = (state: Store): ActiveSession[] => {
  const sessions: ActiveSession[] = [];

  // Coin session
  if (state.coin.activeSessionId && state.coin.status !== 'idle') {
    sessions.push({
      sessionId: state.coin.activeSessionId,
      ticker: state.coin.market,
      displayName: state.coin.koreanName || state.coin.market.replace('KRW-', ''),
      marketType: 'coin',
      status: state.coin.status,
      currentStage: state.coin.currentStage,
      reasoningLog: state.coin.reasoningLog,
    });
  }

  // Kiwoom sessions (multi-session support)
  // Include ALL running/active sessions, not just the active one
  state.kiwoom.sessions.forEach((s) => {
    if (s.status !== 'completed' && s.status !== 'cancelled' && s.status !== 'error') {
      sessions.push({
        sessionId: s.sessionId,
        ticker: s.ticker,
        displayName: s.displayName,
        marketType: 'kiwoom',
        status: s.status,
        currentStage: s.currentStage,
        reasoningLog: s.reasoningLog,
      });
    }
  });

  return sessions;
};

// Chat Popup selector
export const selectChatPopup = (state: Store) => ({
  isOpen: state.chatPopupOpen,
  size: state.chatPopupSize,
  position: state.chatPopupPosition,
});

// Basket selector
export const selectBasket = (state: Store) => state.basket;
export const selectBasketItems = (state: Store) => state.basket.items;
export const selectBasketCount = (state: Store) => state.basket.items.length;
export const selectBasketMaxItems = (state: Store) => state.basket.maxItems;
export const selectIsBasketFull = (state: Store) => state.basket.items.length >= state.basket.maxItems;

// Recent completed analyses selector
export interface RecentAnalysisItem {
  sessionId: string;
  ticker: string;
  displayName: string;
  marketType: MarketType;
  timestamp: Date;
  status: SessionStatus | 'idle';
  tradeProposal: CoinTradeProposal | KRStockTradeProposal | null;
}

export const selectRecentCompletedAnalyses = (state: Store): RecentAnalysisItem[] => {
  const allHistory: RecentAnalysisItem[] = [];

  // Coin history - include completed, awaiting_approval, and cancelled
  state.coin.history.forEach((h) => {
    if (h.status === 'completed' || h.status === 'awaiting_approval' || h.status === 'cancelled') {
      allHistory.push({
        sessionId: h.sessionId,
        ticker: h.ticker,
        displayName: h.koreanName || h.ticker.replace('KRW-', ''),
        marketType: 'coin',
        timestamp: h.timestamp,
        status: h.status,
        tradeProposal: h.sessionId === state.coin.activeSessionId ? state.coin.tradeProposal : null,
      });
    }
  });

  // Kiwoom history - include completed, awaiting_approval, and cancelled
  state.kiwoom.history.forEach((h) => {
    if (h.status === 'completed' || h.status === 'awaiting_approval' || h.status === 'cancelled') {
      allHistory.push({
        sessionId: h.sessionId,
        ticker: h.stk_cd,
        displayName: h.stk_nm || h.stk_cd,
        marketType: 'kiwoom',
        timestamp: h.timestamp,
        status: h.status,
        tradeProposal: h.sessionId === state.kiwoom.activeSessionId ? state.kiwoom.tradeProposal : null,
      });
    }
  });

  // Sort by timestamp (most recent first) and take top 5
  return allHistory
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    .slice(0, 5);
};

// Export types
export type { TickerHistoryItem, CoinHistoryItem, KiwoomHistoryItem, MarketType, ChatPopupSize, Language };
export type { SessionData, TradingMode } from '@/types';
