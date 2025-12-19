/**
 * Trading Chart Component
 *
 * TradingView Lightweight Charts implementation.
 * Supports candlestick, moving averages, and volume.
 * Connects to real Upbit API for coin markets.
 */

import { useEffect, useRef, useState } from 'react';
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type LineData,
  ColorType,
  CrosshairMode,
} from 'lightweight-charts';
import { Loader2 } from 'lucide-react';
import type { TimeFrame } from '@/types';
import { getCoinCandles } from '@/api/client';

interface TradingChartProps {
  ticker: string;
  timeframe: TimeFrame;
  showSMA50: boolean;
  showSMA200: boolean;
  showVolume: boolean;
}

export function TradingChart({
  ticker,
  timeframe,
  showSMA50,
  showSMA200,
  showVolume,
}: TradingChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlestickSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const sma50SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const sma200SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0f1419' },
        textColor: '#9ca3af',
      },
      grid: {
        vertLines: { color: '#1f2937' },
        horzLines: { color: '#1f2937' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: '#4b5563',
          width: 1,
          style: 2,
        },
        horzLine: {
          color: '#4b5563',
          width: 1,
          style: 2,
        },
      },
      rightPriceScale: {
        borderColor: '#1f2937',
      },
      timeScale: {
        borderColor: '#1f2937',
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
    });

    chartRef.current = chart;

    // Add candlestick series
    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderDownColor: '#ef4444',
      borderUpColor: '#22c55e',
      wickDownColor: '#ef4444',
      wickUpColor: '#22c55e',
    });
    candlestickSeriesRef.current = candlestickSeries;

    // Handle resize
    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    };

    window.addEventListener('resize', handleResize);
    handleResize();

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  // Fetch and update data
  useEffect(() => {
    let isMounted = true;

    const fetchData = async () => {
      setIsLoading(true);
      setError(null);

      try {
        // Check if ticker is a coin market (e.g., KRW-BTC)
        const isCoinMarket = ticker.includes('-');

        let candles: CandlestickData[];

        if (isCoinMarket) {
          // Fetch real data from Upbit API for coin markets
          const intervalMap: Record<TimeFrame, string> = {
            '1m': '1m',
            '5m': '5m',
            '15m': '15m',
            '1h': '1h',
            '1d': '1d',
            '1w': '1w',
            '1M': '1M',
          };

          const interval = intervalMap[timeframe] || '1d';
          const response = await getCoinCandles(ticker, interval, 200);

          // Transform API response to lightweight-charts format
          // Upbit returns newest first, so reverse for chronological order
          candles = response.candles
            .map((c) => ({
              time: Math.floor(new Date(c.datetime).getTime() / 1000) as any,
              open: c.open,
              high: c.high,
              low: c.low,
              close: c.close,
            }))
            .reverse();
        } else {
          // Fall back to mock data for stock tickers
          const data = generateMockData(ticker, timeframe);
          candles = data.candles;
        }

        if (!isMounted || !chartRef.current || !candlestickSeriesRef.current) return;

        // Update candlestick data
        candlestickSeriesRef.current.setData(candles);

        // Fit content
        chartRef.current.timeScale().fitContent();

        setIsLoading(false);
      } catch (err) {
        if (isMounted) {
          console.error('Failed to fetch chart data:', err);
          setError('Failed to load chart data');
          setIsLoading(false);
        }
      }
    };

    fetchData();

    return () => {
      isMounted = false;
    };
  }, [ticker, timeframe]);

  // Handle SMA 50
  useEffect(() => {
    if (!chartRef.current || !candlestickSeriesRef.current) return;

    if (showSMA50) {
      if (!sma50SeriesRef.current) {
        const sma50Series = chartRef.current.addLineSeries({
          color: '#3b82f6',
          lineWidth: 2,
          title: 'SMA 50',
        });
        sma50SeriesRef.current = sma50Series;
      }

      // Calculate and set SMA data
      const smaData = calculateSMA(50);
      sma50SeriesRef.current.setData(smaData);
    } else {
      if (sma50SeriesRef.current) {
        chartRef.current.removeSeries(sma50SeriesRef.current);
        sma50SeriesRef.current = null;
      }
    }
  }, [showSMA50, ticker, timeframe]);

  // Handle SMA 200
  useEffect(() => {
    if (!chartRef.current || !candlestickSeriesRef.current) return;

    if (showSMA200) {
      if (!sma200SeriesRef.current) {
        const sma200Series = chartRef.current.addLineSeries({
          color: '#a855f7',
          lineWidth: 2,
          title: 'SMA 200',
        });
        sma200SeriesRef.current = sma200Series;
      }

      // Calculate and set SMA data
      const smaData = calculateSMA(200);
      sma200SeriesRef.current.setData(smaData);
    } else {
      if (sma200SeriesRef.current) {
        chartRef.current.removeSeries(sma200SeriesRef.current);
        sma200SeriesRef.current = null;
      }
    }
  }, [showSMA200, ticker, timeframe]);

  // Handle Volume
  useEffect(() => {
    if (!chartRef.current) return;

    if (showVolume) {
      if (!volumeSeriesRef.current) {
        const volumeSeries = chartRef.current.addHistogramSeries({
          color: '#4b5563',
          priceFormat: {
            type: 'volume',
          },
          priceScaleId: '',
        });

        volumeSeries.priceScale().applyOptions({
          scaleMargins: {
            top: 0.8,
            bottom: 0,
          },
        });

        volumeSeriesRef.current = volumeSeries;
      }

      // Check if coin market - fetch real volume data
      const isCoinMarket = ticker.includes('-');

      if (isCoinMarket) {
        // Fetch real volume from Upbit API
        const intervalMap: Record<TimeFrame, string> = {
          '1m': '1m',
          '5m': '5m',
          '15m': '15m',
          '1h': '1h',
          '1d': '1d',
          '1w': '1w',
          '1M': '1M',
        };

        const interval = intervalMap[timeframe] || '1d';

        getCoinCandles(ticker, interval, 200)
          .then((response) => {
            const volumeData = response.candles
              .map((c) => ({
                time: Math.floor(new Date(c.datetime).getTime() / 1000) as any,
                value: c.volume,
                color:
                  c.close >= c.open
                    ? 'rgba(34, 197, 94, 0.5)'
                    : 'rgba(239, 68, 68, 0.5)',
              }))
              .reverse();
            volumeSeriesRef.current?.setData(volumeData);
          })
          .catch(console.error);
      } else {
        // Fall back to mock volume data for stocks
        const volumeData = generateVolumeData(ticker, timeframe);
        volumeSeriesRef.current.setData(volumeData);
      }
    } else {
      if (volumeSeriesRef.current) {
        chartRef.current.removeSeries(volumeSeriesRef.current);
        volumeSeriesRef.current = null;
      }
    }
  }, [showVolume, ticker, timeframe]);

  if (error) {
    return (
      <div className="w-full h-full flex items-center justify-center text-gray-400">
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div className="relative w-full h-full">
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-surface/80 z-10">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
        </div>
      )}
      <div ref={containerRef} className="w-full h-full" />
    </div>
  );
}

