/**
 * Trading Chart Component
 *
 * TradingView Lightweight Charts implementation.
 * Supports candlestick, moving averages, and volume.
 * Connects to the real Kiwoom API for Korean stocks.
 */

import { useEffect, useRef, useState } from 'react';
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type LineData,
  ColorType,
  CrosshairMode,
} from 'lightweight-charts';
import { Loader2 } from 'lucide-react';
import type { TimeFrame } from '@/types';
import { getKRStockCandles } from '@/api/client';

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

  // Cache candle data to avoid duplicate API calls for volume
  const candleDataRef = useRef<{ time: any; open: number; high: number; low: number; close: number; volume: number }[]>([]);

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0b0e11' },
        textColor: '#7b8794',
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
        // Check if ticker is a Korean stock (6-digit numeric code)
        const isKRStock = /^\d{6}$/.test(ticker);

        let candles: CandlestickData[];

        if (isKRStock) {
          // Fetch real data from Kiwoom API for Korean stocks
          // Currently only daily candles are supported by Kiwoom API
          const response = await getKRStockCandles(ticker, 'D', 100);

          // Check if we got valid data
          if (!response.candles || response.candles.length === 0) {
            throw new Error('No candle data available');
          }

          // Transform API response to lightweight-charts format
          // Kiwoom returns newest first, so reverse for chronological order
          const transformedCandles = response.candles
            .filter((c) => c.datetime && c.open && c.high && c.low && c.close)
            .map((c) => ({
              time: Math.floor(new Date(c.datetime).getTime() / 1000) as any,
              open: c.open,
              high: c.high,
              low: c.low,
              close: c.close,
              volume: c.volume,
            }))
            .reverse();

          if (transformedCandles.length === 0) {
            throw new Error('Invalid candle data received');
          }

          // Cache candle data for volume chart
          candleDataRef.current = transformedCandles;

          candles = transformedCandles.map(({ volume, ...rest }) => rest);
        } else {
          // No live data source for this ticker — render the honest error
          // state instead of fabricated candles.
          throw new Error('No chart data source for this symbol');
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

      // Calculate and set SMA data from cached candles
      if (candleDataRef.current.length > 0) {
        const smaData = calculateSMA(50, candleDataRef.current);
        sma50SeriesRef.current.setData(smaData);
      }
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

      // Calculate and set SMA data from cached candles
      if (candleDataRef.current.length > 0) {
        const smaData = calculateSMA(200, candleDataRef.current);
        sma200SeriesRef.current.setData(smaData);
      }
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

      // Korean stock - use cached data (already fetched for candlestick)
      const isKRStock = /^\d{6}$/.test(ticker);

      if (isKRStock && candleDataRef.current.length > 0) {
        // Use cached candle data for volume (avoid duplicate API call)
        const volumeData = candleDataRef.current.map((c) => ({
          time: c.time,
          value: c.volume,
          color:
            c.close >= c.open
              ? 'rgba(34, 197, 94, 0.5)'
              : 'rgba(239, 68, 68, 0.5)',
        }));
        volumeSeriesRef.current?.setData(volumeData);
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

function calculateSMA(
  period: number,
  candles: { time: any; close: number }[]
): LineData[] {
  // Calculate real SMA from candle data
  if (!candles || candles.length < period) {
    return [];
  }

  const data: LineData[] = [];

  for (let i = period - 1; i < candles.length; i++) {
    let sum = 0;
    for (let j = 0; j < period; j++) {
      sum += candles[i - j].close;
    }
    const sma = sum / period;

    data.push({
      time: candles[i].time,
      value: Number(sma.toFixed(2)),
    });
  }

  return data;
}
