/**
 * BasketWidget Component — user-facing label is "Scratchpad" (P2-T3).
 *
 * Widget for staging multiple stocks/coins before analysis. Not the server
 * watch-list — see nav.ts for the naming split. Internal identifiers
 * (component/file name, `basket` store slice) are kept as-is to minimize
 * blast radius.
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
} from '@/store';
import { getCoinTickers, searchKRStocks } from '@/api/client';
import { useGoTo } from '@/hooks/useNav';
import { useStartAnalysis } from '@/hooks/useStartAnalysis';
import { pnlColor, changeColor } from '@/utils/pnl';
import type { KRStockInfo } from '@/types';

// Market type icon component
function MarketIcon({ marketType }: { marketType: MarketType }) {
  switch (marketType) {
    case 'coin':
      return <Bitcoin className="w-3.5 h-3.5 text-yellow-400" />; // color-ok: market identity, not directional
    case 'kiwoom':
      return <Building2 className="w-3.5 h-3.5 text-blue-400" />; // color-ok: market identity, not directional
  }
}

// Format currency based on market type
function formatCurrency(price: number, _marketType: MarketType): string {
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

// Change color based on direction — delegates to the shared Western-default helper.
function getChangeColor(change: 'RISE' | 'FALL' | 'EVEN'): string {
  return changeColor(change);
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
    <div className="flex items-center gap-2 px-3 py-2 hover:bg-elevated/50 rounded-lg transition-colors group">
      {/* Market Icon & Name */}
      <MarketIcon marketType={item.marketType} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1">
          <span className="font-medium text-sm truncate">{item.displayName}</span>
          {item.displayName !== item.ticker && (
            <span className="text-xs text-dim">({item.ticker})</span>
          )}
        </div>

        {/* Price & Change */}
        {item.isLoading ? (
          <div className="flex items-center gap-1 text-xs text-dim">
            <RefreshCw className="w-3 h-3 animate-spin" />
            <span>Loading...</span>
          </div>
        ) : item.error ? (
          <div className="flex items-center gap-1 text-xs text-down">
            <AlertCircle className="w-3 h-3" />
            <span className="truncate" title={item.error}>
              {item.error.includes('API') ? 'API 미등록' : 'Error'}
            </span>
          </div>
        ) : item.price > 0 ? (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-ink tabular-nums">{formatCurrency(item.price, item.marketType)}</span>
            <span className={`flex items-center gap-0.5 tabular-nums ${getChangeColor(item.change)}`}>
              <ChangeIcon />
              {formatChangeRate(item.changeRate)}
            </span>
          </div>
        ) : !apiConfigured ? (
          <div className="flex items-center gap-1 text-xs text-warn">
            <AlertCircle className="w-3 h-3" />
            <span>API 설정 필요</span>
          </div>
        ) : (
          <span className="text-xs text-dim">가격 정보 없음</span>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={onAnalyze}
          className="p-1.5 text-accent hover:bg-accent/20 rounded transition-colors"
          title="분석 시작"
        >
          <Play className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={onRemove}
          className="p-1.5 text-muted hover:text-red-400 hover:bg-red-500/20 rounded transition-colors" // color-ok: destructive action hover
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
  const marketName = marketType === 'coin' ? 'Upbit' : 'Kiwoom';

  return (
    <div className="px-3 py-2 bg-warn/10 border border-warn/30 rounded-lg">
      <div className="flex items-start gap-2">
        <AlertCircle className="w-4 h-4 text-warn flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="text-xs text-warn font-medium">
            {marketName} API 미등록
          </p>
          <p className="text-xs text-muted mt-0.5">
            실시간 시세를 보려면 API를 등록하세요
          </p>
          <button
            onClick={onConfigure}
            className="flex items-center gap-1 mt-2 text-xs text-warn hover:text-warn/80"
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
  const availableSlots = useStore(selectKiwoomAvailableSlots);

  // Navigation actions
  const goTo = useGoTo();

  // Basket actions
  const addToBasket = useStore((state) => state.addToBasket);
  const removeFromBasket = useStore((state) => state.removeFromBasket);
  const clearBasket = useStore((state) => state.clearBasket);
  const updateBasketItemPrice = useStore((state) => state.updateBasketItemPrice);
  const setBasketItemError = useStore((state) => state.setBasketItemError);
  const setBasketItemLoading = useStore((state) => state.setBasketItemLoading);

  // Shared "start analysis" flow (API call + session + Kiwoom WS wiring),
  // also used by the ⌘K command palette.
  const start = useStartAnalysis();

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
      setInputError(`${stock.stk_nm} (${stock.stk_cd})은 이미 스크래치패드에 있습니다`);
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
      const sessionId = await start(item.marketType, item.ticker, item.displayName);

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
          <ShoppingBasket className={`${expanded ? 'w-6 h-6' : 'w-5 h-5'} text-accent`} />
          <h3 className={`font-semibold ${expanded ? 'text-base' : 'text-sm'}`}>Scratchpad</h3>
          <span className="px-1.5 py-0.5 text-xs bg-accent text-canvas rounded-full tabular-nums">
            {basketItems.length}/10
          </span>
          {availableSlots < 3 && (
            <span className="px-1.5 py-0.5 text-xs bg-warn/20 text-warn rounded-full tabular-nums" title="사용 가능한 분석 슬롯">
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
                    ? 'text-dim cursor-not-allowed'
                    : 'text-accent hover:bg-accent/20'
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
                className="p-1.5 text-muted hover:text-red-400 hover:bg-red-500/10 rounded transition-colors disabled:opacity-50" // color-ok: destructive action hover
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
                ? 'text-dim cursor-not-allowed'
                : 'text-accent hover:bg-accent/20'
            }`}
            title={isBasketFull ? '스크래치패드가 가득 찼습니다' : '종목 추가'}
          >
            <Plus className="w-4 h-4" />
          </button>
          {!expanded && (
            <button
              onClick={() => goTo('basket')}
              className="flex items-center gap-0.5 ml-1 text-xs text-muted hover:text-accent transition-colors"
              title="전체 화면으로 보기"
            >
              <ChevronRight className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>

      {/* Add Item Form */}
      {isAddingItem && (
        <div className="mb-3 p-3 bg-elevated rounded-lg border border-hairline">
          <div className="flex items-center gap-2 mb-2">
            <select
              value={searchMarket}
              onChange={(e) => {
                setSearchMarket(e.target.value as MarketType);
                setInputError(null);
                setSuggestions([]);
                setShowDropdown(false);
              }}
              className="px-2 py-1.5 bg-card border border-hairline rounded text-xs focus:outline-none focus:border-accent"
            >
              <option value="kiwoom">한국 주식</option>
              <option value="coin">코인</option>
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
                className={`w-full px-2 py-1.5 bg-card border rounded text-xs focus:outline-none ${
                  inputError
                    ? 'border-down focus:border-down'
                    : 'border-hairline focus:border-accent'
                }`}
                autoFocus
              />
              {/* Loading indicator */}
              {isSearching && (
                <div className="absolute right-2 top-1/2 -translate-y-1/2">
                  <Loader2 className="w-3 h-3 animate-spin text-muted" />
                </div>
              )}
              {/* Autocomplete dropdown for Kiwoom stocks */}
              {showDropdown && searchMarket === 'kiwoom' && suggestions.length > 0 && (
                <div
                  ref={dropdownRef}
                  className="absolute z-50 w-full mt-1 bg-elevated border border-hairline rounded-lg shadow-lg max-h-48 overflow-y-auto"
                >
                  {suggestions.map((stock, index) => (
                    <button
                      key={stock.stk_cd}
                      type="button"
                      onClick={() => handleSelectSuggestion(stock)}
                      className={`w-full px-3 py-2 text-left flex items-center gap-2 hover:bg-canvas transition-colors ${
                        index === selectedIndex ? 'bg-canvas' : ''
                      }`}
                    >
                      <Building2 className="w-3.5 h-3.5 text-blue-400 flex-shrink-0" /> {/* color-ok: kiwoom market identity, not directional */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="font-medium text-xs truncate">{stock.stk_nm}</span>
                          <span className="text-xs text-dim">{stock.stk_cd}</span>
                        </div>
                        {stock.cur_prc > 0 && (
                          <div className="flex items-center gap-1.5 text-xs">
                            <span className="text-muted tabular-nums">
                              {stock.cur_prc.toLocaleString()}원
                            </span>
                            <span className={`${pnlColor(stock.prdy_ctrt)} tabular-nums`}>
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
                  className="absolute z-50 w-full mt-1 bg-elevated border border-hairline rounded-lg shadow-lg"
                >
                  <div className="px-3 py-3 text-center text-dim text-xs">
                    "{searchTicker}" 검색 결과 없음
                  </div>
                </div>
              )}
            </div>
          </div>
          {/* Error message */}
          {inputError && (
            <div className="flex items-center gap-1 mb-2 text-xs text-down">
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
              className="px-3 py-1 text-xs text-muted hover:text-ink"
            >
              취소
            </button>
            <button
              onClick={handleAddItem}
              disabled={!searchTicker.trim() && suggestions.length === 0}
              className="px-3 py-1 text-xs bg-accent hover:bg-accent/90 text-canvas rounded disabled:opacity-50 disabled:cursor-not-allowed"
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
          <div className="text-center py-6 text-dim">
            <ShoppingBasket className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p className="text-xs">스크래치패드가 비어있습니다</p>
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
      <div className="mt-3 text-xs text-dim">
        종목을 클릭하여 분석을 시작하세요
      </div>
    </div>
  );
}
