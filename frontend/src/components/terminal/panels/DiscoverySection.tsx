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
 *
 * Nav-rationalize (2026-07-14, docs/superpowers/audits/2026-07-14-dashboard-
 * widget-cull.md, user-approved "ABSORB"): the standalone Scratchpad page
 * (BasketPage/BasketWidget, /watchlist route) is gone — its power-staging
 * features (comma-separated bulk-add, autocomplete ↑/↓/Esc keyboard nav,
 * per-item remove + clear-all, bulk "analyze all" respecting the concurrent-
 * slot limit, the API-not-configured warning banner) are folded into this
 * Scratchpad section, on top of what it already had (30s live price
 * polling, row-click chart link, promote▲/analyze▶ per row).
 */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useShallow } from 'zustand/shallow';
import {
  useStore, selectBasketItems, selectChartSymbol, selectKiwoomAvailableSlots,
  type BasketItem, type MarketType,
} from '@/store';
import {
  startScan, pauseScan, resumeScan, stopScan,
  getScanProgress, getScanResults, addToWatchList, searchKRStocks,
  getCoinTickers, getKRStockTickers,
} from '@/api/client';
import { useStartAnalysis } from '@/hooks/useStartAnalysis';
import { changeColor } from '@/utils/pnl';
import type { ScanProgressResponse, ScanResultItem, KRStockInfo } from '@/types';
import { Awaiting, DASH, fmtPct, fmtPrice } from './shared';

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
// Scratchpad manual add — full parity with the former standalone
// BasketWidget (folded in, nav-rationalize 2026-07-14): comma-separated
// bulk-add and an autocomplete dropdown with ↑/↓/Esc keyboard nav, against
// the same store actions/endpoint.
// -------------------------------------------

