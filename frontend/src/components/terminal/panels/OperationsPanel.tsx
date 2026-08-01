/**
 * OPERATIONS pipeline board — the top-wide tile showing the full autonomous
 * operations flow in one glance: 분석중 → 승인대기 → 감시 → 매수대기 → 보유 →
 * 오늘체결. Each column is independently sourced server-side (Task 1); a
 * section that failed renders "조회 실패" honestly rather than faking a 0
 * count, and a section that's genuinely non-applicable is hidden outright.
 * Polls every 5s and refetches immediately on
 * any trade-notification push so the board tracks live state without a
 * manual refresh.
 *
 * Task 7 (P2 funnel-consolidation): the 승인대기 column (AwaitingColumn,
 * below) no longer carries its own approve/reject/cancel buttons — it is a
 * read-only summary that focuses the session and deep-links into the global
 * OrderTicketRail (frontend/src/components/terminal/OrderTicketRail.tsx),
 * which is now the ONE surface that calls submitApproval. Previously the
 * same pending approval was actionable from both places at once.
 *
 * Task 8b (P2 funnel-consolidation, final): WatchingColumn and
 * PendingBuyColumn now carry the re-analyze / cancel-queued-trade / manual
 * queue-process actions that used to live ONLY on the standalone /trading
 * widgets (WatchListWidget / TradeQueueWidget). Those two widgets have been
 * removed from the /trading route — this board (and FunnelPanel, which
 * reuses these same columns) is now the single place both actions are
 * reachable from.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '@/store';
import {
  getOperations, cancelKRStockSession, convertWatchToQueue,
  removeFromWatchList, cancelKRStockOrder, cancelQueuedTrade, processTradeQueue,
} from '@/api/client';
import { useTradeNotifications } from '@/hooks/useTradeNotifications';
import { useStartAnalysis } from '@/hooks/useStartAnalysis';
import type { OperationsResponse, OperationsAwaiting } from '@/types';
import { pnlColor } from '@/utils/pnl';
import { Awaiting, DASH, fmtInt, fmtPct, fmtPrice } from './shared';

type FetchState = 'loading' | 'ready' | 'error';
// Monitoring-cadence tuning: this poll (pending + filled orders) is the
// single biggest steady consumer of the shared Kiwoom QUERY rate budget
// per audit. Slowed 5s → 10s, and gated to skip while the tab is hidden
// (see the effect below) — reclaiming budget for the autonomous
// monitoring loops when nobody's watching the screen. A matching backend
// cache TTL bump (services/kiwoom/cache.py pending_orders/filled_orders)
// keeps 10s-fresh data without extra broker calls.
const POLL_MS = 10_000;

/**
 * Shared data source — exported so FunnelPanel's WATCHLIST + PIPELINE
 * sections poll the SAME underlying `/operations` response instead of
 * running a second independent poll (keeps the two sections in sync and
 * halves the request volume). See FunnelPanel.tsx for the consumer.
 */
export function useOperations() {
  const activeMarket = useStore((s) => s.activeMarket);
  const [data, setData] = useState<OperationsResponse | null>(null);
  const [state, setState] = useState<FetchState>('loading');
  const [err, setErr] = useState<string | null>(null);
  const aliveRef = useRef(true);

  const refetch = useCallback(async (showLoading = false) => {
    if (showLoading) setState('loading');
    try {
      const res = await getOperations('kiwoom');
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
    // Tab-visibility gating: skip the periodic data fetch while the tab is
    // hidden (no one is watching, so there's nothing to refresh for), and
    // catch up immediately the moment the tab regains visibility so the
    // board isn't stale on return.
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') refetch(false);
    }, POLL_MS);
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') refetch(false);
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      aliveRef.current = false;
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [refetch]);

  // 체결/큐/워치 이벤트 push 시 즉시 재조회
  useTradeNotifications({ onNotification: () => refetch(false), autoConnect: true });

  return { activeMarket, data, state, err, refetch };
}

// -------------------------------------------
// Column header
// -------------------------------------------

