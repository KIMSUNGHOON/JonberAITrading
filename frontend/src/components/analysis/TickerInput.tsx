/**
 * Ticker Input Component
 *
 * Input field for starting new analysis.
 */

import { useState } from 'react';
import { Search, Loader2 } from 'lucide-react';
import { useStore } from '@/store';
import { startAnalysis } from '@/api/client';
import { createStoreWebSocket, type TradingWebSocket } from '@/api/websocket';

// Store WebSocket reference
let activeWebSocket: TradingWebSocket | null = null;

export function TickerInput() {
  const [ticker, setTicker] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const status = useStore((state) => state.status);
  const startSession = useStore((state) => state.startSession);
  const addReasoningEntry = useStore((state) => state.addReasoningEntry);
  const setStatus = useStore((state) => state.setStatus);
  const setCurrentStage = useStore((state) => state.setCurrentStage);
  const setTradeProposal = useStore((state) => state.setTradeProposal);
  const setAwaitingApproval = useStore((state) => state.setAwaitingApproval);
  const setActivePosition = useStore((state) => state.setActivePosition);
  const setError = useStore((state) => state.setError);
  const addChatMessage = useStore((state) => state.addChatMessage);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const cleanTicker = ticker.trim().toUpperCase();
    if (!cleanTicker) return;

    setIsLoading(true);

    try {
      // Start analysis via API
      const response = await startAnalysis({ ticker: cleanTicker });

      // Update store
      startSession(response.session_id, cleanTicker);

      // Add system message
      addChatMessage({
        role: 'system',
        content: `Analysis started for ${cleanTicker}`,
      });

      // Disconnect existing WebSocket
      if (activeWebSocket) {
        activeWebSocket.disconnect();
      }

      // Connect WebSocket for real-time updates
      activeWebSocket = createStoreWebSocket(response.session_id, {
        addReasoningEntry,
        setStatus,
        setCurrentStage,
        setTradeProposal,
        setAwaitingApproval,
        setActivePosition,
        setError,
      });

      activeWebSocket.connect();

      setTicker('');
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to start analysis');
    } finally {
      setIsLoading(false);
    }
  };

  const isDisabled = status === 'running' || status === 'awaiting_approval';

  return (
    <form onSubmit={handleSubmit}>
      <div className="relative">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder={isDisabled ? 'Analysis in progress...' : 'Enter ticker (e.g., AAPL)'}
          disabled={isDisabled}
          className="input pr-12"
          maxLength={10}
        />
        <button
          type="submit"
          disabled={isDisabled || !ticker.trim() || isLoading}
          className="absolute right-2 top-1/2 -translate-y-1/2 p-2 text-gray-400 hover:text-white disabled:opacity-50"
        >
          {isLoading ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <Search className="w-5 h-5" />
          )}
        </button>
      </div>
    </form>
  );
}
