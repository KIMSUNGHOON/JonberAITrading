/**
 * Coin Ticker Input Component
 *
 * Input field with autocomplete for starting coin analysis.
 * Supports Korean/English name search and market code input.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { Search, Loader2, Bitcoin } from 'lucide-react';
import { useStore } from '@/store';
import { searchCoinMarkets, startCoinAnalysis } from '@/api/client';
import { createStoreWebSocket, type TradingWebSocket } from '@/api/websocket';
import type { CoinMarketInfo } from '@/types';

// Store WebSocket reference for coin sessions
let activeCoinWebSocket: TradingWebSocket | null = null;

// Popular coins for quick selection
const POPULAR_COINS = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-DOGE'];

interface CoinSuggestion extends CoinMarketInfo {
  isPopular?: boolean;
}

export function CoinTickerInput() {
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<CoinSuggestion[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Use coin-specific state and actions
  const status = useStore((state) => state.coin.status);
  const startCoinSession = useStore((state) => state.startCoinSession);
  const addCoinReasoning = useStore((state) => state.addCoinReasoning);
  const setCoinStatus = useStore((state) => state.setCoinStatus);
  const setCoinStage = useStore((state) => state.setCoinStage);
  const setCoinProposal = useStore((state) => state.setCoinProposal);
  const setCoinAwaitingApproval = useStore((state) => state.setCoinAwaitingApproval);
  const setCoinPosition = useStore((state) => state.setCoinPosition);
  const setCoinError = useStore((state) => state.setCoinError);
  const addChatMessage = useStore((state) => state.addChatMessage);

  const isDisabled = status === 'running' || status === 'awaiting_approval';

  // Search markets with debounce
  const searchMarkets = useCallback(async (searchQuery: string) => {
    if (searchQuery.length < 1) {
      setSuggestions([]);
      return;
    }

    setIsSearching(true);
    try {
      const result = await searchCoinMarkets(searchQuery, 8);
      setSuggestions(result.markets);
      setSelectedIndex(-1);
    } catch (error) {
      console.error('Failed to search markets:', error);
      setSuggestions([]);
    } finally {
      setIsSearching(false);
    }
  }, []);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (query.trim()) {
        searchMarkets(query.trim());
      } else {
        setSuggestions([]);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [query, searchMarkets]);

  // Handle click outside to close dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(event.target as Node)
      ) {
        setShowDropdown(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleStartAnalysis = async (market: string, koreanName?: string) => {
    setIsLoading(true);
    setShowDropdown(false);

    try {
      // Start coin analysis via API
      const response = await startCoinAnalysis({ market });

      // Update store with coin-specific session
      startCoinSession(response.session_id, market, koreanName);

      // Add system message
      addChatMessage({
        role: 'system',
        content: `Coin analysis started for ${koreanName || market}`,
      });

      // Disconnect existing WebSocket
      if (activeCoinWebSocket) {
        activeCoinWebSocket.disconnect();
      }

      // Connect WebSocket for real-time updates (using coin-specific handlers)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      activeCoinWebSocket = createStoreWebSocket(response.session_id, {
        addReasoningEntry: addCoinReasoning,
        setStatus: setCoinStatus,
        setCurrentStage: setCoinStage,
        setTradeProposal: setCoinProposal as any,
        setAwaitingApproval: setCoinAwaitingApproval,
        setActivePosition: setCoinPosition,
        setError: setCoinError,
      });

      activeCoinWebSocket.connect();

      setQuery('');
    } catch (error) {
      setCoinError(
        error instanceof Error ? error.message : 'Failed to start coin analysis'
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // If there's a selected suggestion, use it
    if (selectedIndex >= 0 && suggestions[selectedIndex]) {
      const selected = suggestions[selectedIndex];
      handleStartAnalysis(selected.market, selected.korean_name);
      return;
    }

    // If query looks like a market code (e.g., KRW-BTC), use it directly
    const cleanQuery = query.trim().toUpperCase();
    if (/^[A-Z]{2,5}-[A-Z0-9]{2,10}$/.test(cleanQuery)) {
      handleStartAnalysis(cleanQuery);
      return;
    }

    // Otherwise try to find a match
    if (suggestions.length > 0) {
      const first = suggestions[0];
      handleStartAnalysis(first.market, first.korean_name);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!showDropdown || suggestions.length === 0) return;

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex((prev) =>
          prev < suggestions.length - 1 ? prev + 1 : prev
        );
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex((prev) => (prev > 0 ? prev - 1 : -1));
        break;
      case 'Escape':
        setShowDropdown(false);
        setSelectedIndex(-1);
        break;
    }
  };

  const handleSuggestionClick = (suggestion: CoinSuggestion) => {
    handleStartAnalysis(suggestion.market, suggestion.korean_name);
  };

  return (
    <div className="relative">
      <form onSubmit={handleSubmit}>
        <div className="relative">
          <div className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
            <Bitcoin className="w-4 h-4" />
          </div>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setShowDropdown(true);
            }}
            onFocus={() => setShowDropdown(true)}
            onKeyDown={handleKeyDown}
            placeholder={
              isDisabled
                ? 'Analysis in progress...'
                : 'Search coin (e.g., 비트코인, BTC)'
            }
            disabled={isDisabled}
            className="input pl-10 pr-12"
            maxLength={20}
          />
          <button
            type="submit"
            disabled={isDisabled || !query.trim() || isLoading}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-2 text-gray-400 hover:text-white disabled:opacity-50"
          >
            {isLoading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : isSearching ? (
              <Loader2 className="w-4 h-4 animate-spin opacity-50" />
            ) : (
              <Search className="w-5 h-5" />
            )}
          </button>
        </div>
      </form>

      {/* Dropdown */}
      {showDropdown && !isDisabled && (
        <div
          ref={dropdownRef}
          className="absolute z-50 w-full mt-1 bg-surface-light border border-border rounded-lg shadow-lg max-h-64 overflow-y-auto"
        >
          {/* Show suggestions if query exists */}
          {query.trim() && suggestions.length > 0 && (
            <div className="py-1">
              {suggestions.map((suggestion, index) => (
                <button
                  key={suggestion.market}
                  type="button"
                  onClick={() => handleSuggestionClick(suggestion)}
                  className={`w-full px-3 py-2 text-left flex items-center gap-3 hover:bg-surface transition-colors ${
                    index === selectedIndex ? 'bg-surface' : ''
                  }`}
                >
                  <Bitcoin className="w-4 h-4 text-yellow-500 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm truncate">
                        {suggestion.korean_name}
                      </span>
                      <span className="text-xs text-gray-500">
                        {suggestion.english_name}
                      </span>
                    </div>
                    <div className="text-xs text-gray-400">
                      {suggestion.market}
                    </div>
                  </div>
                  {suggestion.market_warning && (
                    <span className="text-xs text-yellow-500 bg-yellow-500/10 px-1.5 py-0.5 rounded">
                      Warning
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}

          {/* No results message */}
          {query.trim() && suggestions.length === 0 && !isSearching && (
            <div className="px-3 py-4 text-center text-gray-500 text-sm">
              No coins found for "{query}"
            </div>
          )}

          {/* Popular coins when input is empty */}
          {!query.trim() && (
            <div className="py-1">
              <div className="px-3 py-1.5 text-xs text-gray-500 uppercase tracking-wider">
                Popular Coins
              </div>
              {POPULAR_COINS.map((market) => (
                <button
                  key={market}
                  type="button"
                  onClick={() => handleStartAnalysis(market)}
                  className="w-full px-3 py-2 text-left flex items-center gap-3 hover:bg-surface transition-colors"
                >
                  <Bitcoin className="w-4 h-4 text-yellow-500" />
                  <span className="font-medium text-sm">{market}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Quick select popular coins */}
      {!isDisabled && !showDropdown && (
        <div className="flex flex-wrap gap-1 mt-2">
          {POPULAR_COINS.slice(0, 3).map((market) => (
            <button
              key={market}
              type="button"
              onClick={() => handleStartAnalysis(market)}
              className="text-xs px-2 py-1 bg-surface hover:bg-surface-light rounded text-gray-400 hover:text-gray-200 transition-colors"
            >
              {market.replace('KRW-', '')}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
