/**
 * Chart tile — embeds the real TradingChart, fed by an explicitly-picked symbol
 * (watchlist/position row click → store.chartSymbol) or, failing that, the
 * active analysis session's ticker. So the chart works WITHOUT a running session
 * (candles need only ticker+timeframe).
 *
 * TradingChart is h-full and self-fetches candles (coin → Upbit, 6-digit → KR).
 * HONESTY GATE: unknown symbols have no live data source, so we render an
 * explicit awaiting state instead of charting fabricated data.
 */
import { useStore, selectTicker, selectChartConfig, selectChartSymbol } from '@/store';
import { TradingChart } from '@/components/chart/TradingChart';
import { Awaiting } from './shared';

/** Real data exists only for coin markets (contain '-') or 6-digit KR codes. */
function hasRealCandles(symbol: string): boolean {
  return symbol.includes('-') || /^\d{6}$/.test(symbol);
}

export function ChartTile() {
  const picked = useStore(selectChartSymbol);
  const sessionTicker = useStore(selectTicker);
  const cfg = useStore(selectChartConfig);

  const symbol = picked || sessionTicker;

  if (!symbol || !hasRealCandles(symbol)) {
    return (
      <Awaiting label="차트 대기 · 관심종목 행 클릭 또는 :analyze <종목>" />
    );
  }

  return (
    <div className="h-full">
      <TradingChart
        ticker={symbol}
        timeframe={cfg.timeframe}
        showSMA50={cfg.showSMA50}
        showSMA200={cfg.showSMA200}
        showVolume={cfg.showVolume}
      />
    </div>
  );
}
