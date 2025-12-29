/**
 * Chart Panel Component
 *
 * Container for TradingView Lightweight Charts with controls.
 * Shows real-time price for coin markets.
 */

import { useState, useCallback } from 'react';
import {
  Maximize2,
  Minimize2,
  Settings2,
  RefreshCw,
} from 'lucide-react';
import { useStore, selectChartConfig } from '@/store';
import { TradingChart } from './TradingChart';
import { CoinPriceTicker } from '@/components/coin/CoinPriceTicker';
import { KRStockPriceTicker } from '@/components/kiwoom/KRStockPriceTicker';
import type { TimeFrame } from '@/types';

interface ChartPanelProps {
  ticker: string;
}

// Timeframe options (분봉, 일봉, 주봉, 월봉, 년봉)
const TIMEFRAMES: { value: TimeFrame; label: string; labelKo: string }[] = [
  { value: '1m', label: '1M', labelKo: '1분' },
  { value: '5m', label: '5M', labelKo: '5분' },
  { value: '15m', label: '15M', labelKo: '15분' },
  { value: '1h', label: '1H', labelKo: '1시간' },
  { value: '1d', label: '1D', labelKo: '일봉' },
  { value: '1w', label: '1W', labelKo: '주봉' },
  { value: '1M', label: '1M', labelKo: '월봉' },
];

export function ChartPanel({ ticker }: ChartPanelProps) {
  const chartConfig = useStore(selectChartConfig);
  const setChartTimeframe = useStore((state) => state.setChartTimeframe);
  const toggleChartIndicator = useStore((state) => state.toggleChartIndicator);

  const [isExpanded, setIsExpanded] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const handleRefresh = useCallback(() => {
    setIsRefreshing(true);
    // Simulate refresh delay
    setTimeout(() => setIsRefreshing(false), 1000);
  }, []);

  return (
    <div
      className={`card transition-all duration-300 ${
        isExpanded ? 'fixed inset-4 z-40' : ''
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          {/* Show real-time price ticker based on market type */}
          {ticker.includes('-') ? (
            // Coin market (e.g., KRW-BTC)
            <CoinPriceTicker market={ticker} showDetails />
          ) : /^\d{6}$/.test(ticker) ? (
            // Korean stock (6-digit code)
            <KRStockPriceTicker stk_cd={ticker} showDetails />
          ) : (
            // US stock (fallback)
            <>
              <h2 className="font-semibold text-lg">{ticker}</h2>
              <span className="live-indicator text-sm text-bull">Live</span>
            </>
          )}
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2">
          {/* Refresh */}
          <button
            onClick={handleRefresh}
            className="p-2 hover:bg-surface rounded-lg"
            title="Refresh"
          >
            <RefreshCw
              className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`}
            />
          </button>

          {/* Settings */}
          <button
            onClick={() => setShowSettings(!showSettings)}
            className={`p-2 rounded-lg ${
              showSettings ? 'bg-blue-600' : 'hover:bg-surface'
            }`}
            title="Settings"
          >
            <Settings2 className="w-4 h-4" />
          </button>

          {/* Expand/Collapse */}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-2 hover:bg-surface rounded-lg"
            title={isExpanded ? 'Collapse' : 'Expand'}
          >
            {isExpanded ? (
              <Minimize2 className="w-4 h-4" />
            ) : (
              <Maximize2 className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {/* Timeframe Selector */}
      <div className="flex items-center gap-1 mb-4 overflow-x-auto scrollbar-hide">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf.value}
            onClick={() => setChartTimeframe(tf.value)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
              chartConfig.timeframe === tf.value
                ? 'bg-blue-600 text-white'
                : 'bg-surface hover:bg-surface-light text-gray-400'
            }`}
            title={tf.labelKo}
          >
            {tf.label}
          </button>
        ))}
      </div>

      {/* Settings Panel */}
      {showSettings && (
        <div className="mb-4 p-4 bg-surface rounded-lg">
          <h3 className="text-sm font-medium mb-3">Indicators</h3>
          <div className="flex flex-wrap gap-2">
            <IndicatorToggle
              label="SMA 50"
              active={chartConfig.showSMA50}
              onClick={() => toggleChartIndicator('showSMA50')}
            />
            <IndicatorToggle
              label="SMA 200"
              active={chartConfig.showSMA200}
              onClick={() => toggleChartIndicator('showSMA200')}
            />
            <IndicatorToggle
              label="Volume"
              active={chartConfig.showVolume}
              onClick={() => toggleChartIndicator('showVolume')}
            />
          </div>
        </div>
      )}

      {/* Chart */}
      <div
        className={`rounded-lg overflow-hidden bg-surface ${
          isExpanded ? 'h-[calc(100%-120px)]' : 'h-80 md:h-96'
        }`}
      >
        <TradingChart
          ticker={ticker}
          timeframe={chartConfig.timeframe}
          showSMA50={chartConfig.showSMA50}
          showSMA200={chartConfig.showSMA200}
          showVolume={chartConfig.showVolume}
          key={isRefreshing ? 'refreshing' : 'normal'}
        />
      </div>
    </div>
  );
}

interface IndicatorToggleProps {
  label: string;
  active: boolean;
  onClick: () => void;
}

function IndicatorToggle({ label, active, onClick }: IndicatorToggleProps) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
        active
          ? 'bg-blue-600/20 text-blue-400 border border-blue-600/30'
          : 'bg-surface-light text-gray-400 border border-transparent'
      }`}
    >
      {label}
    </button>
  );
}
