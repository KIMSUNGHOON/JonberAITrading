/**
 * Kiwoom Ticker Input Component
 *
 * Input field with autocomplete for starting Korean stock analysis.
 * Supports Korean stock name search and stock code input.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { Search, Loader2, Building2, AlertTriangle, Clock } from 'lucide-react';
import { useStore } from '@/store';
import { searchKRStocks, startKRStockAnalysis } from '@/api/client';
import { createStoreWebSocket, type TradingWebSocket } from '@/api/websocket';
import type { KRStockInfo } from '@/types';
import { getMarketStatus, isTradingAllowed, type MarketStatus } from '@/utils/marketHours';

// Store WebSocket reference for Kiwoom sessions
let activeKiwoomWebSocket: TradingWebSocket | null = null;

// Popular Korean stocks for quick selection
const POPULAR_STOCKS = [
  { stk_cd: '005930', stk_nm: '삼성전자' },
  { stk_cd: '000660', stk_nm: 'SK하이닉스' },
  { stk_cd: '035420', stk_nm: 'NAVER' },
  { stk_cd: '035720', stk_nm: '카카오' },
  { stk_cd: '051910', stk_nm: 'LG화학' },
];

interface StockSuggestion extends KRStockInfo {
  isPopular?: boolean;
}

export function KiwoomTickerInput() {
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<StockSuggestion[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [marketStatus, setMarketStatus] = useState<MarketStatus | null>(null);
  const [tradingWarning, setTradingWarning] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Update market status periodically
  useEffect(() => {
    const updateMarketStatus = () => {
      const status = getMarketStatus('kiwoom');
      setMarketStatus(status);
      const tradingCheck = isTradingAllowed('kiwoom');
      setTradingWarning(tradingCheck.warning || null);
    };

    updateMarketStatus();
    const interval = setInterval(updateMarketStatus, 60000); // Update every minute
    return () => clearInterval(interval);
  }, []);

  // Use kiwoom-specific state and actions
  const kiwoomSessions = useStore((state) => state.kiwoom.sessions);
  const startKiwoomSession = useStore((state) => state.startKiwoomSession);
  const addKiwoomReasoning = useStore((state) => state.addKiwoomReasoning);
  const setKiwoomStatus = useStore((state) => state.setKiwoomStatus);
  const setKiwoomStage = useStore((state) => state.setKiwoomStage);
  const setKiwoomProposal = useStore((state) => state.setKiwoomProposal);
  const setKiwoomAwaitingApproval = useStore((state) => state.setKiwoomAwaitingApproval);
  const setKiwoomPosition = useStore((state) => state.setKiwoomPosition);
  const setKiwoomError = useStore((state) => state.setKiwoomError);
  const completeKiwoomSession = useStore((state) => state.completeKiwoomSession);
  const addChatMessage = useStore((state) => state.addChatMessage);

  // Count active sessions (running or awaiting approval)
  const activeSessions = kiwoomSessions.filter(
    (s) => s.status === 'running' || s.status === 'awaiting_approval'
  );
  const MAX_CONCURRENT_SESSIONS = 3;
  const isDisabled = activeSessions.length >= MAX_CONCURRENT_SESSIONS;

  // Search stocks with debounce
  const searchStocks = useCallback(async (searchQuery: string) => {
    if (searchQuery.length < 1) {
      setSuggestions([]);
      return;
    }

    setIsSearching(true);
    try {
      const result = await searchKRStocks(searchQuery, 8);
      setSuggestions(result.stocks);
      setSelectedIndex(-1);
    } catch (error) {
      console.error('Failed to search stocks:', error);
      setSuggestions([]);
    } finally {
      setIsSearching(false);
    }
  }, []);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (query.trim()) {
        searchStocks(query.trim());
      } else {
        setSuggestions([]);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [query, searchStocks]);

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

  const handleStartAnalysis = async (stk_cd: string, stk_nm?: string) => {
    setIsLoading(true);
    setShowDropdown(false);

    try {
      // Start Korean stock analysis via API
      const response = await startKRStockAnalysis({ stk_cd });

      // Update store with kiwoom-specific session
      startKiwoomSession(response.session_id, stk_cd, stk_nm);

      // Add system message
      addChatMessage({
        role: 'system',
        content: `한국주식 분석 시작: ${stk_nm || stk_cd}`,
      });

      // Disconnect existing WebSocket
      if (activeKiwoomWebSocket) {
        activeKiwoomWebSocket.disconnect();
      }

      // Connect WebSocket for real-time updates (using kiwoom-specific handlers)
      activeKiwoomWebSocket = createStoreWebSocket(
        response.session_id,
        {
          addReasoningEntry: addKiwoomReasoning,
          setStatus: setKiwoomStatus,
          setCurrentStage: setKiwoomStage,
          setTradeProposal: setKiwoomProposal,
          setAwaitingApproval: setKiwoomAwaitingApproval,
          setActivePosition: setKiwoomPosition,
          setError: setKiwoomError,
          completeKiwoomSession, // Pass for saving analysis results
        },
        'kiwoom' // Market type for correct proposal format (₩ currency)
      );

      activeKiwoomWebSocket.connect();

      setQuery('');
    } catch (error) {
      setKiwoomError(
        error instanceof Error ? error.message : 'Failed to start Korean stock analysis'
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
      handleStartAnalysis(selected.stk_cd, selected.stk_nm);
      return;
    }

    // If query looks like a stock code (6 digits), use it directly
    const cleanQuery = query.trim();
    if (/^\d{6}$/.test(cleanQuery)) {
      handleStartAnalysis(cleanQuery);
      return;
    }

    // Otherwise try to find a match
    if (suggestions.length > 0) {
      const first = suggestions[0];
      handleStartAnalysis(first.stk_cd, first.stk_nm);
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

  const handleSuggestionClick = (suggestion: StockSuggestion) => {
    handleStartAnalysis(suggestion.stk_cd, suggestion.stk_nm);
  };

  // Format price with Korean locale
  const formatPrice = (price: number) => {
    return new Intl.NumberFormat('ko-KR').format(price);
  };

  // Format change rate with color indicator
  const getChangeClass = (rate: number) => {
    if (rate > 0) return 'text-red-500'; // Korean market: red = up
    if (rate < 0) return 'text-blue-500'; // Korean market: blue = down
    return 'text-gray-500';
  };

  // Check if market is open for trading
  const isMarketClosed = marketStatus?.status === 'closed';

  return (
    <div className="relative">
      {/* Market Status Warning Banner */}
      {tradingWarning && (
        <div
          className={`mb-2 px-3 py-2 rounded-lg flex items-center gap-2 text-sm ${
            isMarketClosed
              ? 'bg-red-500/10 border border-red-500/30 text-red-400'
              : 'bg-yellow-500/10 border border-yellow-500/30 text-yellow-400'
          }`}
        >
          {isMarketClosed ? (
            <Clock className="w-4 h-4 flex-shrink-0" />
          ) : (
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          )}
          <span className="flex-1">{tradingWarning}</span>
          {marketStatus && (
            <span className="text-xs opacity-75">
              ({marketStatus.openTime}-{marketStatus.closeTime} {marketStatus.timezone})
            </span>
          )}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="relative">
          <div className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
            <Building2 className="w-4 h-4" />
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
                ? `동시 분석 한도 초과 (${activeSessions.length}/${MAX_CONCURRENT_SESSIONS})`
                : activeSessions.length > 0
                ? `종목 추가 검색 (${activeSessions.length}/${MAX_CONCURRENT_SESSIONS} 분석 중)`
                : '종목 검색 (예: 삼성전자, 005930)'
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
                  key={suggestion.stk_cd}
                  type="button"
                  onClick={() => handleSuggestionClick(suggestion)}
                  className={`w-full px-3 py-2 text-left flex items-center gap-3 hover:bg-surface transition-colors ${
                    index === selectedIndex ? 'bg-surface' : ''
                  }`}
                >
                  <Building2 className="w-4 h-4 text-blue-500 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm truncate">
                        {suggestion.stk_nm}
                      </span>
                      <span className="text-xs text-gray-500">
                        {suggestion.stk_cd}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="text-gray-300">
                        {formatPrice(suggestion.cur_prc)}원
                      </span>
                      <span className={getChangeClass(suggestion.prdy_ctrt)}>
                        {suggestion.prdy_ctrt > 0 ? '+' : ''}
                        {suggestion.prdy_ctrt.toFixed(2)}%
                      </span>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* No results message */}
          {query.trim() && suggestions.length === 0 && !isSearching && (
            <div className="px-3 py-4 text-center text-gray-500 text-sm">
              "{query}" 검색 결과 없음
            </div>
          )}

          {/* Popular stocks when input is empty */}
          {!query.trim() && (
            <div className="py-1">
              <div className="px-3 py-1.5 text-xs text-gray-500 uppercase tracking-wider">
                인기 종목
              </div>
              {POPULAR_STOCKS.map((stock) => (
                <button
                  key={stock.stk_cd}
                  type="button"
                  onClick={() => handleStartAnalysis(stock.stk_cd, stock.stk_nm)}
                  className="w-full px-3 py-2 text-left flex items-center gap-3 hover:bg-surface transition-colors"
                >
                  <Building2 className="w-4 h-4 text-blue-500" />
                  <span className="font-medium text-sm">{stock.stk_nm}</span>
                  <span className="text-xs text-gray-500">{stock.stk_cd}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Quick select popular stocks */}
      {!isDisabled && !showDropdown && (
        <div className="flex flex-wrap items-center gap-1 mt-2">
          {POPULAR_STOCKS.slice(0, 4).map((stock) => (
            <button
              key={stock.stk_cd}
              type="button"
              onClick={() => handleStartAnalysis(stock.stk_cd, stock.stk_nm)}
              className="text-xs px-2 py-1 bg-surface hover:bg-surface-light rounded text-gray-400 hover:text-gray-200 transition-colors"
            >
              {stock.stk_nm}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
