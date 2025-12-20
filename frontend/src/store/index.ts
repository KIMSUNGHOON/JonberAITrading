/**
 * Zustand Store for Agentic Trading
 *
 * Manages global application state with COMPLETE ISOLATION between:
 * - Stock analysis (stocks via yfinance)
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
import { devtools } from 'zustand/middleware';
import type {
  AnalysisSummary,
  ChatMessage,
  Position,
  SessionStatus,
  TradeProposal,
  ChartConfig,
  TimeFrame,
  CoinTradeProposal,
} from '@/types';

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
// Store Types
// -------------------------------------------

interface HistoryItem {
  ticker: string;  // Stock ticker or coin market code
  sessionId: string;
  timestamp: Date;
  status: SessionStatus | 'idle';
}

// Stock-specific history
interface StockHistoryItem extends HistoryItem {
  type: 'stock';
}

// Coin-specific history
interface CoinHistoryItem extends HistoryItem {
  type: 'coin';
  koreanName?: string;
}

// Combined ticker history (for backward compatibility)
type TickerHistoryItem = StockHistoryItem | CoinHistoryItem;

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

// Stock-specific state
interface StockState extends BaseAnalysisState {
  ticker: string;
  tradeProposal: TradeProposal | null;
  activePosition: Position | null;
  history: StockHistoryItem[];
}

// Coin-specific state
interface CoinState extends BaseAnalysisState {
  market: string;           // e.g., "KRW-BTC"
  koreanName: string | null;
  tradeProposal: CoinTradeProposal | null;
  activePosition: Position | null;
  history: CoinHistoryItem[];
}

interface ChatState {
  messages: ChatMessage[];
  isTyping: boolean;
}

type MarketType = 'stock' | 'coin';

interface UIState {
  // Market selection
  activeMarket: MarketType;

  // Panels
  showApprovalDialog: boolean;
  showChartPanel: boolean;
  showSettingsModal: boolean;
  isMobileMenuOpen: boolean;
  sidebarCollapsed: boolean;

  // Upbit API status
  upbitApiConfigured: boolean;

  // Chart config
  chartConfig: ChartConfig;
}

interface StockActions {
  // Stock session actions
  startStockSession: (sessionId: string, ticker: string) => void;
  setStockStatus: (status: SessionStatus) => void;
  setStockStage: (stage: string) => void;
  addStockReasoning: (entry: string) => void;
  setStockAnalyses: (analyses: AnalysisSummary[]) => void;
  addStockAnalysis: (analysis: AnalysisSummary) => void;
  setStockProposal: (proposal: TradeProposal | null) => void;
  setStockAwaitingApproval: (awaiting: boolean) => void;
  setStockPosition: (position: Position | null) => void;
  setStockError: (error: string | null) => void;
  resetStock: () => void;
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
}

interface ChatActions {
  addChatMessage: (message: Omit<ChatMessage, 'id' | 'timestamp'>) => void;
  setIsTyping: (typing: boolean) => void;
  clearChat: () => void;
}

interface UIActions {
  setActiveMarket: (market: MarketType) => void;
  setShowApprovalDialog: (show: boolean) => void;
  setShowChartPanel: (show: boolean) => void;
  setShowSettingsModal: (show: boolean) => void;
  setMobileMenuOpen: (open: boolean) => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
  setUpbitApiConfigured: (configured: boolean) => void;
  setChartTimeframe: (timeframe: TimeFrame) => void;
  toggleChartIndicator: (indicator: 'showSMA50' | 'showSMA200' | 'showVolume') => void;
}

// Legacy actions for backward compatibility
interface LegacyActions {
  startSession: (sessionId: string, ticker: string) => void;
  setStatus: (status: SessionStatus) => void;
  setCurrentStage: (stage: string) => void;
  addReasoningEntry: (entry: string) => void;
  setAnalyses: (analyses: AnalysisSummary[]) => void;
  addAnalysis: (analysis: AnalysisSummary) => void;
  setTradeProposal: (proposal: TradeProposal | null) => void;
  setAwaitingApproval: (awaiting: boolean) => void;
  setActivePosition: (position: Position | null) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

type Store = {
  stock: StockState;
  coin: CoinState;
} & ChatState & UIState & StockActions & CoinActions & ChatActions & UIActions & LegacyActions;

// -------------------------------------------
// Initial States
// -------------------------------------------

const initialStockState: StockState = {
  activeSessionId: null,
  ticker: '',
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

const initialChatState: ChatState = {
  messages: [],
  isTyping: false,
};

const initialUIState: UIState = {
  activeMarket: 'stock',
  showApprovalDialog: false,
  showChartPanel: true,
  showSettingsModal: false,
  isMobileMenuOpen: false,
  sidebarCollapsed: false,
  upbitApiConfigured: false,
  chartConfig: {
    timeframe: '1d',
    showSMA50: true,
    showSMA200: true,
    showVolume: true,
  },
};

// -------------------------------------------
// Store Implementation
// -------------------------------------------

export const useStore = create<Store>()(
  devtools(
    (set, get) => ({
      // Initial states
      stock: initialStockState,
      coin: initialCoinState,
      ...initialChatState,
      ...initialUIState,

      // -------------------------------------------
      // Stock Actions
      // -------------------------------------------
      startStockSession: (sessionId, ticker) =>
        set((state) => {
          const upperTicker = ticker.toUpperCase();
          const existingIndex = state.stock.history.findIndex(
            (h) => h.sessionId === sessionId
          );
          let newHistory = [...state.stock.history];
          if (existingIndex === -1) {
            newHistory = [
              {
                type: 'stock' as const,
                ticker: upperTicker,
                sessionId,
                timestamp: new Date(),
                status: 'running' as const,
              },
              ...state.stock.history,
            ].slice(0, 20);
          }
          return {
            stock: {
              ...initialStockState,
              activeSessionId: sessionId,
              ticker: upperTicker,
              status: 'running',
              history: newHistory,
            },
          };
        }),

      setStockStatus: (status) =>
        set((state) => {
          const newHistory = state.stock.history.map((h) =>
            h.sessionId === state.stock.activeSessionId ? { ...h, status } : h
          );
          return {
            stock: { ...state.stock, status, history: newHistory },
          };
        }),

      setStockStage: (stage) =>
        set((state) => ({
          stock: { ...state.stock, currentStage: stage },
        })),

      addStockReasoning: (entry) =>
        set((state) => ({
          stock: {
            ...state.stock,
            reasoningLog: [...state.stock.reasoningLog, entry],
          },
        })),

      setStockAnalyses: (analyses) =>
        set((state) => ({
          stock: { ...state.stock, analyses },
        })),

      addStockAnalysis: (analysis) =>
        set((state) => ({
          stock: {
            ...state.stock,
            analyses: [...state.stock.analyses, analysis],
          },
        })),

      setStockProposal: (proposal) =>
        set((state) => ({
          stock: { ...state.stock, tradeProposal: proposal },
          showApprovalDialog: proposal !== null,
        })),

      setStockAwaitingApproval: (awaiting) =>
        set((state) => ({
          stock: { ...state.stock, awaitingApproval: awaiting },
          showApprovalDialog: awaiting,
        })),

      setStockPosition: (position) =>
        set((state) => ({
          stock: { ...state.stock, activePosition: position },
        })),

      setStockError: (error) =>
        set((state) => ({
          stock: {
            ...state.stock,
            error,
            status: error ? 'error' : state.stock.status,
          },
        })),

      resetStock: () =>
        set((state) => ({
          stock: {
            ...initialStockState,
            history: state.stock.history,
          },
        })),

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
        set((state) => ({
          coin: { ...state.coin, tradeProposal: proposal },
          showApprovalDialog: proposal !== null,
        })),

      setCoinAwaitingApproval: (awaiting) =>
        set((state) => ({
          coin: { ...state.coin, awaitingApproval: awaiting },
          showApprovalDialog: awaiting,
        })),

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
      // UI Actions
      // -------------------------------------------
      setActiveMarket: (market) => set({ activeMarket: market }),

      setShowApprovalDialog: (show) => set({ showApprovalDialog: show }),

      setShowChartPanel: (show) => set({ showChartPanel: show }),

      setShowSettingsModal: (show) => set({ showSettingsModal: show }),

      setMobileMenuOpen: (open) => set({ isMobileMenuOpen: open }),

      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),

      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),

      setUpbitApiConfigured: (configured) => set({ upbitApiConfigured: configured }),

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

      // -------------------------------------------
      // Legacy Actions (for backward compatibility)
      // These delegate to stock or coin based on activeMarket
      // -------------------------------------------
      startSession: (sessionId, ticker) => {
        const market = get().activeMarket;
        if (market === 'stock') {
          get().startStockSession(sessionId, ticker);
        } else {
          get().startCoinSession(sessionId, ticker);
        }
      },

      setStatus: (status) => {
        const market = get().activeMarket;
        if (market === 'stock') {
          get().setStockStatus(status);
        } else {
          get().setCoinStatus(status);
        }
      },

      setCurrentStage: (stage) => {
        const market = get().activeMarket;
        if (market === 'stock') {
          get().setStockStage(stage);
        } else {
          get().setCoinStage(stage);
        }
      },

      addReasoningEntry: (entry) => {
        const market = get().activeMarket;
        if (market === 'stock') {
          get().addStockReasoning(entry);
        } else {
          get().addCoinReasoning(entry);
        }
      },

      setAnalyses: (analyses) => {
        const market = get().activeMarket;
        if (market === 'stock') {
          get().setStockAnalyses(analyses);
        } else {
          get().setCoinAnalyses(analyses);
        }
      },

      addAnalysis: (analysis) => {
        const market = get().activeMarket;
        if (market === 'stock') {
          get().addStockAnalysis(analysis);
        } else {
          get().addCoinAnalysis(analysis);
        }
      },

      setTradeProposal: (proposal) => {
        const market = get().activeMarket;
        if (market === 'stock') {
          get().setStockProposal(proposal);
        }
        // Coin proposals use different type, so skip
      },

      setAwaitingApproval: (awaiting) => {
        const market = get().activeMarket;
        if (market === 'stock') {
          get().setStockAwaitingApproval(awaiting);
        } else {
          get().setCoinAwaitingApproval(awaiting);
        }
      },

      setActivePosition: (position) => {
        const market = get().activeMarket;
        if (market === 'stock') {
          get().setStockPosition(position);
        } else {
          get().setCoinPosition(position);
        }
      },

      setError: (error) => {
        const market = get().activeMarket;
        if (market === 'stock') {
          get().setStockError(error);
        } else {
          get().setCoinError(error);
        }
      },

      reset: () => {
        const market = get().activeMarket;
        if (market === 'stock') {
          get().resetStock();
        } else {
          get().resetCoin();
        }
      },
    }),
    { name: 'agentic-trading-store' }
  )
);

// -------------------------------------------
// Selectors
// -------------------------------------------

// Get current market's session info
export const selectSession = (state: Store) => {
  const isStock = state.activeMarket === 'stock';
  const data = isStock ? state.stock : state.coin;
  return {
    sessionId: data.activeSessionId,
    ticker: isStock ? state.stock.ticker : state.coin.market,
    status: data.status,
  };
};

// Get current market's analysis state
export const selectAnalysis = (state: Store) => {
  const data = state.activeMarket === 'stock' ? state.stock : state.coin;
  return {
    analyses: data.analyses,
    currentStage: data.currentStage,
    reasoningLog: data.reasoningLog,
  };
};

// Get current market's proposal
export const selectProposal = (state: Store) => {
  const data = state.activeMarket === 'stock' ? state.stock : state.coin;
  return {
    proposal: data.tradeProposal,
    awaitingApproval: data.awaitingApproval,
  };
};

export const selectChat = (state: Store) => ({
  messages: state.messages,
  isTyping: state.isTyping,
});

export const selectChartConfig = (state: Store) => state.chartConfig;

// Get current market's history
export const selectTickerHistory = (state: Store): TickerHistoryItem[] => {
  const isStock = state.activeMarket === 'stock';
  return isStock ? state.stock.history : state.coin.history;
};

// Select stock-specific state
export const selectStock = (state: Store) => state.stock;

// Select coin-specific state
export const selectCoin = (state: Store) => state.coin;

// Legacy selectors for backward compatibility
export const selectActiveSessionId = (state: Store) => {
  return state.activeMarket === 'stock'
    ? state.stock.activeSessionId
    : state.coin.activeSessionId;
};

export const selectTicker = (state: Store) => {
  return state.activeMarket === 'stock'
    ? state.stock.ticker
    : state.coin.market;
};

export const selectStatus = (state: Store) => {
  return state.activeMarket === 'stock'
    ? state.stock.status
    : state.coin.status;
};

export const selectAnalyses = (state: Store) => {
  return state.activeMarket === 'stock'
    ? state.stock.analyses
    : state.coin.analyses;
};

export const selectReasoningLog = (state: Store) => {
  return state.activeMarket === 'stock'
    ? state.stock.reasoningLog
    : state.coin.reasoningLog;
};

export const selectTradeProposal = (state: Store) => {
  return state.activeMarket === 'stock'
    ? state.stock.tradeProposal
    : state.coin.tradeProposal;
};

export const selectAwaitingApproval = (state: Store) => {
  return state.activeMarket === 'stock'
    ? state.stock.awaitingApproval
    : state.coin.awaitingApproval;
};

export const selectActivePosition = (state: Store) => {
  return state.activeMarket === 'stock'
    ? state.stock.activePosition
    : state.coin.activePosition;
};

export const selectError = (state: Store) => {
  return state.activeMarket === 'stock'
    ? state.stock.error
    : state.coin.error;
};

// Export types
export type { TickerHistoryItem, StockHistoryItem, CoinHistoryItem, MarketType };
