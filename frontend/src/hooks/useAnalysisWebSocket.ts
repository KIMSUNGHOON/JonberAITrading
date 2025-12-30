/**
 * React Hook for Analysis WebSocket Connection
 *
 * Manages WebSocket connection for a specific analysis session.
 * Automatically connects/disconnects based on sessionId and
 * routes messages to the appropriate store actions.
 */

import { useEffect, useRef, useCallback } from 'react';
import { useStore, type MarketType } from '@/store';
import { wsManager, type WebSocketHandlers, type CompleteMessage } from '@/api/websocket';
import type { KRStockTradeProposal, SessionStatus } from '@/types';

interface UseAnalysisWebSocketOptions {
  /** Session ID to connect to */
  sessionId: string | null;
  /** Market type for proper store routing */
  marketType: MarketType;
  /** Whether to auto-connect when sessionId is provided */
  autoConnect?: boolean;
  /** Additional handlers */
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Event) => void;
}

interface UseAnalysisWebSocketResult {
  /** Whether the WebSocket is currently connected */
  isConnected: boolean;
  /** Manually connect to the WebSocket */
  connect: () => void;
  /** Manually disconnect from the WebSocket */
  disconnect: () => void;
  /** Request current status from the server */
  requestStatus: () => void;
}

/**
 * Hook to manage WebSocket connection for an analysis session.
 *
 * @example
 * ```tsx
 * const { isConnected, disconnect } = useAnalysisWebSocket({
 *   sessionId: 'abc-123',
 *   marketType: 'kiwoom',
 * });
 * ```
 */
