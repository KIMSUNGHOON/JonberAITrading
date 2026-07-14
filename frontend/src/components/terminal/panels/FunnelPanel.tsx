/**
 * FunnelPanel — 발견→감시→실행 (Discovery → Watchlist → Pipeline), assembled
 * into ONE vertical dashboard panel per P2 funnel-consolidation Phase 1
 * (P1-b, docs/superpowers/specs/2026-07-14-funnel-consolidation-design.md).
 *
 * Stacks three self-contained sections top-to-bottom so the flow that used
 * to be scattered across separate tiles (Scanner tile, Scratchpad tile,
 * Operations board) reads as a single funnel:
 *
 *  - DISCOVERY : <DiscoverySection/> (Task 4) — scanner controls/progress,
 *    scan-result rows, and the Scratchpad, each with [승격▲]/[분석▶].
 *  - WATCHLIST : the SERVER watch-list (ExecutionCoordinator), rendered via
 *    OperationsPanel's exported `WatchingColumn` — same data source
 *    (`useOperations` → `data.watching`) and the same mutations
 *    (`convertWatchToQueue`/`removeFromWatchList`, wired through the shared
 *    `useOperationsActions` hook) OperationsPanel already used. Not
 *    reimplemented.
 *  - PIPELINE  : the OperationsPanel board's other 5 columns (분석중·승인대기·
 *    매수대기·보유·오늘체결), reused verbatim via the same exported column
 *    components — so the per-section honest-degrade contract (a column
 *    that fails to load renders "조회 실패" on its own; the rest keep
 *    rendering; a null section is never faked as an empty "0") is
 *    inherited rather than re-derived.
 *
 * WATCHLIST and PIPELINE share the ONE `useOperations()` poll below (not two
 * independent polls) so a queue conversion in WATCHLIST is reflected in
 * PIPELINE's 매수대기 column on the very next shared refetch.
 *
 * Task 7 (P2 funnel-consolidation): PIPELINE's 승인대기 column (AwaitingColumn)
 * is a read-only summary, not a THIRD place to approve/reject a proposal —
 * see OperationsPanel.tsx's module doc and AwaitingColumn's doc comment. The
 * global OrderTicketRail is the one surface that calls submitApproval;
 * clicking a row here just focuses that session and navigates there.
 */
import { useNavigate } from 'react-router-dom';
import { DiscoverySection } from './DiscoverySection';
import {
  useOperations, useOperationsActions,
  WatchingColumn, AnalyzingColumn, AwaitingColumn, PendingBuyColumn,
  HoldingColumn, TodayFillsColumn,
} from './OperationsPanel';
import { Awaiting } from './shared';

const SECTION_LABEL = 'flex-none px-2.5 py-1 text-[10px] text-muted font-semibold tracking-wide uppercase border-b border-hairline bg-card sticky top-0';

export function FunnelPanel() {
  const navigate = useNavigate();
  const { activeMarket, data, state, err, refetch } = useOperations();
  const {
    actionError, setActionError,
    handleCancelAnalysis, handleFocusAwaiting, handleConvertWatch, handleRemoveWatch,
    handleDismissQueue, handleCancelOrder,
  } = useOperationsActions(refetch, navigate);

  const market = activeMarket === 'coin' ? 'coin' : 'kiwoom';

  return (
    <div className="flex flex-col h-full min-h-0 text-[11px]">
      {/* DISCOVERY */}
      <div className="flex-none flex flex-col min-h-0 border-b border-hairline" style={{ height: '42%' }}>
        <div className={SECTION_LABEL}>DISCOVERY · 발견</div>
        <div className="flex-1 min-h-0">
          <DiscoverySection />
        </div>
      </div>

      {/* WATCHLIST — server SSOT (ExecutionCoordinator), same data+actions as PIPELINE below */}
      <div className="flex-none flex flex-col min-h-0 border-b border-hairline" style={{ height: '24%' }}>
        <div className={SECTION_LABEL}>WATCHLIST · 감시</div>
        {actionError && (
          <div className="flex-none flex items-center justify-between gap-2 px-2.5 py-1 border-b border-hairline bg-down/5 text-down">
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
        {state === 'loading' && <Awaiting label="감시 리스트 로드 중…" />}
        {state === 'error' && <Awaiting label={`감시 리스트 오류 · ${err}`} />}
        {state === 'ready' && data && (
          <div className="flex flex-1 min-h-0">
            <WatchingColumn
              items={data.watching}
              errors={data.errors}
              onConvert={handleConvertWatch}
              onRemove={handleRemoveWatch}
            />
          </div>
        )}
      </div>

      {/* PIPELINE — OperationsPanel's 5 remaining columns, reused verbatim */}
      <div className="flex-1 min-h-0 flex flex-col">
        <div className={SECTION_LABEL}>PIPELINE · 실행</div>
        {state === 'loading' && <Awaiting label="파이프라인 로드 중…" />}
        {state === 'error' && <Awaiting label={`파이프라인 오류 · ${err}`} />}
        {state === 'ready' && data && (
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
              activeMarket={market}
              onFocus={handleFocusAwaiting}
            />
            <PendingBuyColumn
              pendingBuy={data.pending_buy}
              errors={data.errors}
              activeMarket={market}
              onDismiss={handleDismissQueue}
              onCancelOrder={handleCancelOrder}
            />
            <HoldingColumn
              items={data.holding}
              errors={data.errors}
              activeMarket={market}
              navigate={navigate}
            />
            <TodayFillsColumn
              items={data.today_fills}
              errors={data.errors}
              activeMarket={market}
              navigate={navigate}
            />
          </div>
        )}
      </div>
    </div>
  );
}
