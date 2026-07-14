/**
 * DISCOVERY section — P2 funnel Phase 1 (P1-b, design doc
 * docs/superpowers/specs/2026-07-14-funnel-consolidation-design.md).
 *
 * Surfaces backend controls that already exist but had ZERO UI callers
 * before this task:
 *  - Scanner pause/resume/stop (client.ts ~1517-1538) — only `startScan`
 *    had a caller; this wires all four plus a live progress bar.
 *  - The `auto_promote_enabled` flag on `/scanner/start` (P1-5, backend
 *    default False) — exposed as an explicit toggle with a warning, since
 *    turning it on feeds scan results straight into the server watch-list
 *    and from there the autonomous watch-monitor/queue pipeline (interacts
 *    with the HITL/master autonomy gate, not just this dashboard).
 *  - `POST /watch-list/add` (client.ts `addToWatchList`, ~1447-1507) — was a
 *    near-dead consumer; now the [승격▲] action on every result/Scratchpad row.
 *
 * No new backend work: every action here calls an endpoint that already
 * exists. Self-contained: no required props. Reads scanner status via REST
 * poll and the Scratchpad (the client `basket` store slice, user-facing
 * label "Scratchpad" since P2-T3) via the existing store, so T5 can drop
 * <DiscoverySection /> into the funnel panel with nothing else wired up.
 *
 * The server watch-list (ExecutionCoordinator) is KR-only, so the
 * [승격▲] action is disabled for coin Scratchpad rows (scan results are
 * always KR — the background scanner covers only KOSPI/KOSDAQ).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useShallow } from 'zustand/shallow';
import { useStore, selectBasketItems, type BasketItem, type MarketType } from '@/store';
import {
  startScan, pauseScan, resumeScan, stopScan,
  getScanProgress, getScanResults, addToWatchList, searchKRStocks,
} from '@/api/client';
import { useStartAnalysis } from '@/hooks/useStartAnalysis';
import type { ScanProgressResponse, ScanResultItem, KRStockInfo } from '@/types';
import { Awaiting, DASH, fmtPrice } from './shared';

const POLL_MS = 5_000;
const TOP_N = 10;

const STATUS_LABEL: Record<string, string> = {
  idle: 'IDLE', running: 'RUNNING', paused: 'PAUSED', completed: 'DONE', error: 'ERROR',
};
const STATUS_COLOR: Record<string, string> = {
  idle: 'text-muted', running: 'text-up', paused: 'text-warn', completed: 'text-accent', error: 'text-down',
};
// Action-badge colors follow the Western convention used elsewhere in the
// terminal shell (up=buy-side green, down=sell-side red).
const ACTION_COLOR: Record<string, string> = {
  STRONG_BUY: 'text-up', BUY: 'text-up', ADD: 'text-up',
  STRONG_SELL: 'text-down', SELL: 'text-down', AVOID: 'text-down', REDUCE: 'text-down',
  WATCH: 'text-warn', HOLD: 'text-muted', NO_ACTION: 'text-muted',
};

function ActionBadge({ action }: { action: string }) {
  const key = (action || '').toUpperCase();
  return <span className={`font-semibold ${ACTION_COLOR[key] ?? 'text-muted'}`}>{action || DASH}</span>;
}

// -------------------------------------------
// Scanner poll (progress + latest results)
// -------------------------------------------

function useScanState() {
  const [progress, setProgress] = useState<ScanProgressResponse | null>(null);
  const [results, setResults] = useState<ScanResultItem[]>([]);
  const aliveRef = useRef(true);

  const refetch = useCallback(async () => {
    try {
      const p = await getScanProgress();
      if (aliveRef.current) setProgress(p);
    } catch {
      /* keep last known progress — offline/dead-scan states are the
         dedicated ScannerLivenessChip's job, not this section's. */
    }
    try {
      const r = await getScanResults();
      if (aliveRef.current) setResults(r.results ?? []);
    } catch {
      /* keep last known results */
    }
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    refetch();
    const id = setInterval(refetch, POLL_MS);
    return () => { aliveRef.current = false; clearInterval(id); };
  }, [refetch]);

  return { progress, results, refetch };
}

// -------------------------------------------
// Scratchpad manual add — compact re-use of BasketWidget's KR-search +
// manual-ticker logic against the same store actions/endpoint, without
// pulling in BasketWidget's full autocomplete/keyboard-nav UI.
// -------------------------------------------