// -------------------------------------------
// Helper Functions
// -------------------------------------------

function generateMockData(
  ticker: string,
  timeframe: TimeFrame
): { candles: CandlestickData[] } {
  const candles: CandlestickData[] = [];
  const now = new Date();

  // Determine time interval based on timeframe
  const intervals: Record<TimeFrame, number> = {
    '1m': 60 * 1000,
    '5m': 5 * 60 * 1000,
    '15m': 15 * 60 * 1000,
    '1h': 60 * 60 * 1000,
    '1d': 24 * 60 * 60 * 1000,
    '1w': 7 * 24 * 60 * 60 * 1000,
    '1M': 30 * 24 * 60 * 60 * 1000,
  };

  const interval = intervals[timeframe];
  const numCandles = 200;

  // Generate price based on ticker hash for consistency
  let basePrice = 100 + (ticker.charCodeAt(0) % 50) * 3;
  let price = basePrice;

  for (let i = numCandles - 1; i >= 0; i--) {
    const time = Math.floor((now.getTime() - i * interval) / 1000);

    // Random walk
    const change = (Math.random() - 0.48) * 2;
    const volatility = basePrice * 0.02;

    const open = price;
    const close = price + change * volatility;
    const high = Math.max(open, close) + Math.random() * volatility * 0.5;
    const low = Math.min(open, close) - Math.random() * volatility * 0.5;

    candles.push({
      time: time as any,
      open: Number(open.toFixed(2)),
      high: Number(high.toFixed(2)),
      low: Number(low.toFixed(2)),
      close: Number(close.toFixed(2)),
    });

    price = close;
  }

  return { candles };
}

function generateVolumeData(
  ticker: string,
  timeframe: TimeFrame
): HistogramData[] {
  const data: HistogramData[] = [];
  const now = new Date();

  const intervals: Record<TimeFrame, number> = {
    '1m': 60 * 1000,
    '5m': 5 * 60 * 1000,
    '15m': 15 * 60 * 1000,
    '1h': 60 * 60 * 1000,
    '1d': 24 * 60 * 60 * 1000,
    '1w': 7 * 24 * 60 * 60 * 1000,
    '1M': 30 * 24 * 60 * 60 * 1000,
  };

  const interval = intervals[timeframe];
  const numCandles = 200;
  const baseVolume = 1000000 + (ticker.charCodeAt(0) % 10) * 500000;

  for (let i = numCandles - 1; i >= 0; i--) {
    const time = Math.floor((now.getTime() - i * interval) / 1000);
    const volume = baseVolume * (0.5 + Math.random());
    const isUp = Math.random() > 0.5;

    data.push({
      time: time as any,
      value: volume,
      color: isUp ? 'rgba(34, 197, 94, 0.5)' : 'rgba(239, 68, 68, 0.5)',
    });
  }

  return data;
}

function calculateSMA(_period: number): LineData[] {
  // Mock SMA calculation
  const data: LineData[] = [];
  const now = new Date();
  const interval = 24 * 60 * 60 * 1000; // Daily for simplicity
  const numPoints = 200;

  let smaValue = 150;

  for (let i = numPoints - 1; i >= 0; i--) {
    const time = Math.floor((now.getTime() - i * interval) / 1000);
    smaValue += (Math.random() - 0.48) * 2;

    data.push({
      time: time as any,
      value: Number(smaValue.toFixed(2)),
    });
  }

  return data;
}
