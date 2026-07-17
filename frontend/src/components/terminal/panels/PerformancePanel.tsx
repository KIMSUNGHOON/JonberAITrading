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
import { getPerformance, getEodReport } from '@/api/client';
import { useTradeNotifications } from '@/hooks/useTradeNotifications';
import type {
  PerformanceDailyPoint, PerformanceResponse, EodReportResponse,
  EodDigest, EodDigestWatchItem, EodDigestAccount, EodDigestHolding,
  EodDigestStrategy, EodDigestRegime,
} from '@/types';
import { pnlColor } from '@/utils/pnl';
import { Awaiting, DASH, TH, fmtInt, fmtPct, fmtPrice } from './shared';

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
// EOD Report (E3-5) — 접이식 "EOD 리포트" 섹션 데이터 소스
// -------------------------------------------

type EodFetchState = 'loading' | 'ready' | 'error';

function useEodReport() {
  const [report, setReport] = useState<EodReportResponse | null>(null);
  const [state, setState] = useState<EodFetchState>('loading');
  const [err, setErr] = useState<string | null>(null);
  const aliveRef = useRef(true);

  const refetch = useCallback(async () => {
    try {
      // getEodReport() itself resolves null (not throw) on the expected
      // "no report yet" 404 — see its docstring in api/client.ts. `report`
      // staying null is the quiet-empty-state signal the render below acts on.
      const res = await getEodReport();
      if (!aliveRef.current) return;
      setReport(res);
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
    refetch();
    return () => { aliveRef.current = false; };
  }, [refetch]);

  // 장마감 요약 브로드캐스트 수신 시 즉시 재조회 — usePerformance의 체결
  // refetch 패턴과 동일하되, 이 섹션은 eod_summary 발생시에만 재조회한다
  // (모든 체결 알림마다 하루 1회 바뀌는 리포트를 다시 조회할 이유가 없다).
  useTradeNotifications({
    onNotification: (n) => { if (n.type === 'eod_summary') refetch(); },
    autoConnect: true,
  });

  return { report, state, err };
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
// EOD Report — 4-block digest fallback template
// -------------------------------------------

function EodWatchTable({ watch }: { watch: EodDigestWatchItem[] }) {
  if (!watch || watch.length === 0) {
    return <div className="px-2.5 py-1.5 text-[11px] text-dim">관심종목 없음</div>;
  }
  return (
    <table className="w-full text-[11px] tabular-nums">
      <thead>
        <tr>
          <th className={`${TH} text-left`}>종목</th>
          <th className={TH}>신호</th>
          <th className={TH}>신뢰도</th>
          <th className={TH}>현재가</th>
          <th className={TH}>목표진입가</th>
          <th className={TH}>갭%</th>
        </tr>
      </thead>
      <tbody>
        {watch.map((w, i) => (
          <tr key={w.ticker ?? i} className="border-b border-hairline last:border-b-0">
            <td className="text-left px-2 py-1 truncate max-w-[110px]">{w.stock_name ?? w.ticker ?? DASH}</td>
            <td className="text-right px-2 py-1 text-muted">{w.signal ?? DASH}</td>
            <td className="text-right px-2 py-1">{w.confidence != null ? `${(w.confidence * 100).toFixed(0)}%` : DASH}</td>
            <td className="text-right px-2 py-1">{fmtPrice(w.current_price, 'kiwoom')}</td>
            <td className="text-right px-2 py-1 text-muted">{fmtPrice(w.target_entry_price, 'kiwoom')}</td>
            <td className={`text-right px-2 py-1 ${w.gap_pct != null ? pnlColor(w.gap_pct) : ''}`}>{fmtPct(w.gap_pct)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function EodAccountCard({ account }: { account: EodDigestAccount }) {
  return (
    <div className="grid grid-cols-4 tabular-nums border border-hairline rounded">
      <Kpi label="예수금" value={fmtInt(account.deposit)} />
      <Kpi label="총평가" value={fmtInt(account.total_equity)} />
      <Kpi
        label="당일실현손익"
        value={fmtInt(account.daily_realized_pnl)}
        valueClassName={account.daily_realized_pnl != null ? pnlColor(account.daily_realized_pnl) : undefined}
      />
      <Kpi
        label="누적수익률"
        value={fmtPct(account.cumulative_return_pct)}
        valueClassName={account.cumulative_return_pct != null ? pnlColor(account.cumulative_return_pct) : undefined}
      />
    </div>
  );
}

function EodHoldingsTable({ holdings }: { holdings: EodDigestHolding[] }) {
  if (!holdings || holdings.length === 0) {
    return <div className="px-2.5 py-1.5 text-[11px] text-dim">보유 종목 없음</div>;
  }
  return (
    <table className="w-full text-[11px] tabular-nums">
      <thead>
        <tr>
          <th className={`${TH} text-left`}>종목</th>
          <th className={TH}>수량</th>
          <th className={TH}>평단가</th>
          <th className={TH}>현재가</th>
          <th className={TH}>평가손익</th>
          <th className={TH}>%</th>
          <th className={TH}>손절가</th>
          <th className={TH}>익절가</th>
        </tr>
      </thead>
      <tbody>
        {holdings.map((h, i) => (
          <tr key={h.ticker ?? i} className="border-b border-hairline last:border-b-0">
            <td className="text-left px-2 py-1 truncate max-w-[110px]">{h.stock_name ?? h.ticker ?? DASH}</td>
            <td className="text-right px-2 py-1">{fmtInt(h.quantity)}</td>
            <td className="text-right px-2 py-1 text-muted">{fmtPrice(h.avg_price, 'kiwoom')}</td>
            <td className="text-right px-2 py-1">{fmtPrice(h.current_price, 'kiwoom')}</td>
            <td className={`text-right px-2 py-1 ${h.unrealized_pnl != null ? pnlColor(h.unrealized_pnl) : ''}`}>{fmtInt(h.unrealized_pnl)}</td>
            <td className={`text-right px-2 py-1 ${h.unrealized_pnl_pct != null ? pnlColor(h.unrealized_pnl_pct) : ''}`}>{fmtPct(h.unrealized_pnl_pct)}</td>
            <td className="text-right px-2 py-1 text-muted">{fmtPrice(h.stop_loss, 'kiwoom')}</td>
            <td className="text-right px-2 py-1 text-muted">{fmtPrice(h.take_profit, 'kiwoom')}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function EodStrategyBlock({
  strategy, regime,
}: {
  strategy: EodDigestStrategy | null;
  regime: EodDigestRegime | null;
}) {
  if (!strategy) {
    return <div className="px-2.5 py-1.5 text-[11px] text-dim">전략 데이터 없음</div>;
  }
  const knobs = strategy.key_knobs;
  return (
    <div className="px-2.5 py-2 text-[11px]">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] uppercase tracking-wide text-muted">전략 스탠스</span>
        <span className="font-semibold text-ink">{strategy.stance ?? DASH}</span>
        {strategy.changed && (
          <span className="text-[9px] px-1 py-px rounded bg-accent/10 text-accent">변경됨</span>
        )}
      </div>
      <div className="text-dim text-[10px] mt-1">
        시장 레짐 {regime?.label ?? DASH} · KOSPI {fmtPct(regime?.index_kospi_chg_pct)} · KOSDAQ {fmtPct(regime?.index_kosdaq_chg_pct)}
      </div>
      {strategy.rationale_excerpt && (
        <div className="text-muted mt-1.5 leading-snug">{strategy.rationale_excerpt}</div>
      )}
      <div className="grid grid-cols-4 gap-2 mt-2 tabular-nums">
        <div>
          <div className="text-[9px] text-muted uppercase tracking-wide">손절%</div>
          <div>{fmtPct(knobs.stop_loss_pct)}</div>
        </div>
        <div>
          <div className="text-[9px] text-muted uppercase tracking-wide">익절%</div>
          <div>{fmtPct(knobs.take_profit_pct)}</div>
        </div>
        <div>
          <div className="text-[9px] text-muted uppercase tracking-wide">최대비중%</div>
          <div>{fmtPct(knobs.max_position_pct)}</div>
        </div>
        <div>
          <div className="text-[9px] text-muted uppercase tracking-wide">최대notional%</div>
          <div>{fmtPct(knobs.max_trade_notional_pct)}</div>
        </div>
      </div>
    </div>
  );
}

/** narrative 없을 때의 4블록 템플릿: 워치 표 · 잔고 카드 · 보유 표 · 전략 스탠스+노브. */
function EodDigestFallback({ digest }: { digest: EodDigest }) {
  return (
    <div className="flex flex-col gap-2">
      <EodWatchTable watch={digest.watch} />
      <EodAccountCard account={digest.account} />
      <EodHoldingsTable holdings={digest.holdings} />
      <EodStrategyBlock strategy={digest.strategy} regime={digest.regime} />
    </div>
  );
}

function EodReportSection({ report, state, err }: { report: EodReportResponse | null; state: EodFetchState; err: string | null }) {
  const digest = report?.digest;
  return (
    <details className="rounded border border-hairline bg-elevated group">
      <summary className="cursor-pointer select-none list-none px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted flex items-center justify-between">
        <span>EOD 리포트{report?.trade_date ? <span className="text-dim font-normal normal-case ml-1">{report.trade_date}</span> : null}</span>
        <span className="text-dim transition-transform group-open:rotate-90">›</span>
      </summary>
      <div className="px-2.5 pb-2 flex flex-col gap-2">
        {state === 'loading' && <div className="text-[11px] text-dim py-1">EOD 리포트 로드 중…</div>}
        {state === 'error' && <div className="text-[11px] text-down py-1">EOD 리포트 로드 오류 · {err}</div>}
        {state === 'ready' && !report && <div className="text-[11px] text-dim py-1">아직 리포트 없음</div>}
        {state === 'ready' && report && (
          <>
            {digest?.staleness_note && (
              <div className="text-[10px] text-warn">{digest.staleness_note}</div>
            )}
            {report.narrative ? (
              <div className="whitespace-pre-wrap text-[12px] leading-relaxed text-ink bg-card border border-hairline rounded p-2">
                {report.narrative}
              </div>
            ) : digest ? (
              <EodDigestFallback digest={digest} />
            ) : (
              <div className="text-[11px] text-dim py-1">리포트에 요약 데이터가 없습니다</div>
            )}
          </>
        )}
      </div>
    </details>
  );
}

// -------------------------------------------
// Main
// -------------------------------------------

export function PerformancePanel() {
  const { data, state, err } = usePerformance();
  const eod = useEodReport();

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
        <div className="p-2">
          <EodReportSection report={eod.report} state={eod.state} err={eod.err} />
        </div>
      </div>
    </div>
  );
}