function useScratchpadAdd() {
  const addToBasket = useStore((s) => s.addToBasket);
  const [market, setMarket] = useState<MarketType>('kiwoom');
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<KRStockInfo[]>([]);
  const [addError, setAddError] = useState<string | null>(null);

  useEffect(() => {
    if (market !== 'kiwoom' || !query.trim()) {
      setSuggestions([]);
      return;
    }
    let alive = true;
    const id = setTimeout(async () => {
      try {
        const res = await searchKRStocks(query.trim(), 6);
        if (alive) setSuggestions(res.stocks);
      } catch {
        if (alive) setSuggestions([]);
      }
    }, 300);
    return () => { alive = false; clearTimeout(id); };
  }, [query, market]);

  const addSuggestion = useCallback((stock: KRStockInfo) => {
    addToBasket({
      marketType: 'kiwoom',
      ticker: stock.stk_cd,
      displayName: stock.stk_nm,
      price: stock.cur_prc || 0,
      prevPrice: 0,
      changeRate: stock.prdy_ctrt || 0,
      change: stock.prdy_ctrt > 0 ? 'RISE' : stock.prdy_ctrt < 0 ? 'FALL' : 'EVEN',
    });
    setQuery('');
    setSuggestions([]);
    setAddError(null);
  }, [addToBasket]);

  const addManual = useCallback(() => {
    const raw = query.trim();
    if (!raw) return;
    if (suggestions.length > 0 && market === 'kiwoom') {
      addSuggestion(suggestions[0]);
      return;
    }
    if (market === 'kiwoom') {
      const code = raw.toUpperCase();
      if (!/^\d{6}$/.test(code)) {
        setAddError('6자리 종목코드를 입력하세요 (예: 005930)');
        return;
      }
      addToBasket({
        marketType: 'kiwoom', ticker: code, displayName: code,
        price: 0, prevPrice: 0, changeRate: 0, change: 'EVEN',
      });
    } else {
      const upper = raw.toUpperCase();
      const ticker = upper.startsWith('KRW-') ? upper : `KRW-${upper}`;
      addToBasket({
        marketType: 'coin', ticker, displayName: upper.replace('KRW-', ''),
        price: 0, prevPrice: 0, changeRate: 0, change: 'EVEN',
      });
    }
    setQuery('');
    setAddError(null);
  }, [query, market, suggestions, addToBasket, addSuggestion]);

  return { market, setMarket, query, setQuery, suggestions, addSuggestion, addManual, addError };
}

// -------------------------------------------
// Main
// -------------------------------------------

