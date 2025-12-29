/**
 * PopularTickerBar Component
 *
 * Horizontal scrolling ticker bar showing popular stocks/coins.
 * - CSS animation for infinite scroll
 * - Pause on hover
 * - Real-time price updates
 * - Market-specific data (Kiwoom or Upbit)
 */

import { useState, useEffect, useMemo, useRef } from 'react';
import { TrendingUp, TrendingDown, Minus, Loader2 } from 'lucide-react';
import { useStore } from '@/store';
import { getCoinTickers, getCoinMarkets, getKRStockTicker } from '@/api/client';

interface TickerItem {
  symbol: string;
  price: number;
  changeRate: number;
  change: 'RISE' | 'FALL' | 'EVEN';
  volume?: number;
}

// Popular Korean stock codes with names
const POPULAR_KR_STOCK_CODES: { code: string; name: string }[] = [
  { code: '005930', name: '삼성전자' },
  { code: '000660', name: 'SK하이닉스' },
  { code: '373220', name: 'LG에너지솔루션' },
  { code: '207940', name: '삼성바이오로직스' },
  { code: '005380', name: '현대차' },
  { code: '035420', name: 'NAVER' },
  { code: '035720', name: '카카오' },
  { code: '068270', name: '셀트리온' },
  { code: '105560', name: 'KB금융' },
  { code: '005490', name: 'POSCO홀딩스' },
];

