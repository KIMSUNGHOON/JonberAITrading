/**
 * PerformancePanel — the "prove returns" tile (TUX4): realized P&L, cumulative
 * return, win rate, and a daily P&L curve for the paper-trading account.
 *
 * Backed by GET /api/trading/performance, which itself wraps the pure
 * aggregation in services/trading/paper_performance.py over two independent
 * broker calls: `pnl` (ka10074 기간 실현손익) and `asset` (kt00004 평가액 →
 * 누적 수익률). Either section can fail on its own — this tile renders each
 * affected stat as "조회 실패" rather than a fabricated number, and an empty
 * (but successful) period renders an honest "표시할 손익 없음" instead of a
 * fake flat line. Same pattern as OperationsPanel's per-section degrade.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { getPerformance } from '@/api/client';
import { useTradeNotifications } from '@/hooks/useTradeNotifications';
import type { PerformanceDailyPoint, PerformanceResponse } from '@/types';
import { pnlColor } from '@/utils/pnl';
import { Awaiting, DASH, fmtInt, fmtPct } from './shared';

type FetchState = 'loading' | 'ready' | 'error';
const POLL_MS = 30_000;

function usePerformance() {
  const [data, setData] = useState<PerformanceResponse | null>(null);
  const [state, setState] = useState<FetchState>('loading');
  const [err, setErr] = useState<string | null>(null);
  const aliveRef = useRef(true);

  const refetch = useCallback(async (showLoading = false) => {
    if (showLoading) setState('loading');
    try {
      const res = await getPerformance();
      if (!aliveRef.current) return;
      setData(res);
      setState('ready');
      setErr(null);
    } catch (e) {
      if (!aliveRef.current) return;
      setErr(e instanceof Error ? e.message : '로드 실패');
      setState('error');
    }
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    refetch(true);
    const id = setInterval(() => refetch(false), POLL_MS);
    return () => { aliveRef.current = false; clearInterval(id); };
  }, [refetch]);

  // 체결 발생 시 실현손익/자산이 바로 바뀐다 — 즉시 재조회
  useTradeNotifications({ onNotification: () => refetch(false), autoConnect: true });

  return { data, state, err };
}

// -------------------------------------------
// KPI cell
// -------------------------------------------

function Kpi({
  label, value, valueClassName, failed, hint,
}: {
  label: string;
  value: string;
  valueClassName?: string;
  failed?: boolean;
  hint?: string;
}) {
  return (
    <div className="px-2.5 py-2 border-r border-hairline last:border-r-0" title={hint}>
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`text-[14px] font-bold mt-0.5 truncate ${failed ? 'text-down' : valueClassName ?? ''}`}>
        {failed ? '조회 실패' : value}
      </div>
    </div>
  );
}

// -------------------------------------------
// Daily P&L curve — inline SVG (diverging bars = daily delta, line = cumulative)
// -------------------------------------------

function formatDt(yyyymmdd: string): string {
  if (yyyymmdd.length !== 8) return yyyymmdd;
  return `${yyyymmdd.slice(4, 6)}/${yyyymmdd.slice(6, 8)}`;
}

const CHART_H = 90;
const PAD_TOP = 6;
const PAD_BOTTOM = 14;

function DailyCurve({ daily }: { daily: PerformanceDailyPoint[] }) {
  if (daily.length === 0) {
    return <Awaiting label="표시할 일별 손익 없음 — 기간 내 실현손익 발생일이 없습니다" />;
  }

  const width = 100; // viewBox units; scaled to 100% via the svg width attr
  const plotH = CHART_H - PAD_TOP - PAD_BOTTOM;
  const values = daily.flatMap((d) => [d.pnl, d.cumulative_pnl]);
  const maxAbs = Math.max(1, ...values.map((v) => Math.abs(v)));
  const yFor = (v: number) => PAD_TOP + plotH / 2 - (v / maxAbs) * (plotH / 2);
  const zeroY = yFor(0);
  const n = daily.length;
  const barW = Math.max(1, (width / n) * 0.6);
  const xFor = (i: number) => ((i + 0.5) / n) * width;
  const linePoints = daily.map((d, i) => `${xFor(i)},${yFor(d.cumulative_pnl)}`).join(' ');

  return (
    <div className="px-2.5 py-2">
      <svg
        viewBox={`0 0 ${width} ${CHART_H}`}
        width="100%"
        height={CHART_H}
        preserveAspectRatio="none"
        role="img"
        aria-label="일별 손익 및 누적 손익 곡선"
      >
        <line x1={0} x2={width} y1={zeroY} y2={zeroY} className="text-hairline" stroke="currentColor" strokeWidth={0.5} />
        {daily.map((d, i) => {
          const y = yFor(d.pnl);
          const top = Math.min(y, zeroY);
          const barH = Math.max(0.5, Math.abs(y - zeroY));
          return (
            <rect
              key={d.dt}
              x={xFor(i) - barW / 2}
              y={top}
              width={barW}
              height={barH}
              rx={0.5}
              className={pnlColor(d.pnl)}
              fill="currentColor"
            >
              <title>{`${formatDt(d.dt)}  일손익 ${d.pnl.toLocaleString()}원  누적 ${d.cumulative_pnl.toLocaleString()}원`}</title>
            </rect>
          );
        })}
        <polyline
          points={linePoints}
          fill="none"
          className="text-accent"
          stroke="currentColor"
          strokeWidth={1.25}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </svg>
      <div className="flex items-center justify-between text-[9px] text-dim mt-0.5">
        <span>{formatDt(daily[0].dt)}</span>
        <span className="flex items-center gap-2.5">
          <span className="inline-flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-up/70" />상승일</span>
          <span className="inline-flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-down/70" />하락일</span>
          <span className="inline-flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-accent" />누적</span>
        </span>
        <span>{formatDt(daily[daily.length - 1].dt)}</span>
      </div>
    </div>
  );
}

// -------------------------------------------
// Main
// -------------------------------------------

export function PerformancePanel() {
  const { data, state, err } = usePerformance();

  if (state === 'loading') return <Awaiting label="성과 로드 중…" />;
  if (state === 'error') return <Awaiting label={`성과 로드 오류 · ${err}`} />;
  if (!data) return <Awaiting label="성과 로드 중…" />;

  const pnlFailed = data.pnl === null;
  const assetFailed = data.asset === null;
  const pnlReason = data.errors.pnl;
  const assetReason = data.errors.asset;

  const realizedTotal = data.pnl?.realized_pnl_total ?? null;
  const winRate = data.pnl?.win_rate_pct ?? null;
  const cumulativeReturn = data.asset?.cumulative_return_pct ?? null;
  const currentAsset = data.asset?.current_asset ?? null;
  const baseAsset = data.asset?.base_asset ?? null;
  const noDecidedDays = data.pnl != null && data.pnl.win_days + data.pnl.loss_days === 0;

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="grid grid-cols-4 tabular-nums flex-none border-b border-hairline">
        <Kpi
          label="실현손익"
          value={fmtInt(realizedTotal)}
          valueClassName={realizedTotal != null ? pnlColor(realizedTotal) : undefined}
          failed={pnlFailed}
          hint={pnlFailed ? pnlReason : undefined}
        />
        <Kpi
          label="누적수익률"
          value={fmtPct(cumulativeReturn)}
          valueClassName={cumulativeReturn != null ? pnlColor(cumulativeReturn) : undefined}
          failed={assetFailed}
          hint={assetFailed ? assetReason : (baseAsset == null ? '기준 자산 미설정' : undefined)}
        />
        <Kpi
          label="승률"
          value={winRate != null ? `${winRate.toFixed(1)}%` : DASH}
          failed={pnlFailed}
          hint={pnlFailed ? pnlReason : (noDecidedDays ? '승부(체결) 없음' : undefined)}
        />
        <Kpi
          label="현재 자산"
          value={fmtInt(currentAsset)}
          failed={assetFailed}
          hint={assetFailed ? assetReason : (baseAsset != null ? `기준 자산 ${fmtInt(baseAsset)}원` : undefined)}
        />
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {pnlFailed ? (
          <Awaiting label={`일별 곡선 조회 실패 · ${pnlReason}`} />
        ) : (
          <DailyCurve daily={data.pnl!.daily} />
        )}
      </div>
    </div>
  );
}