export function DiscoverySection() {
  const { progress, results, refetch } = useScanState();
  const basketItems = useStore(useShallow(selectBasketItems));
  const startAnalysis = useStartAnalysis();
  const scratchpad = useScratchpadAdd();

  const [autoPromote, setAutoPromote] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const status = progress?.status ?? 'idle';
  const pct = Math.min(100, Math.max(0, progress?.progress_pct ?? 0));
  const completed = progress?.completed ?? 0;
  const total = progress?.total_stocks ?? 0;

  // Scanner start/pause/resume/stop: toggles `busy` (disables the control
  // row briefly) and refetches progress immediately after.
  const runScanAction = useCallback(async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await refetch();
    } catch (e) {
      setError(`${label} 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally {
      setBusy(false);
    }
  }, [refetch]);

  // Promote (watch-list/add): independent of scanner busy-state — a
  // promote click shouldn't disable the scan controls.
  const runPromote = useCallback(async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(`승격 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    }
  }, []);

  const handleStart = useCallback(() => {
    // Built as a variable (not an inline literal) so `auto_promote_enabled`
    // — real on the backend (P1-5) but not yet added to the FE
    // `StartScanRequest` type — can ride along without touching shared
    // types.ts; `notify_progress` keeps this assignable to that type.
    const scanRequest = { notify_progress: true, auto_promote_enabled: autoPromote };
    return runScanAction('스캔 시작', () => startScan(scanRequest));
  }, [runScanAction, autoPromote]);

  const handlePause = useCallback(() => runScanAction('일시중단', () => pauseScan()), [runScanAction]);
  const handleResume = useCallback(() => runScanAction('재개', () => resumeScan()), [runScanAction]);
  const handleStop = useCallback(() => runScanAction('정지', () => stopScan()), [runScanAction]);

  const handlePromoteResult = useCallback((r: ScanResultItem) => runPromote(() => addToWatchList({
    ticker: r.stk_cd,
    stock_name: r.stk_nm,
    signal: r.signal,
    confidence: r.confidence,
    current_price: r.current_price,
    analysis_summary: r.summary,
    key_factors: r.key_factors,
  })), [runPromote]);

  const handleAnalyzeResult = useCallback((r: ScanResultItem) => {
    startAnalysis('kiwoom', r.stk_cd, r.stk_nm).catch((e) => {
      setError(`분석 시작 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    });
  }, [startAnalysis]);

  const handlePromoteItem = useCallback((item: BasketItem) => {
    if (item.marketType !== 'kiwoom') return; // server watch-list is KR-only (ExecutionCoordinator)
    runPromote(() => addToWatchList({
      ticker: item.ticker,
      stock_name: item.displayName,
      current_price: item.price || 0,
    }));
  }, [runPromote]);

  const handleAnalyzeItem = useCallback((item: BasketItem) => {
    startAnalysis(item.marketType, item.ticker, item.displayName).catch((e) => {
      setError(`분석 시작 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    });
  }, [startAnalysis]);

  const topResults = [...results].sort((a, b) => b.confidence - a.confidence).slice(0, TOP_N);

  return (
    <div className="flex flex-col h-full min-h-0 text-[11px]">
      {error && (
        <div className="flex-none flex items-center justify-between gap-2 px-2.5 py-1 border-b border-hairline bg-down/5 text-down">
          <span>{error}</span>
          <button
            type="button"
            aria-label="오류 닫기"
            onClick={() => setError(null)}
            className="text-dim hover:text-down flex-none"
          >
            ✕
          </button>
        </div>
      )}

      {/* Scanner controls + progress */}
      <div className="flex-none px-2.5 py-2 border-b border-hairline">
        <div className="flex items-center gap-2">
          <span className={`uppercase font-semibold ${STATUS_COLOR[status] ?? 'text-muted'}`}>
            {STATUS_LABEL[status] ?? status}
          </span>
          <div
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            className="flex-1 h-1.5 rounded bg-elevated overflow-hidden"
          >
            <i className="block h-full bg-accent transition-[width] duration-500" style={{ width: `${pct}%` }} />
          </div>
          <span className="text-dim tabular-nums">
            {completed.toLocaleString()} / {total > 0 ? total.toLocaleString() : DASH}
          </span>
          <div className="flex gap-2 flex-none">
            {status === 'running' ? (
              <>
                <button type="button" disabled={busy} onClick={handlePause} className="text-warn font-medium disabled:opacity-50">
                  ⏸ 일시중단
                </button>
                <button type="button" disabled={busy} onClick={handleStop} className="text-down font-medium disabled:opacity-50">
                  ⏹ 정지
                </button>
              </>
            ) : status === 'paused' ? (
              <>
                <button type="button" disabled={busy} onClick={handleResume} className="text-up font-medium disabled:opacity-50">
                  ▶ 재개
                </button>
                <button type="button" disabled={busy} onClick={handleStop} className="text-down font-medium disabled:opacity-50">
                  ⏹ 정지
                </button>
              </>
            ) : (
              <button type="button" disabled={busy} onClick={handleStart} className="text-up font-medium disabled:opacity-50">
                ▶ 스캔 시작
              </button>
            )}
          </div>
        </div>
        <label className="flex items-center gap-1.5 mt-1.5 cursor-pointer text-dim">
          <input type="checkbox" checked={autoPromote} onChange={(e) => setAutoPromote(e.target.checked)} />
          자동 승격 (auto-promote)
        </label>
        {autoPromote && (
          <div className="mt-1 text-warn text-[10px] leading-snug">
            ⚠ 자동 승격 ON — 스캔 결과가 서버 워치리스트에 자동 등록되고, 자율 감시·토론을 거쳐 매수 큐로
            흘러갈 수 있습니다 (HITL·자율매매 마스터 게이트의 영향을 받는 자율 파이프라인입니다).
          </div>
        )}
      </div>

      {/* Scan results */}
      <div className="flex-1 min-h-0 overflow-y-auto border-b border-hairline">
        <div className="sticky top-0 bg-card text-[10px] text-muted font-semibold tracking-wide px-2.5 py-1.5 border-b border-hairline">
          스캔 결과 · 상위 {topResults.length}
        </div>
        {topResults.length === 0 ? (
          <Awaiting label="스캔 결과 없음 — 스캔을 시작하세요" />
        ) : (
          topResults.map((r) => (
            <div key={r.stk_cd} className="flex items-center justify-between gap-2 px-2.5 py-1.5 border-b border-hairline/40">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="font-semibold truncate">{r.stk_nm || r.stk_cd}</span>
                  <span className="text-dim text-[10px]">{r.stk_cd}</span>
                  <ActionBadge action={r.action} />
                </div>
                <div className="text-dim text-[10px]">
                  신뢰도 {(r.confidence * 100).toFixed(0)}% · {fmtPrice(r.current_price, 'kiwoom')}
                </div>
              </div>
              <div className="flex gap-2 flex-none">
                <button
                  type="button"
                  onClick={() => handlePromoteResult(r)}
                  aria-label={`승격 ${r.stk_cd}`}
                  title="서버 워치리스트에 등록"
                  className="text-accent font-medium"
                >
                  승격▲
                </button>
                <button
                  type="button"
                  onClick={() => handleAnalyzeResult(r)}
                  aria-label={`분석 ${r.stk_cd}`}
                  title="분석 시작"
                  className="text-up font-medium"
                >
                  분석▶
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Scratchpad */}
      <div className="flex-none max-h-[45%] flex flex-col min-h-0">
        <div className="flex items-center justify-between px-2.5 py-1.5 border-b border-hairline flex-none">
          <span className="text-[10px] text-muted font-semibold tracking-wide">
            Scratchpad · {basketItems.length}/10
          </span>
        </div>
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 flex-none relative">
          <select
            value={scratchpad.market}
            onChange={(e) => scratchpad.setMarket(e.target.value as MarketType)}
            className="px-1.5 py-1 bg-card border border-hairline rounded text-[10px]"
          >
            <option value="kiwoom">KR</option>
            <option value="coin">COIN</option>
          </select>
          <input
            type="text"
            value={scratchpad.query}
            onChange={(e) => scratchpad.setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                scratchpad.addManual();
              }
            }}
            placeholder="종목코드/티커 (예: 005930, BTC)"
            className="flex-1 min-w-0 px-2 py-1 bg-card border border-hairline rounded text-[10px]"
          />
          <button
            type="button"
            onClick={scratchpad.addManual}
            className="px-2 py-1 bg-accent text-canvas rounded text-[10px]"
          >
            추가
          </button>
          {scratchpad.suggestions.length > 0 && (
            <div className="absolute z-10 top-full left-8 right-16 mt-1 bg-elevated border border-hairline rounded shadow-lg max-h-32 overflow-y-auto">
              {scratchpad.suggestions.map((s) => (
                <button
                  key={s.stk_cd}
                  type="button"
                  onClick={() => scratchpad.addSuggestion(s)}
                  className="w-full text-left px-2 py-1 text-[10px] hover:bg-canvas"
                >
                  {s.stk_nm} <span className="text-dim">{s.stk_cd}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {scratchpad.addError && (
          <div className="px-2.5 pb-1 text-down text-[10px] flex-none">{scratchpad.addError}</div>
        )}
        <div className="flex-1 min-h-0 overflow-y-auto">
          {basketItems.length === 0 ? (
            <Awaiting label="스크래치패드 비어있음 — 종목을 추가하세요" />
          ) : (
            basketItems.map((item) => (
              <div key={item.id} className="flex items-center justify-between gap-2 px-2.5 py-1.5 border-b border-hairline/40">
                <div className="flex-1 min-w-0">
                  <span className="font-semibold">{item.displayName}</span>
                  <span className="text-dim text-[10px] ml-1">{item.ticker}</span>
                </div>
                <div className="flex gap-2 flex-none">
                  <button
                    type="button"
                    onClick={() => handlePromoteItem(item)}
                    disabled={item.marketType !== 'kiwoom'}
                    aria-label={`승격 ${item.ticker}`}
                    title={item.marketType !== 'kiwoom' ? '서버 워치리스트는 KR 전용입니다' : '서버 워치리스트에 등록'}
                    className="text-accent font-medium disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    승격▲
                  </button>
                  <button
                    type="button"
                    onClick={() => handleAnalyzeItem(item)}
                    aria-label={`분석 ${item.ticker}`}
                    title="분석 시작"
                    className="text-up font-medium"
                  >
                    분석▶
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