function ColumnHeader({
  label, items, errorKey, errors,
}: {
  label: string;
  items: unknown[] | null;
  errorKey: string;
  errors: Record<string, string>;
}) {
  const failed = items === null && errors[errorKey] != null;
  return (
    <div
      className="text-[10px] text-muted font-semibold tracking-wide px-2.5 py-1.5 border-b border-hairline sticky top-0 bg-card flex-none"
      title={failed ? errors[errorKey] : undefined}
    >
      {failed ? <span className="text-down">{label} · 조회 실패</span> : `${label} · ${items?.length ?? 0}`}
    </div>
  );
}

/** Column is hidden outright when its data is null with NO errors entry (non-applicable). */
function columnVisible(items: unknown[] | null, errorKey: string, errors: Record<string, string>): boolean {
  return items !== null || errors[errorKey] != null;
}

const COLUMN_WRAP = 'min-w-[150px] flex-1 border-r border-hairline/60 last:border-r-0 flex flex-col overflow-y-auto';
const CARD = 'px-2.5 py-1.5 border-b border-hairline/40 text-[11px]';

// -------------------------------------------
// 분석중
// -------------------------------------------

// Column components below are exported: FunnelPanel's PIPELINE section
// reuses them verbatim (minus WatchingColumn, which becomes its own
// WATCHLIST section) instead of reimplementing the honest-degrade contract.
export function AnalyzingColumn({
  items, errors, navigate, onCancel,
}: {
  items: OperationsResponse['analyzing'];
  errors: Record<string, string>;
  navigate: (path: string) => void;
  onCancel: (sessionId: string) => void;
}) {
  if (!columnVisible(items, 'sessions', errors)) return null;
  return (
    <div className={COLUMN_WRAP}>
      <ColumnHeader label="분석중" items={items} errorKey="sessions" errors={errors} />
      {(items ?? []).map((a) => (
        <div
          key={a.session_id}
          className={`${CARD} cursor-pointer hover:bg-elevated/40`}
          onClick={() => navigate(`/workflow/${a.session_id}`)}
        >
          <div className="flex items-start justify-between gap-1">
            <div>
              <div className="font-semibold">{a.name || a.ticker}</div>
              <div className="text-muted">{a.current_stage ?? DASH}</div>
            </div>
            <button
              type="button"
              aria-label="분석 취소"
              onClick={(e) => { e.stopPropagation(); onCancel(a.session_id); }}
              className="text-dim hover:text-down flex-none"
            >
              ✕
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

// -------------------------------------------
// 승인대기
// -------------------------------------------

function AwaitingCountdown({ autoApproveAt }: { autoApproveAt: string }) {
  const [nowTs, setNowTs] = useState(() => Date.now());
  useEffect(() => {
    setNowTs(Date.now());
    const id = setInterval(() => setNowTs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [autoApproveAt]);
  const secondsLeft = Math.max(0, Math.ceil((Date.parse(autoApproveAt) - nowTs) / 1000));
  return (
    <div className="text-accent font-medium tabular-nums">
      {secondsLeft > 0 ? `자율 승인까지 ${secondsLeft}초` : '자율 승인 처리 중…'}
    </div>
  );
}

// Task 7 (P2 funnel-consolidation): this column used to carry its own
// 승인/거부/취소 buttons calling submitApproval directly — the SAME endpoint
// the global OrderTicketRail (frontend/src/components/terminal/
// OrderTicketRail.tsx) already calls for the active session's ticket. With
// both surfaces live at once (and now THREE places once FunnelPanel's
// PIPELINE section reused this column too — Task 5), the same pending
// approval was actionable from multiple places simultaneously: confusing,
// and safety-adjacent since these buttons approve real paper trades.
//
// Resolution: OrderTicketRail is the ONE authoritative approval surface
// (it's global/always-docked, unlike this column which only appears inside
// whichever panel is currently tiled in). This column is now a read-only
// summary — clicking a row calls `onFocus` with the row's OWN data, which
// targets that session on the rail and navigates to its workflow view. No
// action (approve/reject/cancel) is lost — all three remain reachable, just
// from a single place.
//
// T7 review HIGH #1 fix: `onFocus` takes the FULL row (not just session_id).
// This column's rows come from the server /operations poll — a session can
// land here without ever touching this tab's local FE cache (kiwoom.
// sessions[], only populated by rehydrateKiwoomSessions at mount + this
// tab's own WS handlers). Passing only the id let the old handler silently
// no-op on a cache miss — see handleFocusAwaiting below, which now seeds
// the store straight from this row so the click is NEVER a no-op.
export function AwaitingColumn({
  items, errors, activeMarket, onFocus,
}: {
  items: OperationsResponse['awaiting'];
  errors: Record<string, string>;
  activeMarket: 'kiwoom';
  onFocus: (row: OperationsAwaiting) => void;
}) {
  if (!columnVisible(items, 'sessions', errors)) return null;
  return (
    <div className={COLUMN_WRAP}>
      <ColumnHeader label="승인대기" items={items} errorKey="sessions" errors={errors} />
      {(items ?? []).map((a) => {
        const proposal = a.proposal ?? {};
        const action = typeof proposal.action === 'string' ? proposal.action : DASH;
        const entry = typeof proposal.entry_price === 'number' ? proposal.entry_price : null;
        const stop = typeof proposal.stop_loss === 'number' ? proposal.stop_loss : null;
        const take = typeof proposal.take_profit === 'number' ? proposal.take_profit : null;
        const risk = typeof proposal.risk_score === 'number' ? proposal.risk_score : null;
        const notActionable = a.actionable === false;
        return (
          <div
            key={a.session_id}
            role="button"
            tabIndex={0}
            onClick={() => onFocus(a)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onFocus(a); } }}
            title="주문 레일에서 승인/거부/취소를 처리합니다"
            className={`${CARD} cursor-pointer hover:bg-elevated/40`}
          >
            <div className="font-semibold">{a.name || a.ticker}</div>
            <div className="text-muted">
              {action} · 진입 {fmtPrice(entry, activeMarket)} · 손절 {fmtPrice(stop, activeMarket)} · 익절 {fmtPrice(take, activeMarket)} · 리스크 {risk != null ? `${risk}/10` : DASH}
            </div>
            {a.auto_approve_at && <AwaitingCountdown autoApproveAt={a.auto_approve_at} />}
            {notActionable && (
              <div className="text-[10px] text-warn mt-0.5">세션 상태 불일치 · 취소만 가능</div>
            )}
            <div className="text-accent text-[10px] font-medium mt-1">주문 레일에서 처리 →</div>
          </div>
        );
      })}
    </div>
  );
}

// -------------------------------------------
// 감시
// -------------------------------------------

// 감시(WATCHLIST) status label — server enum values are lowercase
// (active/triggered/removed/converted); get_watch_list() only ever returns
// ACTIVE rows today, but the label map is honest about the full enum
// rather than assuming a single value.
const WATCH_STATUS_LABEL: Record<string, string> = {
  active: 'ACTIVE', triggered: 'TRIGGERED', removed: 'REMOVED', converted: 'CONVERTED',
};

export function WatchingColumn({
  items, errors, onConvert, onRemove, onReanalyze,
}: {
  items: OperationsResponse['watching'];
  errors: Record<string, string>;
  onConvert: (watchId: string) => void;
  onRemove: (watchId: string) => void;
  /** Task 8b: backported from the /trading WatchListWidget's re-analyze button. */
  onReanalyze: (ticker: string, name: string) => void;
}) {
  if (!columnVisible(items, 'watching', errors)) return null;
  return (
    <div className={COLUMN_WRAP}>
      <ColumnHeader label="감시" items={items} errorKey="watching" errors={errors} />
      {(items ?? []).map((raw, i) => {
        const w = raw as Record<string, unknown>;
        const id = w.id as string;
        const ticker = w.ticker as string;
        const name = (w.stock_name as string | null) ?? ticker;
        const currentPrice = w.current_price as number | null;
        const targetEntry = w.target_entry_price as number | null;
        const confidence = typeof w.confidence === 'number' ? w.confidence : null;
        const status = typeof w.status === 'string' ? w.status : null;
        // FI-3: provenance badge -- 'discovery' (regime-weighted ranking
        // auto-promotion, services/discovery/ranker.py) gets a small
        // "발굴" label; 'manual' (the historical default, user/analysis-
        // flow add) stays unbadged/unchanged.
        const source = typeof w.source === 'string' ? w.source : 'manual';
        return (
          <div key={id ?? i} className={CARD}>
            <div className="font-semibold flex items-center gap-1.5">
              {name}
              <span className="text-dim text-[10px] font-normal">{ticker}</span>
              {source === 'discovery' && (
                <span className="text-[9px] px-1 py-px rounded bg-accent/10 text-accent font-medium">발굴</span>
              )}
            </div>
            <div className="text-muted">
              현재 {fmtPrice(currentPrice, 'kiwoom')} · 목표진입 {fmtPrice(targetEntry, 'kiwoom')}
            </div>
            <div className="text-dim text-[10px]">
              신뢰도 {confidence != null ? `${(confidence * 100).toFixed(0)}%` : DASH}
              {' · '}
              {status ? (WATCH_STATUS_LABEL[status] ?? status.toUpperCase()) : DASH}
            </div>
            <div className="flex gap-2 mt-1">
              <button
                type="button"
                onClick={() => onConvert(id)}
                aria-label={`큐 전환 ${ticker}`}
                className="text-accent font-medium"
              >
                큐 전환
              </button>
              <button
                type="button"
                onClick={() => onReanalyze(ticker, name)}
                aria-label={`재분석 ${ticker}`}
                className="text-accent font-medium"
              >
                재분석
              </button>
              <button
                type="button"
                onClick={() => onRemove(id)}
                aria-label={`제거 ${ticker}`}
                className="text-dim hover:text-down font-medium"
              >
                제거
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// -------------------------------------------
// 매수대기
// -------------------------------------------

export function PendingBuyColumn({
  pendingBuy, errors, activeMarket, onCancelQueued, onCancelOrder, onProcessQueue,
}: {
  pendingBuy: OperationsResponse['pending_buy'];
  errors: Record<string, string>;
  activeMarket: 'kiwoom';
  /**
   * Task 8b: backported from the /trading TradeQueueWidget — cancels a
   * PENDING queued trade (DELETE /trading/queue/{id}). Distinct from
   * `onCancelOrder` below, which cancels an already-placed broker order.
   */
  onCancelQueued: (queueId: string) => void;
  onCancelOrder: (orderId: string) => void;
  /**
   * Task 8b: backported from the /trading TradeQueueWidget's manual
   * "Process" button (POST /trading/queue/process) — forces queue
   * processing instead of waiting for the next scheduled market-open tick.
   */
  onProcessQueue: () => void;
}) {
  const { queue, open_orders: openOrders } = pendingBuy;
  const queueVisible = columnVisible(queue, 'queue', errors);
  const ordersVisible = columnVisible(openOrders, 'open_orders', errors);
  if (!queueVisible && !ordersVisible) return null;

  const count = (queue?.length ?? 0) + (openOrders?.length ?? 0);
  const queueFailed = queue === null && errors.queue != null;
  const ordersFailed = openOrders === null && errors.open_orders != null;
  const anyFailed = queueFailed || ordersFailed;
  const failReason = errors.queue ?? errors.open_orders;

  return (
    <div className={COLUMN_WRAP}>
      <div
        className="flex items-center justify-between gap-2 text-[10px] text-muted font-semibold tracking-wide px-2.5 py-1.5 border-b border-hairline sticky top-0 bg-card flex-none"
        title={anyFailed ? failReason : undefined}
      >
        <span>{anyFailed ? <span className="text-down">매수대기 · 조회 실패</span> : `매수대기 · ${count}`}</span>
        {!queueFailed && (queue?.length ?? 0) > 0 && (
          <button
            type="button"
            onClick={onProcessQueue}
            title="큐를 즉시 처리합니다 (다음 장 개시를 기다리지 않음)"
            className="text-accent font-medium normal-case tracking-normal"
          >
            Process
          </button>
        )}
      </div>
      {(queue ?? []).map((raw, i) => {
        const q = raw as Record<string, unknown>;
        const id = q.id as string;
        const ticker = (q.ticker as string) ?? '';
        const name = (q.stock_name as string | null) ?? ticker;
        const action = q.action as string | undefined;
        const quantity = q.quantity as number | null;
        const entry = q.entry_price as number | null;
        return (
          <div key={id ?? i} className={CARD}>
            <div className="font-semibold flex items-center gap-1.5">
              {name}
              <span className="text-[9px] px-1 py-px rounded bg-warn/10 text-warn font-medium">대기</span>
            </div>
            <div className="text-muted">
              {action ?? DASH} {fmtInt(quantity)}주 @{fmtPrice(entry, activeMarket)}
            </div>
            <button type="button" onClick={() => onCancelQueued(id)} className="text-dim hover:text-down font-medium mt-1">
              대기 취소
            </button>
          </div>
        );
      })}
      {(openOrders ?? []).map((o) => (
        <div key={o.order_id} className={CARD}>
          <div className="font-semibold">{o.stk_nm || o.stk_cd}</div>
          <div className="text-muted">
            미체결 {fmtInt(o.remaining_quantity)}주 @{fmtPrice(o.price, activeMarket)}
          </div>
          <button
            type="button"
            onClick={() => onCancelOrder(o.order_id)}
            className="text-dim hover:text-down font-medium mt-1"
          >
            주문 취소
          </button>
        </div>
      ))}
    </div>
  );
}

// -------------------------------------------
// 보유
// -------------------------------------------

export function HoldingColumn({
  items, errors, activeMarket, navigate,
}: {
  items: OperationsResponse['holding'];
  errors: Record<string, string>;
  activeMarket: 'kiwoom';
  navigate: (path: string) => void;
}) {
  if (!columnVisible(items, 'holding', errors)) return null;
  return (
    <div className={COLUMN_WRAP}>
      <ColumnHeader label="보유" items={items} errorKey="holding" errors={errors} />
      {(items ?? []).map((h, i) => (
        <div
          key={`${h.ticker}-${i}`}
          className={`${CARD} cursor-pointer hover:bg-elevated/40`}
          onClick={() => navigate('/positions')}
        >
          <div className="font-semibold">{h.name || h.ticker}</div>
          <div className="text-muted">
            {fmtInt(h.quantity)}주 · 평단 {fmtPrice(h.avg_price, activeMarket)} · 현재 {fmtPrice(h.current_price, activeMarket)}
          </div>
          <div className={pnlColor(h.pnl)}>
            {fmtInt(h.pnl)} ({fmtPct(h.pnl_pct)})
          </div>
          <div className="text-dim">
            STOP {h.stop_loss != null ? fmtPrice(h.stop_loss, activeMarket) : DASH} · TAKE {h.take_profit != null ? fmtPrice(h.take_profit, activeMarket) : DASH}
          </div>
        </div>
      ))}
    </div>
  );
}

// -------------------------------------------
// 오늘체결
// -------------------------------------------

function formatFillTime(hhmmss: string): string {
  if (hhmmss.length < 4) return hhmmss;
  return `${hhmmss.slice(0, 2)}:${hhmmss.slice(2, 4)}`;
}

export function TodayFillsColumn({
  items, errors, activeMarket, navigate,
}: {
  items: OperationsResponse['today_fills'];
  errors: Record<string, string>;
  activeMarket: 'kiwoom';
  navigate: (path: string) => void;
}) {
  if (!columnVisible(items, 'today_fills', errors)) return null;
  return (
    <div className={COLUMN_WRAP}>
      <ColumnHeader label="오늘체결" items={items} errorKey="today_fills" errors={errors} />
      {(items ?? []).map((f, i) => (
        <div
          key={`${f.ticker}-${i}`}
          className={`${CARD} cursor-pointer hover:bg-elevated/40`}
          onClick={() => navigate('/trades')}
        >
          <div className="font-semibold">{f.name || f.ticker}</div>
          <div className="text-muted">
            {f.side === 'buy' ? '매수' : '매도'} {fmtInt(f.quantity)}주 @{fmtPrice(f.price, activeMarket)} · {formatFillTime(f.time)}
          </div>
        </div>
      ))}
    </div>
  );
}

// -------------------------------------------
// Shared action handlers — exported so FunnelPanel's WATCHLIST + PIPELINE
// sections dispatch the exact same mutations (convertWatchToQueue/
// removeFromWatchList/cancelQueuedTrade/processTradeQueue/cancelKRStockOrder/
// cancelKRStockSession/startKRStockAnalysis-via-useStartAnalysis) against the
// ONE `refetch` from `useOperations()`, instead of re-deriving the wiring.
// `submitApproval` is deliberately NOT called from here (Task 7, P2
// funnel-consolidation) — approve/reject/cancel of an awaiting proposal is
// handled EXCLUSIVELY by the global OrderTicketRail now; `handleFocusAwaiting`
// below only navigates the user there instead of duplicating the decision.
//
// Task 8b: `handleReanalyzeWatch`/`handleCancelQueued`/`handleProcessQueue`
// are backported from the now-removed /trading WatchListWidget/
// TradeQueueWidget — same client fns those widgets called
// (startKRStockAnalysis via useStartAnalysis, cancelQueuedTrade,
// processTradeQueue), just dispatched from the shared columns instead.
// -------------------------------------------

export function useOperationsActions(refetch: () => void, navigate: (path: string) => void) {
  const injectAwaitingKiwoomSession = useStore((s) => s.injectAwaitingKiwoomSession);
  const startAnalysis = useStartAnalysis();
  const [actionError, setActionError] = useState<string | null>(null);

  const handleCancelAnalysis = useCallback(async (sessionId: string) => {
    try {
      await cancelKRStockSession(sessionId);
      setActionError(null);
    } catch (e) {
      setActionError(`분석 취소 실패: ${e instanceof Error ? e.message : '액션 실패'}`);
    } finally {
      refetch();
    }
  }, [refetch]);

  // Task 7: routes an awaiting session into the ONE authoritative approval
  // surface (OrderTicketRail) instead of submitting approve/reject/cancel
  // directly from this read-only summary column.
  //
  // T7 review HIGH #1 fix: this used to only switch the ACTIVE session id
  // and trust that session's own local cache to already carry the right
  // tradeProposal/awaitingApproval — which silently no-ops on a cache miss
  // (setActiveKiwoomSession returns unchanged state when the session isn't
  // in kiwoom.sessions[], stranding the approval with NO error). Fixed by
  // seeding the store straight from the ROW's own data (id/ticker/name/
  // proposal/auto_approve_at — everything the poll already gave us) via
  // injectAwaitingKiwoomSession, so the click NEVER depends on local cache
  // state. If the row itself lacks a proposal (a genuine state-inconsistency
  // case — see `actionable`), focusing can't produce a renderable ticket;
  // surface that honestly instead of pretending it worked.
  const handleFocusAwaiting = useCallback((row: OperationsAwaiting) => {
    if (!row.proposal) {
      setActionError('제안 데이터가 없어 주문 레일에 표시할 수 없습니다 (취소는 워크플로 화면에서 가능)');
    } else {
      const seed = {
        sessionId: row.session_id, ticker: row.ticker, name: row.name,
        proposal: row.proposal, autoApproveAt: row.auto_approve_at,
      };
      injectAwaitingKiwoomSession(seed);
    }
    navigate(`/workflow/${row.session_id}`);
  }, [injectAwaitingKiwoomSession, navigate, setActionError]);

  const handleConvertWatch = useCallback(async (watchId: string) => {
    try {
      await convertWatchToQueue({ watch_id: watchId });
      setActionError(null);
    } catch (e) {
      setActionError(`큐 전환 실패: ${e instanceof Error ? e.message : '액션 실패'}`);
    } finally {
      refetch();
    }
  }, [refetch]);

  const handleRemoveWatch = useCallback(async (watchId: string) => {
    try {
      await removeFromWatchList(watchId);
      setActionError(null);
    } catch (e) {
      setActionError(`감시 제거 실패: ${e instanceof Error ? e.message : '액션 실패'}`);
    } finally {
      refetch();
    }
  }, [refetch]);

  // Task 8b: backported from WatchListWidget.handleReanalyze — starts a
  // fresh analysis session for an already-watched ticker and navigates
  // there, via the SAME shared `useStartAnalysis` hook DiscoverySection uses
  // (wraps startKRStockAnalysis + multi-session bookkeeping/WS wiring)
  // rather than reimplementing the widget's older, WS-less store call.
  const handleReanalyzeWatch = useCallback(async (ticker: string, name: string) => {
    try {
      // P4 T3: startAnalysis now returns {sessionId, duplicate, positionExists}
      // — a `duplicate` hit still navigates here (to the pre-existing session
      // useStartAnalysis just focused), it just doesn't spawn a second one.
      const result = await startAnalysis('kiwoom', ticker, name);
      setActionError(null);
      if (result.sessionId) navigate(`/workflow/${result.sessionId}`);
    } catch (e) {
      setActionError(`재분석 실패: ${e instanceof Error ? e.message : '액션 실패'}`);
    }
  }, [startAnalysis, navigate]);

  // Task 8b: backported from TradeQueueWidget.handleCancel — cancels a
  // PENDING queued trade. NOTE: this replaces a prior wiring of this same
  // "대기 취소" button to `dismissTrade` (DELETE /queue/{id}/dismiss), which
  // only succeeds for trades NOT pending/processing — but the queue items
  // rendered here (`data.pending_buy.queue`) are, by construction
  // (coordinator.get_trade_queue() default), ALWAYS pending/processing. That
  // wiring could never succeed; `cancelQueuedTrade` (DELETE /queue/{id}) is
  // the endpoint that actually works for an active queued trade.
  const handleCancelQueued = useCallback(async (queueId: string) => {
    try {
      await cancelQueuedTrade(queueId);
      setActionError(null);
    } catch (e) {
      setActionError(`대기 취소 실패: ${e instanceof Error ? e.message : '액션 실패'}`);
    } finally {
      refetch();
    }
  }, [refetch]);

  const handleCancelOrder = useCallback(async (orderId: string) => {
    try {
      await cancelKRStockOrder(orderId);
      setActionError(null);
    } catch (e) {
      setActionError(`주문 취소 실패: ${e instanceof Error ? e.message : '액션 실패'}`);
    } finally {
      refetch();
    }
  }, [refetch]);

  // Task 8b: backported from TradeQueueWidget.handleProcess — manually
  // triggers queue processing instead of waiting for the scheduled
  // market-open tick.
  const handleProcessQueue = useCallback(async () => {
    try {
      await processTradeQueue();
      setActionError(null);
    } catch (e) {
      setActionError(`대기열 처리 실패: ${e instanceof Error ? e.message : '액션 실패'}`);
    } finally {
      refetch();
    }
  }, [refetch]);

  return {
    actionError, setActionError,
    handleCancelAnalysis, handleFocusAwaiting, handleConvertWatch, handleRemoveWatch,
    handleReanalyzeWatch, handleCancelQueued, handleCancelOrder, handleProcessQueue,
  };
}

// -------------------------------------------
// Main
// -------------------------------------------

export function OperationsPanel() {
  const { activeMarket, data, state, err, refetch } = useOperations();
  const navigate = useNavigate();
  const {
    actionError, setActionError,
    handleCancelAnalysis, handleFocusAwaiting, handleConvertWatch, handleRemoveWatch,
    handleReanalyzeWatch, handleCancelQueued, handleCancelOrder, handleProcessQueue,
  } = useOperationsActions(refetch, navigate);

  if (state === 'loading') return <Awaiting label="운용 현황 로드 중…" />;
  if (state === 'error') return <Awaiting label={`운용 현황 오류 · ${err}`} />;
  if (!data) return <Awaiting label="운용 현황 로드 중…" />;

  return (
    <div className="flex flex-col h-full min-h-0">
      {actionError && (
        <div className="flex-none flex items-center justify-between gap-2 px-2.5 py-1 border-b border-hairline bg-down/5 text-down text-[11px]">
          <span>{actionError}</span>
          <button
            type="button"
            aria-label="오류 닫기"
            onClick={() => setActionError(null)}
            className="text-dim hover:text-down flex-none"
          >
            ✕
          </button>
        </div>
      )}
      <div className="flex flex-1 min-h-0 gap-0 overflow-x-auto">
        <AnalyzingColumn
          items={data.analyzing}
          errors={data.errors}
          navigate={navigate}
          onCancel={handleCancelAnalysis}
        />
        <AwaitingColumn
          items={data.awaiting}
          errors={data.errors}
          activeMarket={activeMarket}
          onFocus={handleFocusAwaiting}
        />
        <WatchingColumn
          items={data.watching}
          errors={data.errors}
          onConvert={handleConvertWatch}
          onRemove={handleRemoveWatch}
          onReanalyze={handleReanalyzeWatch}
        />
        <PendingBuyColumn
          pendingBuy={data.pending_buy}
          errors={data.errors}
          activeMarket={activeMarket}
          onCancelQueued={handleCancelQueued}
          onCancelOrder={handleCancelOrder}
          onProcessQueue={handleProcessQueue}
        />
        <HoldingColumn
          items={data.holding}
          errors={data.errors}
          activeMarket={activeMarket}
          navigate={navigate}
        />
        <TodayFillsColumn
          items={data.today_fills}
          errors={data.errors}
          activeMarket={activeMarket}
          navigate={navigate}
        />
      </div>
    </div>
  );
}
