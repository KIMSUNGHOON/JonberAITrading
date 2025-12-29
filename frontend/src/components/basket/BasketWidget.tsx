/**
 * BasketWidget Component
 *
 * Watchlist-style widget for tracking multiple stocks/coins.
 * - Add/remove items to basket
 * - Real-time price updates (when API configured)
 * - API configuration status handling
 * - Start analysis from basket
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  ShoppingBasket,
  Plus,
  Trash2,
  TrendingUp,
  TrendingDown,
  Minus,
  RefreshCw,
  AlertCircle,
  Settings,
  Play,
  PlayCircle,
  X,
  Bitcoin,
  Building2,
  LineChart,
  Loader2,
  ChevronRight,
} from 'lucide-react';
import { useShallow } from 'zustand/shallow';
import {
  useStore,
  selectBasketItems,
  selectIsBasketFull,
  selectKiwoomAvailableSlots,
  type BasketItem,
  type MarketType,
  type SessionData,
} from '@/store';
import {
  getCoinTickers,
  startKRStockAnalysis,
  startCoinAnalysis,
  startAnalysis,
  searchKRStocks,
} from '@/api/client';
import { wsManager, type WebSocketHandlers } from '@/api/websocket';
import type { KRStockTradeProposal, SessionStatus, KRStockInfo } from '@/types';

// Market type icon component
function MarketIcon({ marketType }: { marketType: MarketType }) {
  switch (marketType) {
    case 'stock':
      return <LineChart className="w-3.5 h-3.5 text-green-400" />;
    case 'coin':
      return <Bitcoin className="w-3.5 h-3.5 text-yellow-400" />;
    case 'kiwoom':
      return <Building2 className="w-3.5 h-3.5 text-blue-400" />;
  }
}

// Format currency based on market type
function formatCurrency(price: number, marketType: MarketType): string {
  if (marketType === 'stock') {
    return `$${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  // KRW for coin and kiwoom
  if (price >= 1000000) {
    return `₩${(price / 10000).toFixed(0)}만`;
  }
  return `₩${price.toLocaleString('ko-KR')}`;
}

// Format change rate
function formatChangeRate(rate: number): string {
  const sign = rate > 0 ? '+' : '';
  return `${sign}${rate.toFixed(2)}%`;
}

// Change color based on direction
function getChangeColor(change: 'RISE' | 'FALL' | 'EVEN'): string {
  if (change === 'RISE') return 'text-green-400';
  if (change === 'FALL') return 'text-red-400';
  return 'text-gray-400';
}

// Individual basket item component
function BasketItemRow({
  item,
  onRemove,
  onAnalyze,
  apiConfigured,
}: {
  item: BasketItem;
  onRemove: () => void;
  onAnalyze: () => void;
  apiConfigured: boolean;
}) {
  const ChangeIcon = () => {
    if (item.change === 'RISE') return <TrendingUp className="w-3 h-3" />;
    if (item.change === 'FALL') return <TrendingDown className="w-3 h-3" />;
    return <Minus className="w-3 h-3" />;
  };

  return (
    <div className="flex items-center gap-2 px-3 py-2 hover:bg-surface/50 rounded-lg transition-colors group">
      {/* Market Icon & Name */}
      <MarketIcon marketType={item.marketType} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1">
          <span className="font-medium text-sm truncate">{item.displayName}</span>
          {item.displayName !== item.ticker && (
            <span className="text-xs text-gray-500">({item.ticker})</span>
          )}
        </div>

        {/* Price & Change */}
        {item.isLoading ? (
          <div className="flex items-center gap-1 text-xs text-gray-500">
            <RefreshCw className="w-3 h-3 animate-spin" />
            <span>Loading...</span>
          </div>
        ) : item.error ? (
          <div className="flex items-center gap-1 text-xs text-red-400">
            <AlertCircle className="w-3 h-3" />
            <span className="truncate" title={item.error}>
              {item.error.includes('API') ? 'API 미등록' : 'Error'}
            </span>
          </div>
        ) : item.price > 0 ? (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-gray-300">{formatCurrency(item.price, item.marketType)}</span>
            <span className={`flex items-center gap-0.5 ${getChangeColor(item.change)}`}>
              <ChangeIcon />
              {formatChangeRate(item.changeRate)}
            </span>
          </div>
        ) : !apiConfigured ? (
          <div className="flex items-center gap-1 text-xs text-yellow-500">
            <AlertCircle className="w-3 h-3" />
            <span>API 설정 필요</span>
          </div>
        ) : (
          <span className="text-xs text-gray-500">가격 정보 없음</span>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={onAnalyze}
          className="p-1.5 text-blue-400 hover:bg-blue-500/20 rounded transition-colors"
          title="분석 시작"
        >
          <Play className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={onRemove}
          className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-red-500/20 rounded transition-colors"
          title="삭제"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}

// API Not Configured Warning
function ApiNotConfiguredWarning({
  marketType,
  onConfigure,
}: {
  marketType: MarketType;
  onConfigure: () => void;
}) {
  const marketName = marketType === 'coin' ? 'Upbit' : marketType === 'kiwoom' ? 'Kiwoom' : 'Stock';

  return (
    <div className="px-3 py-2 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
      <div className="flex items-start gap-2">
        <AlertCircle className="w-4 h-4 text-yellow-500 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="text-xs text-yellow-500 font-medium">
            {marketName} API 미등록
          </p>
          <p className="text-xs text-gray-400 mt-0.5">
            실시간 시세를 보려면 API를 등록하세요
          </p>
          <button
            onClick={onConfigure}
            className="flex items-center gap-1 mt-2 text-xs text-yellow-400 hover:text-yellow-300"
          >
            <Settings className="w-3 h-3" />
            설정으로 이동
          </button>
        </div>
      </div>
    </div>
  );
}

interface BasketWidgetProps {
  expanded?: boolean;
}

export function BasketWidget({ expanded = false }: BasketWidgetProps) {
  const [isAddingItem, setIsAddingItem] = useState(false);
  const [searchTicker, setSearchTicker] = useState('');
  const [searchMarket, setSearchMarket] = useState<MarketType>('kiwoom');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analyzingItems, setAnalyzingItems] = useState<Set<string>>(new Set());
  const [inputError, setInputError] = useState<string | null>(null);

  // Autocomplete state for Kiwoom stocks
  const [suggestions, setSuggestions] = useState<KRStockInfo[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Store selectors
  const basketItems = useStore(useShallow(selectBasketItems));
  const isBasketFull = useStore(selectIsBasketFull);
  const upbitApiConfigured = useStore((state) => state.upbitApiConfigured);
  const kiwoomApiConfigured = useStore((state) => state.kiwoomApiConfigured);
  const setShowSettingsModal = useStore((state) => state.setShowSettingsModal);
  const setActiveMarket = useStore((state) => state.setActiveMarket);
  const availableSlots = useStore(selectKiwoomAvailableSlots);

  // Navigation actions
  const setCurrentView = useStore((state) => state.setCurrentView);

  // Basket actions
  const addToBasket = useStore((state) => state.addToBasket);
  const removeFromBasket = useStore((state) => state.removeFromBasket);
  const clearBasket = useStore((state) => state.clearBasket);
  const updateBasketItemPrice = useStore((state) => state.updateBasketItemPrice);
  const setBasketItemError = useStore((state) => state.setBasketItemError);
  const setBasketItemLoading = useStore((state) => state.setBasketItemLoading);

  // Legacy session actions (for stock/coin single-session mode)
  const startCoinSession = useStore((state) => state.startCoinSession);
  const startStockSession = useStore((state) => state.startStockSession);

  // Multi-session actions for Kiwoom
  const addKiwoomSession = useStore((state) => state.addKiwoomSession);
  const updateKiwoomSessionStatus = useStore((state) => state.updateKiwoomSessionStatus);
  const updateKiwoomSessionStage = useStore((state) => state.updateKiwoomSessionStage);
  const addKiwoomSessionReasoning = useStore((state) => state.addKiwoomSessionReasoning);
  const setKiwoomSessionProposal = useStore((state) => state.setKiwoomSessionProposal);
  const setKiwoomSessionAwaitingApproval = useStore((state) => state.setKiwoomSessionAwaitingApproval);
  const setKiwoomSessionError = useStore((state) => state.setKiwoomSessionError);
  const setActiveKiwoomSession = useStore((state) => state.setActiveKiwoomSession);

  // Check which APIs need configuration based on basket items
  const hasCoinItems = basketItems.some((item) => item.marketType === 'coin');
  const hasKiwoomItems = basketItems.some((item) => item.marketType === 'kiwoom');
  const showCoinApiWarning = hasCoinItems && !upbitApiConfigured;
  const showKiwoomApiWarning = hasKiwoomItems && !kiwoomApiConfigured;

  // Fetch prices for coin items
  const fetchCoinPrices = useCallback(async () => {
    if (!upbitApiConfigured) return;

    const coinItems = basketItems.filter((item) => item.marketType === 'coin');
    if (coinItems.length === 0) return;

    const markets = coinItems.map((item) => item.ticker);

    try {
      const response = await getCoinTickers(markets);

      response.tickers.forEach((ticker) => {
        const change = ticker.change as 'RISE' | 'FALL' | 'EVEN';
        updateBasketItemPrice(
          ticker.market,
          ticker.trade_price,
          ticker.change_rate * 100,
          change
        );
      });
    } catch (error) {
      coinItems.forEach((item) => {
        setBasketItemError(item.ticker, 'API 호출 실패');
      });
    }
  }, [basketItems, upbitApiConfigured, updateBasketItemPrice, setBasketItemError]);

  // Auto-fetch prices periodically
  useEffect(() => {
    fetchCoinPrices();

    const interval = setInterval(() => {
      fetchCoinPrices();
    }, 30000); // Every 30 seconds

    return () => clearInterval(interval);
  }, [fetchCoinPrices]);

  // Search Korean stocks with debounce
  const searchStocks = useCallback(async (query: string) => {
    if (query.length < 1 || searchMarket !== 'kiwoom') {
      setSuggestions([]);
      return;
    }

    setIsSearching(true);
    try {
      const result = await searchKRStocks(query, 8);
      setSuggestions(result.stocks);
      setSelectedIndex(-1);
    } catch (error) {
      console.error('Failed to search stocks:', error);
      setSuggestions([]);
    } finally {
      setIsSearching(false);
    }
  }, [searchMarket]);

  // Debounced search effect
  useEffect(() => {
    if (searchMarket !== 'kiwoom') {
      setSuggestions([]);
      return;
    }

    const timer = setTimeout(() => {
      if (searchTicker.trim()) {
        searchStocks(searchTicker.trim());
      } else {
        setSuggestions([]);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [searchTicker, searchMarket, searchStocks]);

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

  // Handle keyboard navigation in dropdown
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!showDropdown || suggestions.length === 0) return;

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex((prev) => (prev < suggestions.length - 1 ? prev + 1 : prev));
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

  // Handle selecting a suggestion
  const handleSelectSuggestion = (stock: KRStockInfo) => {
    // Add to basket directly
    const exists = basketItems.some((item) => item.ticker === stock.stk_cd);
    if (exists) {
      setInputError(`${stock.stk_nm} (${stock.stk_cd})은 이미 바스켓에 있습니다`);
      return;
    }

    addToBasket({
      marketType: 'kiwoom',
      ticker: stock.stk_cd,
      displayName: stock.stk_nm,
      price: stock.cur_prc || 0,
      prevPrice: 0,
      changeRate: stock.prdy_ctrt || 0,
      change: stock.prdy_ctrt > 0 ? 'RISE' : stock.prdy_ctrt < 0 ? 'FALL' : 'EVEN',
    });

    if (!kiwoomApiConfigured) {
      setBasketItemError(stock.stk_cd, 'Kiwoom API 미등록');
    }

    setSearchTicker('');
    setSuggestions([]);
    setShowDropdown(false);
    setIsAddingItem(false);
    setInputError(null);
  };

  // Handle adding new items (supports comma-separated input)
  const handleAddItem = () => {
    // If there's a selected suggestion in dropdown, use it
    if (selectedIndex >= 0 && suggestions[selectedIndex] && searchMarket === 'kiwoom') {
      handleSelectSuggestion(suggestions[selectedIndex]);
      return;
    }

    // If suggestions exist and user presses Enter, use first suggestion
    if (suggestions.length > 0 && searchMarket === 'kiwoom') {
      handleSelectSuggestion(suggestions[0]);
      return;
    }

    if (!searchTicker.trim()) return;

    // Clear previous error
    setInputError(null);

    // Split by comma and process each ticker
    const tickers = searchTicker
      .split(',')
      .map((t) => t.trim().toUpperCase())
      .filter((t) => t.length > 0);

    let addedCount = 0;
    const invalidCodes: string[] = [];
    const needsFetch = searchMarket === 'coin' && upbitApiConfigured;

    for (const ticker of tickers) {
      // Check if basket is full
      if (basketItems.length + addedCount >= 10) break;

      // Check for duplicates
      const exists = basketItems.some(
        (item) => item.ticker === ticker ||
        (searchMarket === 'coin' && item.ticker === `KRW-${ticker}`)
      );
      if (exists) continue;

      let displayName = ticker;

      // For coin market, format ticker
      if (searchMarket === 'coin') {
        const formattedTicker = ticker.startsWith('KRW-') ? ticker : `KRW-${ticker}`;
        displayName = ticker.replace('KRW-', '');

        addToBasket({
          marketType: 'coin',
          ticker: formattedTicker,
          displayName,
          price: 0,
          prevPrice: 0,
          changeRate: 0,
          change: 'EVEN',
        });

        if (!upbitApiConfigured) {
          setBasketItemError(formattedTicker, 'Upbit API 미등록');
        } else {
          setBasketItemLoading(formattedTicker, true);
        }
        addedCount++;
      } else if (searchMarket === 'kiwoom') {
        // Korean stock - validate 6-digit stock code
        if (ticker.length !== 6 || !/^\d{6}$/.test(ticker)) {
          console.warn(`[BasketWidget] Invalid Kiwoom stock code: ${ticker}. Must be 6 digits.`);
          invalidCodes.push(ticker);
          continue; // Skip invalid stock codes
        }

        addToBasket({
          marketType: 'kiwoom',
          ticker,
          displayName: ticker, // Will be updated when we get stock name
          price: 0,
          prevPrice: 0,
          changeRate: 0,
          change: 'EVEN',
        });

        if (!kiwoomApiConfigured) {
          setBasketItemError(ticker, 'Kiwoom API 미등록');
        }
        addedCount++;
      } else {
        // US stock
        addToBasket({
          marketType: 'stock',
          ticker,
          displayName: ticker,
          price: 0,
          prevPrice: 0,
          changeRate: 0,
          change: 'EVEN',
        });
        addedCount++;
      }
    }

    // Show error for invalid codes
    if (invalidCodes.length > 0) {
      setInputError(`잘못된 종목코드: ${invalidCodes.join(', ')} (6자리 숫자 필요)`);
    }

    // Fetch prices for newly added coin items
    if (needsFetch && addedCount > 0) {
      fetchCoinPrices();
    }

    // Only close form if at least one item was added or all were invalid
    if (addedCount > 0 || invalidCodes.length === tickers.length) {
      setSearchTicker('');
      if (addedCount > 0) {
        setIsAddingItem(false);
      }
    }
  };

  // Create WebSocket handlers for a Kiwoom session
  const createKiwoomWebSocketHandlers = (sessionId: string): WebSocketHandlers => ({
    onReasoning: (entry) => {
      addKiwoomSessionReasoning(sessionId, entry);
    },
    onStatus: (data) => {
      updateKiwoomSessionStatus(sessionId, data.status as SessionStatus);
      updateKiwoomSessionStage(sessionId, data.stage);
      setKiwoomSessionAwaitingApproval(sessionId, data.awaiting_approval);
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
      setKiwoomSessionProposal(sessionId, proposal);
    },
    onComplete: (data) => {
      if (data.error) {
        setKiwoomSessionError(sessionId, data.error);
      }
      updateKiwoomSessionStatus(sessionId, data.status as SessionStatus);
      // Remove from analyzing items
      setAnalyzingItems((prev) => {
        const next = new Set(prev);
        next.delete(sessionId);
        return next;
      });
    },
    onError: () => {
      setKiwoomSessionError(sessionId, 'WebSocket connection error');
      setAnalyzingItems((prev) => {
        const next = new Set(prev);
        next.delete(sessionId);
        return next;
      });
    },
  });

  // Handle bulk analyze - start analysis for all items
  const handleBulkAnalyze = async () => {
    if (basketItems.length === 0) return;
    if (isAnalyzing) return;

    setIsAnalyzing(true);

    // Get current available slots from store (real-time)
    const currentSlots = useStore.getState().kiwoom.maxConcurrentSessions -
      useStore.getState().kiwoom.sessions.filter(
        s => s.status === 'running' || s.status === 'awaiting_approval'
      ).length;

    // Determine how many items we can analyze (respect max concurrent limit)
    const maxItems = Math.min(basketItems.length, currentSlots, 3);
    const itemsToAnalyze = basketItems.slice(0, maxItems);

    console.log('[BasketWidget] handleBulkAnalyze started', {
      totalItems: basketItems.length,
      maxItems,
      currentSlots,
      runningSessions: useStore.getState().kiwoom.sessions.length,
      itemsToAnalyze: itemsToAnalyze.map(i => i.ticker),
    });

    if (maxItems === 0) {
      console.warn('[BasketWidget] No available slots for analysis');
      setIsAnalyzing(false);
      return;
    }

    // Track which items were successfully started
    const startedItems: BasketItem[] = [];
    const startedSessions: string[] = [];

    for (let i = 0; i < itemsToAnalyze.length; i++) {
      const item = itemsToAnalyze[i];
      console.log(`[BasketWidget] Starting analysis ${i + 1}/${itemsToAnalyze.length}: ${item.ticker}`);

      try {
        const sessionId = await handleAnalyze(item);
        if (sessionId) {
          startedSessions.push(sessionId);
          startedItems.push(item);
          console.log(`[BasketWidget] ✓ Analysis started for ${item.ticker}: sessionId=${sessionId}`);
        } else {
          console.warn(`[BasketWidget] ✗ Analysis returned null for ${item.ticker}`);
        }

        // Delay between starts to avoid race conditions
        if (i < itemsToAnalyze.length - 1) {
          console.log(`[BasketWidget] Waiting 500ms before next analysis...`);
          await new Promise((resolve) => setTimeout(resolve, 500));
        }
      } catch (error) {
        console.error(`[BasketWidget] ✗ Failed to start analysis for ${item.ticker}:`, error);
        setBasketItemError(item.ticker, error instanceof Error ? error.message : '분석 시작 실패');
      }
    }

    console.log('[BasketWidget] handleBulkAnalyze completed', {
      startedSessions,
      totalStarted: startedSessions.length,
      failedCount: itemsToAnalyze.length - startedItems.length,
    });

    // Only remove items that were successfully started
    startedItems.forEach((item) => removeFromBasket(item.id));

    setIsAnalyzing(false);
  };

  // Handle starting analysis - now calls API and connects WebSocket
  const handleAnalyze = async (item: BasketItem): Promise<string | null> => {
    console.log(`[BasketWidget] handleAnalyze started for ${item.ticker}`, { item });

    // Mark item as analyzing
    setAnalyzingItems((prev) => new Set(prev).add(item.id));

    try {
      let sessionId: string;

      // Switch to the correct market
      console.log(`[BasketWidget] Setting active market: ${item.marketType}`);
      setActiveMarket(item.marketType);

      if (item.marketType === 'kiwoom') {
        // Call API to start analysis
        console.log(`[BasketWidget] Calling startKRStockAnalysis for ${item.ticker}`);
        const response = await startKRStockAnalysis({ stk_cd: item.ticker });
        sessionId = response.session_id;
        console.log(`[BasketWidget] API response received`, { sessionId, stk_nm: response.stk_nm });

        // Create session data for multi-session store
        const sessionData: SessionData = {
          sessionId,
          ticker: item.ticker,
          displayName: item.displayName || response.stk_nm || item.ticker,
          marketType: 'kiwoom',
          status: 'running',
          currentStage: null,
          reasoningLog: [],
          analyses: [],
          tradeProposal: null,
          awaitingApproval: false,
          activePosition: null,
          error: null,
          createdAt: new Date(),
          updatedAt: new Date(),
        };

        // Add to multi-session store - check if it was successful
        console.log(`[BasketWidget] Adding session to store`, { sessionId, ticker: item.ticker });
        const sessionAdded = addKiwoomSession(sessionData);

        if (!sessionAdded) {
          console.error(`[BasketWidget] Failed to add session to store for ${item.ticker}`);
          throw new Error('세션 추가 실패: 동시 분석 한도에 도달했습니다.');
        }

        // Connect WebSocket with handlers
        console.log(`[BasketWidget] Connecting WebSocket for ${sessionId}`);
        const handlers = createKiwoomWebSocketHandlers(sessionId);
        wsManager.connect(sessionId, handlers);

        // Set as active session
        console.log(`[BasketWidget] Setting active session: ${sessionId}`);
        setActiveKiwoomSession(sessionId);

        console.log(`[BasketWidget] Kiwoom analysis complete: ${item.ticker} -> ${sessionId}`);

      } else if (item.marketType === 'coin') {
        // For coin, use legacy single-session mode for now
        const response = await startCoinAnalysis({ market: item.ticker });
        sessionId = response.session_id;
        startCoinSession(sessionId, item.ticker, item.displayName);

      } else {
        // For US stock, use legacy single-session mode
        const response = await startAnalysis({ ticker: item.ticker });
        sessionId = response.session_id;
        startStockSession(sessionId, item.ticker);
      }

      // Remove from analyzing state but keep in basket until bulk clear
      setAnalyzingItems((prev) => {
        const next = new Set(prev);
        next.delete(item.id);
        return next;
      });

      return sessionId;

    } catch (error) {
      console.error(`Failed to start analysis for ${item.ticker}:`, error);

      // Remove from analyzing state
      setAnalyzingItems((prev) => {
        const next = new Set(prev);
        next.delete(item.id);
        return next;
      });

      // Show error on the basket item
      setBasketItemError(item.ticker, error instanceof Error ? error.message : 'Analysis failed');

      return null;
    }
  };

  // Handle configure API
  const handleConfigureApi = () => {
    setShowSettingsModal(true);
  };

  return (
    <div className={expanded ? '' : 'card'}>
      {/* Header */}
      <div className={`flex items-center justify-between ${expanded ? 'mb-4' : 'mb-3'}`}>
        <div className="flex items-center gap-2">
          <ShoppingBasket className={`${expanded ? 'w-6 h-6' : 'w-5 h-5'} text-purple-400`} />
          <h3 className={`font-semibold ${expanded ? 'text-base' : 'text-sm'}`}>My Basket</h3>
          <span className="px-1.5 py-0.5 text-xs bg-purple-600 text-white rounded-full">
            {basketItems.length}/10
          </span>
          {availableSlots < 3 && (
            <span className="px-1.5 py-0.5 text-xs bg-yellow-600/50 text-yellow-200 rounded-full" title="사용 가능한 분석 슬롯">
              슬롯: {availableSlots}/3
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {basketItems.length > 0 && (
            <>
              <button
                onClick={handleBulkAnalyze}
                disabled={isAnalyzing || availableSlots === 0}
                className={`p-1.5 rounded transition-colors ${
                  isAnalyzing || availableSlots === 0
                    ? 'text-gray-600 cursor-not-allowed'
                    : 'text-green-400 hover:bg-green-500/20'
                }`}
                title={
                  availableSlots === 0
                    ? '분석 슬롯이 모두 사용 중입니다'
                    : `전체 분석 (최대 ${Math.min(basketItems.length, availableSlots, 3)}개)`
                }
              >
                {isAnalyzing ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <PlayCircle className="w-4 h-4" />
                )}
              </button>
              <button
                onClick={clearBasket}
                disabled={isAnalyzing}
                className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors disabled:opacity-50"
                title="전체 삭제"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </>
          )}
          <button
            onClick={() => setIsAddingItem(true)}
            disabled={isBasketFull}
            className={`p-1.5 rounded transition-colors ${
              isBasketFull
                ? 'text-gray-600 cursor-not-allowed'
                : 'text-purple-400 hover:bg-purple-500/20'
            }`}
            title={isBasketFull ? '바스켓이 가득 찼습니다' : '종목 추가'}
          >
            <Plus className="w-4 h-4" />
          </button>
          {!expanded && (
            <button
              onClick={() => setCurrentView('basket')}
              className="flex items-center gap-0.5 ml-1 text-xs text-gray-400 hover:text-blue-400 transition-colors"
              title="전체 화면으로 보기"
            >
              <ChevronRight className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>

      {/* Add Item Form */}
      {isAddingItem && (
        <div className="mb-3 p-3 bg-surface-dark rounded-lg border border-border">
          <div className="flex items-center gap-2 mb-2">
            <select
              value={searchMarket}
              onChange={(e) => {
                setSearchMarket(e.target.value as MarketType);
                setInputError(null);
                setSuggestions([]);
                setShowDropdown(false);
              }}
              className="px-2 py-1.5 bg-surface border border-border rounded text-xs focus:outline-none focus:border-purple-500"
            >
              <option value="kiwoom">한국 주식</option>
              <option value="coin">코인</option>
              <option value="stock">미국 주식</option>
            </select>
            <div className="relative flex-1">
              <input
                ref={inputRef}
                type="text"
                value={searchTicker}
                onChange={(e) => {
                  setSearchTicker(e.target.value);
                  setInputError(null);
                  if (searchMarket === 'kiwoom') {
                    setShowDropdown(true);
                  }
                }}
                onFocus={() => {
                  if (searchMarket === 'kiwoom' && searchTicker.trim()) {
                    setShowDropdown(true);
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAddItem();
                  } else {
                    handleKeyDown(e);
                  }
                }}
                placeholder={
                  searchMarket === 'kiwoom'
                    ? '종목명 또는 코드 (예: 삼성전자, 005930)'
                    : searchMarket === 'coin'
                    ? '코인 (예: BTC, ETH, XRP)'
                    : '티커 (예: AAPL, TSLA)'
                }
                className={`w-full px-2 py-1.5 bg-surface border rounded text-xs focus:outline-none ${
                  inputError
                    ? 'border-red-500 focus:border-red-400'
                    : 'border-border focus:border-purple-500'
                }`}
                autoFocus
              />
              {/* Loading indicator */}
              {isSearching && (
                <div className="absolute right-2 top-1/2 -translate-y-1/2">
                  <Loader2 className="w-3 h-3 animate-spin text-gray-400" />
                </div>
              )}
              {/* Autocomplete dropdown for Kiwoom stocks */}
              {showDropdown && searchMarket === 'kiwoom' && suggestions.length > 0 && (
                <div
                  ref={dropdownRef}
                  className="absolute z-50 w-full mt-1 bg-surface-light border border-border rounded-lg shadow-lg max-h-48 overflow-y-auto"
                >
                  {suggestions.map((stock, index) => (
                    <button
                      key={stock.stk_cd}
                      type="button"
                      onClick={() => handleSelectSuggestion(stock)}
                      className={`w-full px-3 py-2 text-left flex items-center gap-2 hover:bg-surface transition-colors ${
                        index === selectedIndex ? 'bg-surface' : ''
                      }`}
                    >
                      <Building2 className="w-3.5 h-3.5 text-blue-400 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="font-medium text-xs truncate">{stock.stk_nm}</span>
                          <span className="text-xs text-gray-500">{stock.stk_cd}</span>
                        </div>
                        {stock.cur_prc > 0 && (
                          <div className="flex items-center gap-1.5 text-xs">
                            <span className="text-gray-400">
                              {stock.cur_prc.toLocaleString()}원
                            </span>
                            <span className={stock.prdy_ctrt > 0 ? 'text-red-400' : stock.prdy_ctrt < 0 ? 'text-blue-400' : 'text-gray-400'}>
                              {stock.prdy_ctrt > 0 ? '+' : ''}{stock.prdy_ctrt?.toFixed(2)}%
                            </span>
                          </div>
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              )}
              {/* No results message */}
              {showDropdown && searchMarket === 'kiwoom' && searchTicker.trim() && suggestions.length === 0 && !isSearching && (
                <div
                  ref={dropdownRef}
                  className="absolute z-50 w-full mt-1 bg-surface-light border border-border rounded-lg shadow-lg"
                >
                  <div className="px-3 py-3 text-center text-gray-500 text-xs">
                    "{searchTicker}" 검색 결과 없음
                  </div>
                </div>
              )}
            </div>
          </div>
          {/* Error message */}
          {inputError && (
            <div className="flex items-center gap-1 mb-2 text-xs text-red-400">
              <AlertCircle className="w-3 h-3 flex-shrink-0" />
              <span>{inputError}</span>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <button
              onClick={() => {
                setIsAddingItem(false);
                setSearchTicker('');
                setInputError(null);
                setSuggestions([]);
                setShowDropdown(false);
              }}
              className="px-3 py-1 text-xs text-gray-400 hover:text-gray-300"
            >
              취소
            </button>
            <button
              onClick={handleAddItem}
              disabled={!searchTicker.trim() && suggestions.length === 0}
              className="px-3 py-1 text-xs bg-purple-600 hover:bg-purple-500 text-white rounded disabled:opacity-50 disabled:cursor-not-allowed"
            >
              추가
            </button>
          </div>
        </div>
      )}

      {/* API Warnings */}
      {showCoinApiWarning && (
        <div className="mb-2">
          <ApiNotConfiguredWarning marketType="coin" onConfigure={handleConfigureApi} />
        </div>
      )}
      {showKiwoomApiWarning && (
        <div className="mb-2">
          <ApiNotConfiguredWarning marketType="kiwoom" onConfigure={handleConfigureApi} />
        </div>
      )}

      {/* Basket Items */}
      <div className="space-y-1">
        {basketItems.length === 0 ? (
          <div className="text-center py-6 text-gray-500">
            <ShoppingBasket className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p className="text-xs">바스켓이 비어있습니다</p>
            <p className="text-xs mt-1">종목을 추가해보세요</p>
          </div>
        ) : (
          basketItems.map((item) => {
            const isItemAnalyzing = analyzingItems.has(item.id);
            return (
              <BasketItemRow
                key={item.id}
                item={{ ...item, isLoading: isItemAnalyzing || item.isLoading }}
                onRemove={() => removeFromBasket(item.id)}
                onAnalyze={() => handleAnalyze(item)}
                apiConfigured={
                  item.marketType === 'coin'
                    ? upbitApiConfigured
                    : item.marketType === 'kiwoom'
                    ? kiwoomApiConfigured
                    : true
                }
              />
            );
          })
        )}
      </div>

      {/* Info text */}
      <div className="mt-3 text-xs text-gray-500">
        종목을 클릭하여 분석을 시작하세요
      </div>
    </div>
  );
}