export function useAnalysisWebSocket({
  sessionId,
  marketType,
  autoConnect = true,
  onConnect,
  onDisconnect,
  onError,
}: UseAnalysisWebSocketOptions): UseAnalysisWebSocketResult {
  const store = useStore();
  const isConnectedRef = useRef(false);

  // Get the appropriate store actions based on market type
  const getActions = useCallback(() => {
    if (marketType === 'kiwoom') {
      return {
        addReasoning: (entry: string) => {
          if (sessionId) {
            store.addKiwoomSessionReasoning(sessionId, entry);
          }
        },
        updateStatus: (status: SessionStatus) => {
          if (sessionId) {
            store.updateKiwoomSessionStatus(sessionId, status);
          }
        },
        updateStage: (stage: string) => {
          if (sessionId) {
            store.updateKiwoomSessionStage(sessionId, stage);
          }
        },
        setProposal: (proposal: KRStockTradeProposal | null) => {
          if (sessionId) {
            store.setKiwoomSessionProposal(sessionId, proposal);
          }
        },
        setAwaitingApproval: (awaiting: boolean) => {
          if (sessionId) {
            store.setKiwoomSessionAwaitingApproval(sessionId, awaiting);
          }
        },
        setError: (error: string | null) => {
          if (sessionId) {
            store.setKiwoomSessionError(sessionId, error);
          }
        },
        marketType: 'kiwoom' as const,
      };
    } else if (marketType === 'coin') {
      // Coin uses legacy single-session actions for now
      return {
        addReasoning: store.addCoinReasoning,
        updateStatus: store.setCoinStatus,
        updateStage: store.setCoinStage,
        setProposal: store.setCoinProposal,
        setAwaitingApproval: store.setCoinAwaitingApproval,
        setError: store.setCoinError,
        marketType: 'coin' as const,
      };
    } else {
      // Stock uses legacy single-session actions for now
      return {
        addReasoning: store.addStockReasoning,
        updateStatus: store.setStockStatus,
        updateStage: store.setStockStage,
        setProposal: store.setStockProposal,
        setAwaitingApproval: store.setStockAwaitingApproval,
        setError: store.setStockError,
        marketType: 'stock' as const,
      };
    }
  }, [marketType, sessionId, store]);

  // Create handlers that route to store
  const createHandlers = useCallback((): WebSocketHandlers => {
    const actions = getActions();

    return {
      onReasoning: (entry) => {
        actions.addReasoning(entry);
      },
      onStatus: (data) => {
        actions.updateStatus(data.status as SessionStatus);
        actions.updateStage(data.stage);
        actions.setAwaitingApproval(data.awaiting_approval);
      },
      onProposal: (data) => {
        // Convert proposal data to the appropriate type based on market type
        // Use display_name from backend if available, otherwise fallback to ticker
        if (actions.marketType === 'kiwoom') {
          const proposal: KRStockTradeProposal = {
            id: data.id,
            stk_cd: data.ticker,
            stk_nm: data.display_name || data.ticker || null,  // Use display_name from backend
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
          (actions.setProposal as (p: KRStockTradeProposal | null) => void)(proposal);
        } else if (actions.marketType === 'coin') {
          // For coin, convert to CoinTradeProposal format
          const proposal = {
            id: data.id,
            market: data.ticker,
            korean_name: data.display_name || null,  // Use display_name from backend
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
          (actions.setProposal as (p: any) => void)(proposal);
        } else {
          // For stock, use TradeProposal format
          const proposal = {
            id: data.id,
            ticker: data.ticker,
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
          (actions.setProposal as (p: any) => void)(proposal);
        }
      },
      onComplete: (data: CompleteMessage['data']) => {
        // Debug logging to trace analysis results
        console.log('[WebSocket] Complete message received:', {
          sessionId,
          status: data.status,
          hasAnalysisResults: !!data.analysis_results,
          analysisResultsKeys: data.analysis_results ? Object.keys(data.analysis_results) : [],
          hasProposal: !!data.trade_proposal,
          hasReasoningSummary: !!data.reasoning_summary,
        });

        if (data.error) {
          actions.setError(data.error);
        }
        actions.updateStatus(data.status as SessionStatus);

        // Save detailed analysis results for Kiwoom sessions
        if (sessionId && actions.marketType === 'kiwoom' && data.status === 'completed') {
          console.log('[WebSocket] Calling completeKiwoomSession with analysis_results:', data.analysis_results);
          store.completeKiwoomSession(sessionId, {
            analysisResults: data.analysis_results || null,
            tradeProposal: data.trade_proposal ? {
              id: data.trade_proposal.id,
              stk_cd: data.trade_proposal.ticker,
              stk_nm: null,
              action: data.trade_proposal.action as 'BUY' | 'SELL' | 'HOLD',
              quantity: data.trade_proposal.quantity,
              entry_price: data.trade_proposal.entry_price,
              stop_loss: data.trade_proposal.stop_loss,
              take_profit: data.trade_proposal.take_profit,
              risk_score: data.trade_proposal.risk_score,
              position_size_pct: 0,
              rationale: data.trade_proposal.rationale,
              bull_case: data.trade_proposal.bull_case || '',
              bear_case: data.trade_proposal.bear_case || '',
              created_at: new Date().toISOString(),
            } : null,
            reasoningSummary: data.reasoning_summary ?? undefined,
            completedAt: data.completed_at ? new Date(data.completed_at) : new Date(),
          });
        }
      },
      onConnect: () => {
        isConnectedRef.current = true;
        onConnect?.();
      },
      onDisconnect: () => {
        isConnectedRef.current = false;
        onDisconnect?.();
      },
      onError: (error) => {
        actions.setError('WebSocket connection error');
        onError?.(error);
      },
    };
  }, [getActions, onConnect, onDisconnect, onError]);

  // Connect to WebSocket
  const connect = useCallback(() => {
    if (!sessionId) return;
    const handlers = createHandlers();
    wsManager.connect(sessionId, handlers);
  }, [sessionId, createHandlers]);

  // Disconnect from WebSocket
  const disconnect = useCallback(() => {
    if (!sessionId) return;
    wsManager.disconnect(sessionId);
    isConnectedRef.current = false;
  }, [sessionId]);

  // Request status
  const requestStatus = useCallback(() => {
    if (!sessionId) return;
    const ws = wsManager.get(sessionId);
    ws?.requestStatus();
  }, [sessionId]);

  // Auto-connect/disconnect effect
  useEffect(() => {
    if (!sessionId || !autoConnect) return;

    // Connect when sessionId changes
    connect();

    // Cleanup on unmount or sessionId change
    return () => {
      // Only disconnect if we're the ones who connected
      // This prevents disconnecting during re-renders
      if (wsManager.has(sessionId)) {
        disconnect();
      }
    };
  }, [sessionId, autoConnect, connect, disconnect]);

  return {
    isConnected: sessionId ? wsManager.isConnected(sessionId) : false,
    connect,
    disconnect,
    requestStatus,
  };
}

/**
 * Hook to connect multiple sessions at once.
 * Useful for bulk analysis from basket.
 */
export function useMultipleAnalysisWebSockets(
  sessions: Array<{ sessionId: string; marketType: MarketType }>
) {
  const store = useStore();

  // Connect all sessions
  const connectAll = useCallback(() => {
    for (const { sessionId, marketType } of sessions) {
      if (marketType === 'kiwoom') {
        const handlers: WebSocketHandlers = {
          onReasoning: (entry) => store.addKiwoomSessionReasoning(sessionId, entry),
          onStatus: (data) => {
            store.updateKiwoomSessionStatus(sessionId, data.status as SessionStatus);
            store.updateKiwoomSessionStage(sessionId, data.stage);
            store.setKiwoomSessionAwaitingApproval(sessionId, data.awaiting_approval);
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
            store.setKiwoomSessionProposal(sessionId, proposal);
          },
          onComplete: (data: CompleteMessage['data']) => {
            if (data.error) {
              store.setKiwoomSessionError(sessionId, data.error);
            }
            store.updateKiwoomSessionStatus(sessionId, data.status as SessionStatus);

            // Save detailed analysis results
            if (data.status === 'completed') {
              store.completeKiwoomSession(sessionId, {
                analysisResults: data.analysis_results || null,
                tradeProposal: data.trade_proposal ? {
                  id: data.trade_proposal.id,
                  stk_cd: data.trade_proposal.ticker,
                  stk_nm: null,
                  action: data.trade_proposal.action as 'BUY' | 'SELL' | 'HOLD',
                  quantity: data.trade_proposal.quantity,
                  entry_price: data.trade_proposal.entry_price,
                  stop_loss: data.trade_proposal.stop_loss,
                  take_profit: data.trade_proposal.take_profit,
                  risk_score: data.trade_proposal.risk_score,
                  position_size_pct: 0,
                  rationale: data.trade_proposal.rationale,
                  bull_case: data.trade_proposal.bull_case || '',
                  bear_case: data.trade_proposal.bear_case || '',
                  created_at: new Date().toISOString(),
                } : null,
                reasoningSummary: data.reasoning_summary ?? undefined,
                completedAt: data.completed_at ? new Date(data.completed_at) : new Date(),
              });
            }
          },
          onError: () => {
            store.setKiwoomSessionError(sessionId, 'WebSocket connection error');
          },
        };
        wsManager.connect(sessionId, handlers);
      }
      // Add coin and stock handlers similarly if needed
    }
  }, [sessions, store]);

  // Disconnect all sessions
  const disconnectAll = useCallback(() => {
    for (const { sessionId } of sessions) {
      wsManager.disconnect(sessionId);
    }
  }, [sessions]);

  // Get connection status for all sessions
  const getConnectionStatus = useCallback(() => {
    return sessions.map(({ sessionId }) => ({
      sessionId,
      isConnected: wsManager.isConnected(sessionId),
    }));
  }, [sessions]);

  return {
    connectAll,
    disconnectAll,
    getConnectionStatus,
    activeCount: wsManager.getActiveCount(),
    availableSlots: wsManager.getAvailableSlots(),
  };
}
