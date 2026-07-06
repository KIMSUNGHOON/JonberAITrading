/**
 * OrderTicketRail — the docked HITL order ticket on the right edge of the shell.
 * Idle: slim "NO PENDING ORDER" + the active market's session stage. Active
 * (Task 3+): a dense key-value approval ticket. Reuses the existing
 * submitApproval flow (Task 4) — presentation-only, no execution change.
 */
import {
  useStore, selectTradeProposal, selectActiveSessionId, selectStatus, selectCurrentStage,
} from '@/store';
import { isTicketActive } from './orderTicket';

export function OrderTicketRail() {
  const proposal = useStore(selectTradeProposal);
  const sessionId = useStore(selectActiveSessionId);
  const status = useStore(selectStatus);
  const currentStage = useStore(selectCurrentStage);

  const active = isTicketActive(proposal, sessionId);

  return (
    <aside className="w-64 flex-none border-l border-hairline bg-card flex flex-col min-h-0 overflow-y-auto">
      <div className="flex-none px-3 py-2 border-b border-hairline text-[11px] font-semibold uppercase tracking-wide text-muted">
        Order
      </div>
      {!active && (
        <div className="flex-1 flex flex-col items-center justify-center gap-1 p-4 text-center">
          <div className="text-dim text-[13px]">NO PENDING ORDER</div>
          <div className="text-[11px] text-dim tabular-nums">
            {currentStage || status || '—'}
          </div>
        </div>
      )}
      {/* active ticket → Task 3 */}
    </aside>
  );
}