function useScratchpadAdd(basketItems: BasketItem[]) {
  const addToBasket = useStore((s) => s.addToBasket);
  const [market, setMarketRaw] = useState<MarketType>('kiwoom');
  const [query, setQueryRaw] = useState('');
  const [suggestions, setSuggestions] = useState<KRStockInfo[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [dismissed, setDismissed] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  // Typing re-opens a dismissed (Esc'd) dropdown and resets keyboard selection.
  const setQuery = useCallback((v: string) => {
    setQueryRaw(v);
    setDismissed(false);
    setSelectedIndex(-1);
  }, []);

  const setMarket = useCallback((m: MarketType) => {
    setMarketRaw(m);
    setQueryRaw('');
    setSuggestions([]);
    setSelectedIndex(-1);
    setDismissed(false);
    setAddError(null);
  }, []);

  useEffect(() => {
    if (market !== 'kiwoom' || !query.trim()) {
      setSuggestions([]);
      return;
    }
    let alive = true;
    const id = setTimeout(async () => {
      try {
        const res = await searchKRStocks(query.trim(), 6);
        if (alive) { setSuggestions(res.stocks); setSelectedIndex(-1); }
      } catch {
        if (alive) setSuggestions([]);
      }
    }, 300);
    return () => { alive = false; clearTimeout(id); };
  }, [query, market]);

  const addSuggestion = useCallback((stock: KRStockInfo) => {
    if (basketItems.some((i) => i.ticker === stock.stk_cd)) {
      setAddError(`${stock.stk_nm} (${stock.stk_cd})은 이미 스크래치패드에 있습니다`);
      return;
    }
    addToBasket({
      marketType: 'kiwoom',
      ticker: stock.stk_cd,
      displayName: stock.stk_nm,
      price: stock.cur_prc || 0,
      prevPrice: 0,
      changeRate: stock.prdy_ctrt || 0,
      change: stock.prdy_ctrt > 0 ? 'RISE' : stock.prdy_ctrt < 0 ? 'FALL' : 'EVEN',
    });
    setQueryRaw('');
    setSuggestions([]);
    setSelectedIndex(-1);
    setAddError(null);
  }, [addToBasket, basketItems]);

  // Bulk add: comma-separated tickers/codes (BasketWidget parity). A single
  // non-comma kiwoom query with a live suggestion still prefers the
  // keyboard-selected (or first) autocomplete match over raw-code parsing.
  const addManual = useCallback(() => {
    const raw = query.trim();
    if (!raw) return;

    if (!raw.includes(',') && market === 'kiwoom' && suggestions.length > 0) {
      const pick = selectedIndex >= 0 ? suggestions[selectedIndex] : suggestions[0];
      if (pick) {
        addSuggestion(pick);
        return;
      }
    }

    const tokens = raw.split(',').map((t) => t.trim().toUpperCase()).filter(Boolean);
    const invalid: string[] = [];
    let added = 0;

    for (const token of tokens) {
      if (basketItems.length + added >= 10) break;

      if (market === 'kiwoom') {
        if (!/^\d{6}$/.test(token)) {
          invalid.push(token);
          continue;
        }
        if (basketItems.some((i) => i.ticker === token)) continue;
        addToBasket({
          marketType: 'kiwoom', ticker: token, displayName: token,
          price: 0, prevPrice: 0, changeRate: 0, change: 'EVEN',
        });
        added++;
      } else {
        const ticker = token.startsWith('KRW-') ? token : `KRW-${token}`;
        if (basketItems.some((i) => i.ticker === ticker)) continue;
        addToBasket({
          marketType: 'coin', ticker, displayName: token.replace('KRW-', ''),
          price: 0, prevPrice: 0, changeRate: 0, change: 'EVEN',
        });
        added++;
      }
    }

    setAddError(invalid.length > 0 ? `잘못된 종목코드: ${invalid.join(', ')} (6자리 숫자 필요)` : null);
    if (added > 0 || invalid.length === tokens.length) {
      setQueryRaw('');
      setSuggestions([]);
      setSelectedIndex(-1);
    }
  }, [query, market, suggestions, selectedIndex, basketItems, addToBasket, addSuggestion]);

  // ↑/↓ cycles the autocomplete dropdown; Esc dismisses it (until the next
  // keystroke); Enter commits (autocomplete pick, or bulk/manual add).
  const onKeyDown = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addManual();
    } else if (e.key === 'ArrowDown') {
      if (dismissed || suggestions.length === 0) return;
      e.preventDefault();
      setSelectedIndex((prev) => (prev < suggestions.length - 1 ? prev + 1 : prev));
    } else if (e.key === 'ArrowUp') {
      if (dismissed || suggestions.length === 0) return;
      e.preventDefault();
      setSelectedIndex((prev) => (prev > 0 ? prev - 1 : -1));
    } else if (e.key === 'Escape') {
      setDismissed(true);
      setSelectedIndex(-1);
    }
  }, [addManual, dismissed, suggestions.length]);

  return {
    market, setMarket,
    query, setQuery,
    suggestions: dismissed ? [] : suggestions,
    selectedIndex, addSuggestion, addManual, addError, onKeyDown,
  };
}

// -------------------------------------------
// Scratchpad price polling — re-homed from the former standalone Watchlist
// tile (merged in, P2 dashboard-cull). Batched (ONE request per market per
// poll, not one-per-symbol), 30s cadence, gated on the relevant API being
// configured. Unlike the old tile, the Scratchpad shows items from BOTH
// markets at once (no activeMarket filter) — so both effects run
// independently, each keyed on its own ticker subset, rather than one effect
// gated on a single activeMarket.
// -------------------------------------------

