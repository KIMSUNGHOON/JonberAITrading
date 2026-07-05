/**
 * Chart tile — embeds the real TradingChart, fed by the active market's symbol.
 *
 * TradingChart is h-full and self-fetches candles (coin → Upbit, 6-digit → KR).
 * HONESTY GATE: US ('stock') / unknown symbols would fall to generateMockData
 * (random-walk fake candles), so we render an explicit awaiting state instead of
 * charting fabricated data. The symbol comes from selectTicker, which a running
 * analysis session populates — empty until then.
 */
import { useStore, selectTicker, selectChartConfig } from '@/store';
import { TradingChart } from '@/components/chart/TradingChart';
import { Awaiting } from './shared';

export function ChartTile() {
  const ticker = useStore(selectTicker);
  const cfg = useStore(selectChartConfig);
  const market = useStore((s) => s.activeMarket);

  const hasRealData =
    !!ticker && (market === 'coin' || market === 'kiwoom' || ticker.includes('-') || /^\d{6}$/.test(ticker));

  if (!hasRealData) {
    return (
      <Awaiting
        label={
          market === 'stock'
            ? 'US 실시간 차트 미연동 (SIM) · 종목 선택 시 표시'
            : '차트 대기 · :analyze <종목> 실행 시 표시'
        }
      />
    );
  }

  return (
    <div className="h-full">
      <TradingChart
        ticker={ticker}
        timeframe={cfg.timeframe}
        showSMA50={cfg.showSMA50}
        showSMA200={cfg.showSMA200}
        showVolume={cfg.showVolume}
      />
    </div>
  );
}
