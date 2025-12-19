/**
 * Zustand Store for Agentic Trading
 *
 * Manages global application state including:
 * - Active session and analysis status
 * - Chat messages (hybrid UI)
 * - Trade proposals and positions
 * - UI state (modals, panels)
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
} from '@/types';

// -------------------------------------------
// Store Types
// -------------------------------------------

interface TickerHistoryItem {
  ticker: string;
  sessionId: string;
  timestamp: Date;
  status: SessionStatus | 'idle';
}

interface AnalysisState {
  // Session
  activeSessionId: string | null;
  ticker: string;
  status: SessionStatus | 'idle';

  // Ticker history
  tickerHistory: TickerHistoryItem[];

  // Analysis results
  analyses: AnalysisSummary[];
  currentStage: string | null;

  // Reasoning log
  reasoningLog: string[];

  // Trade proposal
  tradeProposal: TradeProposal | null;
  awaitingApproval: boolean;

  // Position
  activePosition: Position | null;

  // Error
  error: string | null;
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
  isMobileMenuOpen: boolean;

  // Chart config
  chartConfig: ChartConfig;
}

interface Actions {
  // Session actions
  startSession: (sessionId: string, ticker: string) => void;
  setStatus: (status: SessionStatus) => void;
  setCurrentStage: (stage: string) => void;

  // Analysis actions
  addReasoningEntry: (entry: string) => void;
  setAnalyses: (analyses: AnalysisSummary[]) => void;
  addAnalysis: (analysis: AnalysisSummary) => void;

  // Proposal actions
  setTradeProposal: (proposal: TradeProposal | null) => void;
  setAwaitingApproval: (awaiting: boolean) => void;

  // Position actions
  setActivePosition: (position: Position | null) => void;

  // Chat actions
  addChatMessage: (message: Omit<ChatMessage, 'id' | 'timestamp'>) => void;
  setIsTyping: (typing: boolean) => void;
  clearChat: () => void;

  // UI actions
  setActiveMarket: (market: MarketType) => void;
  setShowApprovalDialog: (show: boolean) => void;
  setShowChartPanel: (show: boolean) => void;
  setMobileMenuOpen: (open: boolean) => void;
  setChartTimeframe: (timeframe: TimeFrame) => void;
  toggleChartIndicator: (indicator: 'showSMA50' | 'showSMA200' | 'showVolume') => void;

  // Error handling
  setError: (error: string | null) => void;

  // Reset
  reset: () => void;
}

type Store = AnalysisState & ChatState & UIState & Actions;

// -------------------------------------------
// Initial State
// -------------------------------------------

const initialAnalysisState: AnalysisState = {
  activeSessionId: null,
  ticker: '',
  status: 'idle',
  tickerHistory: [],
  analyses: [],
  currentStage: null,
  reasoningLog: [],
  tradeProposal: null,
  awaitingApproval: false,
  activePosition: null,
  error: null,
};

const initialChatState: ChatState = {
  messages: [],
  isTyping: false,
};

const initialUIState: UIState = {
  activeMarket: 'stock',
  showApprovalDialog: false,
  showChartPanel: true,
  isMobileMenuOpen: false,
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
      // Initial state
      ...initialAnalysisState,
      ...initialChatState,
      ...initialUIState,

      // Session actions
      startSession: (sessionId, ticker) =>
        set((state) => {
          const upperTicker = ticker.toUpperCase();
          // Add to history (avoid duplicates for same session)
          const existingIndex = state.tickerHistory.findIndex(
            (h) => h.sessionId === sessionId
          );
          let newHistory = [...state.tickerHistory];
          if (existingIndex === -1) {
            // Add new entry at the beginning
            newHistory = [
              {
                ticker: upperTicker,
                sessionId,
                timestamp: new Date(),
                status: 'running' as const,
              },
              ...state.tickerHistory,
            ].slice(0, 20); // Keep last 20 entries
          }
          return {
            activeSessionId: sessionId,
            ticker: upperTicker,
            status: 'running',
            tickerHistory: newHistory,
            analyses: [],
            reasoningLog: [],
            tradeProposal: null,
            awaitingApproval: false,
            error: null,
          };
        }),

      setStatus: (status) =>
        set((state) => {
          // Update history status for current session
          const newHistory = state.tickerHistory.map((h) =>
            h.sessionId === state.activeSessionId ? { ...h, status } : h
          );
          return { status, tickerHistory: newHistory };
        }),

      setCurrentStage: (stage) => set({ currentStage: stage }),

      // Analysis actions
      addReasoningEntry: (entry) =>
        set((state) => ({
          reasoningLog: [...state.reasoningLog, entry],
        })),

      setAnalyses: (analyses) => set({ analyses }),

      addAnalysis: (analysis) =>
        set((state) => ({
          analyses: [...state.analyses, analysis],
        })),

      // Proposal actions
      setTradeProposal: (proposal) =>
        set({
          tradeProposal: proposal,
          showApprovalDialog: proposal !== null,
        }),

      setAwaitingApproval: (awaiting) =>
        set({
          awaitingApproval: awaiting,
          showApprovalDialog: awaiting,
        }),

      // Position actions
      setActivePosition: (position) => set({ activePosition: position }),

      // Chat actions
      addChatMessage: (message) =>
        set((state) => ({
          messages: [
            ...state.messages,
            {
              ...message,
              id: crypto.randomUUID(),
              timestamp: new Date(),
            },
          ],
        })),

      setIsTyping: (typing) => set({ isTyping: typing }),

      clearChat: () => set({ messages: [] }),

      // UI actions
      setActiveMarket: (market) => set({ activeMarket: market }),

      setShowApprovalDialog: (show) => set({ showApprovalDialog: show }),

      setShowChartPanel: (show) => set({ showChartPanel: show }),

      setMobileMenuOpen: (open) => set({ isMobileMenuOpen: open }),

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

      // Error handling
      setError: (error) => set({ error, status: error ? 'error' : get().status }),

      // Reset
      reset: () =>
        set((state) => ({
          ...initialAnalysisState,
          ...initialChatState,
          // Keep ticker history and UI state
          tickerHistory: state.tickerHistory,
        })),
    }),
    { name: 'agentic-trading-store' }
  )
);

// -------------------------------------------
// Selectors (for performance)
// -------------------------------------------

export const selectSession = (state: Store) => ({
  sessionId: state.activeSessionId,
  ticker: state.ticker,
  status: state.status,
});

export const selectAnalysis = (state: Store) => ({
  analyses: state.analyses,
  currentStage: state.currentStage,
  reasoningLog: state.reasoningLog,
});

export const selectProposal = (state: Store) => ({
  proposal: state.tradeProposal,
  awaitingApproval: state.awaitingApproval,
});

export const selectChat = (state: Store) => ({
  messages: state.messages,
  isTyping: state.isTyping,
});

export const selectChartConfig = (state: Store) => state.chartConfig;

export const selectTickerHistory = (state: Store) => state.tickerHistory;

// Export types
export type { TickerHistoryItem, MarketType };
