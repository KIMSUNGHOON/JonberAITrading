/**
 * CoinMarketList Component
 *
 * Browse and search all available coin markets.
 * Displays real-time prices with updates.
 */

import { useState, useEffect } from 'react';
import { Search, TrendingUp, TrendingDown, Bitcoin } from 'lucide-react';
import { getCoinMarkets, getCoinTickers } from '@/api/client';
import type { CoinMarketInfo } from '@/types';

interface CoinMarketListProps {
  onSelectMarket: (market: string, koreanName?: string) => void;
  quoteCurrency?: 'KRW' | 'BTC' | 'USDT';
}

interface MarketWithPrice extends CoinMarketInfo {
  price?: number;
  change?: 'RISE' | 'EVEN' | 'FALL';
  changeRate?: number;
}

// Individual market row with price display
function MarketRow({
  market,
  onSelect,
}: {
  market: MarketWithPrice;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className="w-full flex items-center justify-between p-3 hover:bg-surface rounded-lg transition-colors"
    >
      <div className="flex items-center gap-3">
        <Bitcoin className="w-5 h-5 text-yellow-500" />
        <div className="text-left">
          <div className="font-medium">{market.korean_name}</div>
          <div className="text-xs text-gray-500">{market.market}</div>
        </div>
      </div>

      {market.price !== undefined && (
        <div className="text-right">
          <div className="font-medium">{market.price.toLocaleString('ko-KR')}</div>
          <div
            className={`text-xs flex items-center gap-1 justify-end ${
              market.change === 'RISE'
                ? 'text-green-400'
                : market.change === 'FALL'
                  ? 'text-red-400'
                  : 'text-gray-400'
            }`}
          >
            {market.change === 'RISE' ? (
              <TrendingUp className="w-3 h-3" />
            ) : market.change === 'FALL' ? (
              <TrendingDown className="w-3 h-3" />
            ) : null}
            {market.changeRate !== undefined && (
              <span>
                {market.changeRate > 0 ? '+' : ''}
                {(market.changeRate * 100).toFixed(2)}%
              </span>
            )}
          </div>
        </div>
      )}
    </button>
  );
}

export function CoinMarketList({
  onSelectMarket,
  quoteCurrency = 'KRW',
}: CoinMarketListProps) {
  const [markets, setMarkets] = useState<MarketWithPrice[]>([]);
  const [filteredMarkets, setFilteredMarkets] = useState<MarketWithPrice[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch markets on mount
  useEffect(() => {
    async function fetchMarkets() {
      try {
        const response = await getCoinMarkets(quoteCurrency);
        setMarkets(response.markets);
        setFilteredMarkets(response.markets);

        // Fetch prices for top 50 markets (increased from 20)
        const topMarkets = response.markets.slice(0, 50);
        await fetchPricesForMarkets(topMarkets, response.markets);
      } catch (err) {
        setError('Failed to load markets');
      } finally {
        setIsLoading(false);
      }
    }
    fetchMarkets();
  }, [quoteCurrency]);

  // Fetch prices for a list of markets using batch API
  async function fetchPricesForMarkets(
    marketsToFetch: CoinMarketInfo[],
    allMarkets: MarketWithPrice[]
  ) {
    try {
      // Use batch API to fetch all tickers in a single request
      const marketCodes = marketsToFetch.map((m) => m.market);
      const response = await getCoinTickers(marketCodes);

      // Create a map for quick lookup
      const priceMap = new Map(
        response.tickers.map((t) => [
          t.market,
          {
            price: t.trade_price,
            change: t.change as 'RISE' | 'EVEN' | 'FALL',
            changeRate: t.change_rate,
          },
        ])
      );

      // Update markets with prices
      const updatedMarkets = allMarkets.map((m) => {
        const priceData = priceMap.get(m.market);
        if (priceData) {
          return { ...m, ...priceData };
        }
        return m;
      });

      setMarkets(updatedMarkets);
      setFilteredMarkets((prev) =>
        prev.map((m) => {
          const updated = updatedMarkets.find((u) => u.market === m.market);
          return updated || m;
        })
      );
    } catch (err) {
      console.error('Failed to fetch prices:', err);
    }
  }

  // Filter markets based on search
  useEffect(() => {
    if (!searchQuery.trim()) {
      setFilteredMarkets(markets);
      return;
    }

    const query = searchQuery.toLowerCase();
    const filtered = markets.filter(
      (m) =>
        m.korean_name.toLowerCase().includes(query) ||
        m.english_name.toLowerCase().includes(query) ||
        m.market.toLowerCase().includes(query)
    );
    setFilteredMarkets(filtered);
  }, [searchQuery, markets]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    );
  }

  if (error) {
    return <div className="text-center text-red-400 py-8">{error}</div>;
  }

  return (
    <div className="flex flex-col h-full">
      {/* Search Header */}
      <div className="p-3 border-b border-border">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search coins..."
            className="input pl-10 w-full"
          />
        </div>
        <div className="text-xs text-gray-500 mt-2">
          {filteredMarkets.length} coins available
        </div>
      </div>

      {/* Market List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {filteredMarkets.map((market) => (
          <MarketRow
            key={market.market}
            market={market}
            onSelect={() => onSelectMarket(market.market, market.korean_name)}
          />
        ))}

        {filteredMarkets.length === 0 && (
          <div className="text-center text-gray-500 py-8">No coins found</div>
        )}
      </div>
    </div>
  );
}