export function PopularTickerBar() {
  const [tickers, setTickers] = useState<TickerItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isPaused, setIsPaused] = useState(false);
  const activeMarket = useStore((state) => state.activeMarket);
  const upbitApiConfigured = useStore((state) => state.upbitApiConfigured);
  const kiwoomApiConfigured = useStore((state) => state.kiwoomApiConfigured);
  const validMarketsRef = useRef<string[]>([]);

  // Fetch coin tickers from Upbit
  const fetchCoinTickers = async () => {
    try {
      // Get valid markets if not cached
      if (validMarketsRef.current.length === 0) {
        const marketsResponse = await getCoinMarkets();
        validMarketsRef.current = marketsResponse.markets
          .filter((m) => m.market.startsWith('KRW-'))
          .slice(0, 20)
          .map((m) => m.market);
      }

      if (validMarketsRef.current.length === 0) return;

      const response = await getCoinTickers(validMarketsRef.current);

      // Sort by volume and take top 10
      const sorted = response.tickers
        .sort((a, b) => b.acc_trade_price_24h - a.acc_trade_price_24h)
        .slice(0, 10);

      const tickerItems: TickerItem[] = sorted.map((t) => ({
        symbol: t.market.replace('KRW-', ''),
        price: t.trade_price,
        changeRate: t.change_rate * 100,
        change: t.change as 'RISE' | 'FALL' | 'EVEN',
        volume: t.acc_trade_price_24h,
      }));

      setTickers(tickerItems);
    } catch (err) {
      console.error('Failed to fetch coin tickers:', err);
    } finally {
      setIsLoading(false);
    }
  };

  // Fetch Korean stock tickers from Kiwoom API (sequential to avoid rate limit)
  const fetchKiwoomTickers = async () => {
    try {
      const results: TickerItem[] = [];

      // Fetch prices sequentially with delay to respect rate limits
      for (const stock of POPULAR_KR_STOCK_CODES) {
        try {
          const ticker = await getKRStockTicker(stock.code);
          const change: 'RISE' | 'FALL' | 'EVEN' =
            ticker.prdy_vrss > 0 ? 'RISE' : ticker.prdy_vrss < 0 ? 'FALL' : 'EVEN';
          results.push({
            symbol: stock.name,
            price: ticker.cur_prc,
            changeRate: ticker.prdy_ctrt,
            change,
            volume: ticker.trde_prica,
          });

          // Update UI progressively as tickers arrive
          if (results.length >= 3) {
            setTickers([...results]);
            setIsLoading(false);
          }

          // Small delay between requests (300ms) to help backend rate limiter
          await new Promise((resolve) => setTimeout(resolve, 300));
        } catch {
          // Skip failed fetches, continue with others
          console.warn(`Failed to fetch ticker for ${stock.code}`);
        }
      }

      // Final update with all results
      if (results.length > 0) {
        setTickers(results);
      } else {
        // If all failed, show names without prices
        setTickers(POPULAR_KR_STOCK_CODES.map((s) => ({
          symbol: s.name,
          price: 0,
          changeRate: 0,
          change: 'EVEN' as const,
        })));
      }
    } catch (err) {
      console.error('Failed to fetch Kiwoom tickers:', err);
      // Show names without prices on error
      setTickers(POPULAR_KR_STOCK_CODES.map((s) => ({
        symbol: s.name,
        price: 0,
        changeRate: 0,
        change: 'EVEN' as const,
      })));
    } finally {
      setIsLoading(false);
    }
  };

  // Fetch data based on market type
  useEffect(() => {
    const fetchData = async () => {
      setIsLoading(true);

      if (activeMarket === 'coin' && upbitApiConfigured) {
        await fetchCoinTickers();
      } else if (activeMarket === 'kiwoom') {
        if (kiwoomApiConfigured) {
          await fetchKiwoomTickers();
        } else {
          // Show names only without prices if API not configured
          setTickers(POPULAR_KR_STOCK_CODES.map((s) => ({
            symbol: s.name,
            price: 0,
            changeRate: 0,
            change: 'EVEN' as const,
          })));
          setIsLoading(false);
        }
      } else {
        // US stocks - use placeholder
        setTickers([]);
        setIsLoading(false);
      }
    };

    fetchData();

    // Refresh every 30 seconds
    const interval = setInterval(() => {
      if (activeMarket === 'coin' && upbitApiConfigured) {
        fetchCoinTickers();
      } else if (activeMarket === 'kiwoom' && kiwoomApiConfigured) {
        fetchKiwoomTickers();
      }
    }, 30000);

    return () => clearInterval(interval);
  }, [activeMarket, upbitApiConfigured, kiwoomApiConfigured]);

  // Duplicate items for seamless loop animation
  const displayTickers = useMemo(() => {
    if (tickers.length === 0) return [];
    // Duplicate the array for seamless scrolling
    return [...tickers, ...tickers];
  }, [tickers]);

  const formatPrice = (price: number) => {
    if (price >= 1000000) {
      return `${(price / 10000).toFixed(0)}만`;
    }
    if (price >= 1000) {
      return price.toLocaleString('ko-KR');
    }
    return price.toFixed(price < 1 ? 4 : 2);
  };

  const formatChange = (rate: number) => {
    const sign = rate > 0 ? '+' : '';
    return `${sign}${rate.toFixed(2)}%`;
  };

  const ChangeIcon = ({ change }: { change: string }) => {
    if (change === 'RISE') return <TrendingUp className="w-3 h-3" />;
    if (change === 'FALL') return <TrendingDown className="w-3 h-3" />;
    return <Minus className="w-3 h-3" />;
  };

  const getChangeColor = (change: string) => {
    if (change === 'RISE') return 'text-green-400';
    if (change === 'FALL') return 'text-red-400';
    return 'text-gray-400';
  };

  // Don't show for US stocks (no data source yet)
  if (activeMarket === 'stock') {
    return null;
  }

  // Show loading state
  if (isLoading && tickers.length === 0) {
    return (
      <div className="h-8 bg-surface-dark border-b border-border flex items-center justify-center">
        <Loader2 className="w-4 h-4 animate-spin text-gray-500" />
      </div>
    );
  }

  // Don't render if no tickers
  if (tickers.length === 0) {
    return null;
  }

  return (
    <div
      className="h-8 bg-surface-dark border-b border-border overflow-hidden relative"
      onMouseEnter={() => setIsPaused(true)}
      onMouseLeave={() => setIsPaused(false)}
    >
      {/* Gradient fade edges */}
      <div className="absolute left-0 top-0 bottom-0 w-8 bg-gradient-to-r from-surface-dark to-transparent z-10 pointer-events-none" />
      <div className="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-surface-dark to-transparent z-10 pointer-events-none" />

      {/* Scrolling container */}
      <div
        className={`flex items-center h-full ticker-scroll ${isPaused ? 'paused' : ''}`}
        style={{
          animation: `scroll ${tickers.length * 3}s linear infinite`,
          animationPlayState: isPaused ? 'paused' : 'running',
        }}
      >
        {displayTickers.map((ticker, idx) => (
          <div
            key={`${ticker.symbol}-${idx}`}
            className="flex items-center gap-2 px-4 whitespace-nowrap cursor-pointer hover:bg-surface/50 h-full transition-colors"
            title={`Click to analyze ${ticker.symbol}`}
          >
            <span className="font-medium text-sm">{ticker.symbol}</span>
            {ticker.price > 0 && (
              <>
                <span className="text-sm text-gray-300">
                  {(activeMarket === 'coin' || activeMarket === 'kiwoom') ? '₩' : '$'}{formatPrice(ticker.price)}
                </span>
                <span className={`flex items-center gap-0.5 text-xs ${getChangeColor(ticker.change)}`}>
                  <ChangeIcon change={ticker.change} />
                  {formatChange(ticker.changeRate)}
                </span>
              </>
            )}
            <span className="text-gray-600 mx-2">│</span>
          </div>
        ))}
      </div>

      {/* CSS for scrolling animation */}
      <style>{`
        @keyframes scroll {
          0% {
            transform: translateX(0);
          }
          100% {
            transform: translateX(-50%);
          }
        }
        .ticker-scroll {
          width: max-content;
        }
        .ticker-scroll.paused {
          animation-play-state: paused !important;
        }
      `}</style>
    </div>
  );
}
