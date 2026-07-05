/**
 * Scanner tile — live KOSPI+KOSDAQ background-scan progress.
 *
 * Market-AGNOSTIC: the scanner is one global singleton over the KR universe, so
 * this tile does NOT follow activeMarket. Data is REST-only (getScanProgress),
 * polled every 5s. Replaces the previously hardcoded "idle · 0 / 2,100": status,
 * bar width and the total all come from the real ScanProgressResponse.
 */
import { useEffect, useState } from 'react';
import { getScanProgress } from '@/api/client';
import type { ScanProgressResponse } from '@/types';
import { DASH } from './shared';

const STATUS_LABEL: Record<string, string> = {
  idle: 'idle',
  running: 'running',
  paused: 'paused',
  completed: 'completed',
  error: 'error',
};

const STATUS_COLOR: Record<string, string> = {
  idle: 'text-muted',
  running: 'text-up',
  paused: 'text-warn',
  completed: 'text-accent',
  error: 'text-down',
};

function useScanProgress() {
  const [progress, setProgress] = useState<ScanProgressResponse | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let alive = true;

    async function run() {
      try {
        const p = await getScanProgress();
        if (!alive) return;
        setProgress(p);
        setOffline(false);
      } catch {
        if (!alive) return;
        setOffline(true);
      }
    }

    run();
    const id = setInterval(run, 5_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return { progress, offline };
}

export function ScannerPanel() {
  const { progress, offline } = useScanProgress();

  if (offline && !progress) {
    return (
      <div className="flex items-center gap-3 px-2.5 py-2 text-[11px] h-full">
        <span className="text-dim">스캐너 오프라인</span>
        <div className="flex-1 h-1.5 rounded bg-elevated overflow-hidden">
          <i className="block h-full w-0 bg-accent" />
        </div>
        <span className="text-dim tabular-nums">{DASH}</span>
      </div>
    );
  }

  const status = progress?.status ?? 'idle';
  const pct = progress?.progress_pct ?? 0;
  const completed = progress?.completed ?? 0;
  const total = progress?.total_stocks ?? 0;
  const counts = progress
    ? [
        ['B', progress.buy_count, 'text-up'],
        ['S', progress.sell_count, 'text-down'],
        ['W', progress.watch_count, 'text-warn'],
      ]
    : [];

  return (
    <div className="flex flex-col gap-1.5 px-2.5 py-2 text-[11px] h-full justify-center">
      <div className="flex items-center gap-3">
        <span className={`uppercase font-semibold ${STATUS_COLOR[status] ?? 'text-muted'}`}>
          {STATUS_LABEL[status] ?? status}
        </span>
        <div className="flex-1 h-1.5 rounded bg-elevated overflow-hidden">
          <i
            className="block h-full bg-accent transition-[width] duration-500"
            style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
          />
        </div>
        <span className="text-dim tabular-nums">
          {completed.toLocaleString()} / {total > 0 ? total.toLocaleString() : DASH}
        </span>
      </div>
      {progress && (status === 'running' || status === 'completed') && (
        <div className="flex items-center gap-3 text-[10px] tabular-nums">
          <span className="text-muted">{pct.toFixed(1)}%</span>
          {counts.map(([k, v, cls]) => (
            <span key={String(k)} className={String(cls)}>
              {String(k)} {Number(v).toLocaleString()}
            </span>
          ))}
          {status === 'running' && progress.current_stocks[0] && (
            <span className="text-dim truncate">· {progress.current_stocks[0]}</span>
          )}
        </div>
      )}
    </div>
  );
}