function useScratchpadPricePolling(basketItems: BasketItem[]) {
  const upbitApiConfigured = useStore((s) => s.upbitApiConfigured);
  const kiwoomApiConfigured = useStore((s) => s.kiwoomApiConfigured);
  const updateBasketItemPrice = useStore((s) => s.updateBasketItemPrice);

  // 코인 동결(freeze) fix round 2: coin 시세 폴링은 영구 비활성화한다. 정상 경로로는
  // basket에 coin 항목이 존재할 수 없다 — round 1에서 select의 COIN 옵션을 지웠고,
  // merge()가 rehydrate 시 marketType!=='kiwoom' 항목을 전부 걸러낸다(store/index.ts).
  // 그래도 어떤 경로로든(예: setState 직접 호출) coin 항목이 basket에 들어오면 이
  // 이펙트가 언마운트된 GET /coin/tickers를 칠 수 있으므로, basketItems 내용과
  // 무관하게 하드코딩해 방어한다(리뷰 발견).
  const coinTickers: string[] = [];
  const krTickers = basketItems.filter((i) => i.marketType === 'kiwoom').map((i) => i.ticker);

  // Coin prices (batched, gated on Upbit config).
  useEffect(() => {
    if (!upbitApiConfigured || coinTickers.length === 0) return;

    let alive = true;
    async function run() {
      try {
        const res = await getCoinTickers(coinTickers);
        if (!alive) return;
        res.tickers.forEach((t) => {
          updateBasketItemPrice(
            t.market,
            t.trade_price,
            t.change_rate * 100,
            t.change as 'RISE' | 'FALL' | 'EVEN',
          );
        });
      } catch {
        /* keep last known prices; do not fabricate */
      }
    }
    run();
    const id = setInterval(run, 30_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
    // ticker identity changes each render; key on the joined ticker set instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [upbitApiConfigured, coinTickers.join(','), updateBasketItemPrice]);

  // KR prices in ONE batch call (P1-7) instead of one request per symbol. A
  // code that fails to fetch maps to `null` in the response — that item MUST
  // keep its last known price rather than being blanked (the KR
  // early-return-skip guard WatchlistPanel.test.tsx regression-tested; kept
  // here verbatim across the merge).
  useEffect(() => {
    if (!kiwoomApiConfigured || krTickers.length === 0) return;

    let alive = true;
    async function run() {
      try {
        const res = await getKRStockTickers(krTickers);
        if (!alive) return;
        Object.values(res.tickers).forEach((t) => {
          if (!t) return; // keep last known price; do not fabricate
          updateBasketItemPrice(
            t.stk_cd,
            t.cur_prc,
            t.prdy_ctrt,
            t.prdy_ctrt > 0 ? 'RISE' : t.prdy_ctrt < 0 ? 'FALL' : 'EVEN',
          );
        });
      } catch {
        /* keep last known prices; do not fabricate */
      }
    }
    run();
    const id = setInterval(run, 30_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
    // ticker identity changes each render; key on the joined ticker set instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kiwoomApiConfigured, krTickers.join(','), updateBasketItemPrice]);
}

// -------------------------------------------
// Main
// -------------------------------------------

export function DiscoverySection() {
  const { progress, results, refetch } = useScanState();
  const basketItems = useStore(useShallow(selectBasketItems));
  const chartSymbol = useStore(selectChartSymbol);
  const setChartSymbol = useStore((s) => s.setChartSymbol);
  const removeFromBasket = useStore((s) => s.removeFromBasket);
  const clearBasket = useStore((s) => s.clearBasket);
  const setShowSettingsModal = useStore((s) => s.setShowSettingsModal);
  const upbitApiConfigured = useStore((s) => s.upbitApiConfigured);
  const kiwoomApiConfigured = useStore((s) => s.kiwoomApiConfigured);
  const startAnalysis = useStartAnalysis();
  const scratchpad = useScratchpadAdd(basketItems);
  useScratchpadPricePolling(basketItems);

  const [autoPromote, setAutoPromote] = useState(false);
  const [busy, setBusy] = useState(false);
  const [bulkAnalyzing, setBulkAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasCoinItems = basketItems.some((i) => i.marketType === 'coin');
  const hasKiwoomItems = basketItems.some((i) => i.marketType === 'kiwoom');
  const showCoinApiWarning = hasCoinItems && !upbitApiConfigured;
  const showKiwoomApiWarning = hasKiwoomItems && !kiwoomApiConfigured;

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
    // 코인 동결(freeze) fix round 2: handlePromoteItem과 동일한 방어 — 정상
    // 경로로는 basket에 coin 항목이 있을 수 없지만(merge()가 걸러냄), 어떤
    // 경로로든 존재하면 이 호출이 setActiveMarket('coin') 후 언마운트된
    // /coin/analysis/start를 치므로 marketType으로 차단한다(리뷰 발견).
    if (item.marketType !== 'kiwoom') return;
    startAnalysis(item.marketType, item.ticker, item.displayName).catch((e) => {
      setError(`분석 시작 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    });
  }, [startAnalysis]);

  // Bulk "analyze all" (BasketWidget.handleBulkAnalyze parity, folded in
  // nav-rationalize 2026-07-14): starts analysis for as many Scratchpad
  // items as the concurrent Kiwoom session slot limit allows (max 3 at
  // once), staggered 500ms apart to avoid session-creation races.
  // Successfully-started items are removed from the Scratchpad; failures
  // stay behind with an inline error.
  const handleBulkAnalyze = useCallback(async () => {
    if (basketItems.length === 0 || bulkAnalyzing) return;
    setBulkAnalyzing(true);
    setError(null);

    // 코인 동결(freeze) fix round 2: handleAnalyzeItem과 동일한 이유로 kiwoom
    // 항목만 대상으로 삼는다 — availableSlots도 kiwoom 세션 슬롯 기준이라 원래도
    // coin 항목엔 의미가 없었다.
    const kiwoomItems = basketItems.filter((item) => item.marketType === 'kiwoom');
    const availableSlots = selectKiwoomAvailableSlots(useStore.getState());
    const maxItems = Math.min(kiwoomItems.length, availableSlots, 3);
    const itemsToAnalyze = kiwoomItems.slice(0, maxItems);

    if (maxItems === 0) {
      setError('분석 슬롯이 모두 사용 중입니다');
      setBulkAnalyzing(false);
      return;
    }

    const startedItems: BasketItem[] = [];
    for (let i = 0; i < itemsToAnalyze.length; i++) {
      const item = itemsToAnalyze[i];
      try {
        const result = await startAnalysis(item.marketType, item.ticker, item.displayName);
        if (result.sessionId) startedItems.push(item);
        if (i < itemsToAnalyze.length - 1) {
          await new Promise((resolve) => setTimeout(resolve, 500));
        }
      } catch (e) {
        setError(`전체분석 실패 (${item.ticker}): ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
      }
    }
    startedItems.forEach((item) => removeFromBasket(item.id));
    setBulkAnalyzing(false);
  }, [basketItems, bulkAnalyzing, startAnalysis, removeFromBasket]);

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
          {basketItems.length > 0 && (
            <div className="flex items-center gap-2 flex-none">
              <button
                type="button"
                onClick={handleBulkAnalyze}
                disabled={bulkAnalyzing}
                aria-label="전체 분석"
                title="전체 분석 (동시 슬롯 한도 적용, 최대 3개)"
                className="text-up font-medium disabled:opacity-50"
              >
                {bulkAnalyzing ? '분석 중…' : '전체분석▶▶'}
              </button>
              <button
                type="button"
                onClick={clearBasket}
                aria-label="전체 삭제"
                title="스크래치패드 비우기"
                className="text-down font-medium"
              >
                전체삭제🗑
              </button>
            </div>
          )}
        </div>
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 flex-none relative">
          {/* 코인 동결(freeze) 이후 마켓은 KR 하나뿐 — COIN 옵션은 fix round 1에서
              제거됐다(scratchpad에서 market:'coin'으로 startCoinAnalysis까지 도달하던
              배선, 리뷰 발견). select 자체는 남겨 최소 변경으로 유지한다. */}
          <select
            value={scratchpad.market}
            onChange={(e) => scratchpad.setMarket(e.target.value as MarketType)}
            className="px-1.5 py-1 bg-card border border-hairline rounded text-[10px]"
          >
            <option value="kiwoom">KR</option>
          </select>
          <input
            type="text"
            value={scratchpad.query}
            onChange={(e) => scratchpad.setQuery(e.target.value)}
            onKeyDown={scratchpad.onKeyDown}
            placeholder="종목코드/티커, 콤마로 여러 개 (예: 005930,000660)"
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
              {scratchpad.suggestions.map((s, idx) => (
                <button
                  key={s.stk_cd}
                  type="button"
                  onClick={() => scratchpad.addSuggestion(s)}
                  className={`w-full text-left px-2 py-1 text-[10px] hover:bg-canvas ${
                    idx === scratchpad.selectedIndex ? 'bg-canvas' : ''
                  }`}
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
        {(showCoinApiWarning || showKiwoomApiWarning) && (
          <div className="flex-none flex items-center justify-between gap-2 px-2.5 py-1 border-b border-hairline bg-warn/10 text-warn text-[10px]">
            <span>
              {showCoinApiWarning && showKiwoomApiWarning
                ? 'Upbit·Kiwoom API 미등록 — 실시간 시세 없음'
                : showCoinApiWarning
                ? 'Upbit API 미등록 — 실시간 시세 없음'
                : 'Kiwoom API 미등록 — 실시간 시세 없음'}
            </span>
            <button type="button" onClick={() => setShowSettingsModal(true)} className="underline flex-none">
              설정으로 이동
            </button>
          </div>
        )}
        <div className="flex-1 min-h-0 overflow-y-auto">
          {basketItems.length === 0 ? (
            <Awaiting label="스크래치패드 비어있음 — 종목을 추가하세요" />
          ) : (
            basketItems.map((item) => (
              <div
                key={item.id}
                onClick={() => setChartSymbol(item.ticker)}
                title="차트에 표시"
                className={`flex items-center justify-between gap-2 px-2.5 py-1.5 border-b border-hairline/40 cursor-pointer hover:bg-elevated/40 ${
                  chartSymbol === item.ticker ? 'bg-elevated/60' : ''
                }`}
              >
                <div className="flex-1 min-w-0">
                  <span className="font-semibold">{item.displayName}</span>
                  <span className="text-dim text-[10px] ml-1">{item.ticker}</span>
                </div>
                <div className="flex items-center gap-2 flex-none text-[10px] tabular-nums">
                  <span>{fmtPrice(item.price, item.marketType)}</span>
                  <span className={changeColor(item.change)}>
                    {item.price > 0 ? fmtPct(item.changeRate) : DASH}
                  </span>
                </div>
                <div className="flex gap-2 flex-none">
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); handlePromoteItem(item); }}
                    disabled={item.marketType !== 'kiwoom'}
                    aria-label={`승격 ${item.ticker}`}
                    title={item.marketType !== 'kiwoom' ? '서버 워치리스트는 KR 전용입니다' : '서버 워치리스트에 등록'}
                    className="text-accent font-medium disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    승격▲
                  </button>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); handleAnalyzeItem(item); }}
                    disabled={item.marketType !== 'kiwoom'}
                    aria-label={`분석 ${item.ticker}`}
                    title={item.marketType !== 'kiwoom' ? '코인 동결 — 분석 미지원' : '분석 시작'}
                    className="text-up font-medium disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    분석▶
                  </button>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); removeFromBasket(item.id); }}
                    aria-label={`제거 ${item.ticker}`}
                    title="스크래치패드에서 제거"
                    className="text-dim hover:text-down font-medium"
                  >
                    ✕
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
