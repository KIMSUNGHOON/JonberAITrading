/**
 * OrderTicketRail — the docked HITL order ticket on the right edge of the shell.
 * Idle: slim "NO PENDING ORDER" + the active market's session stage. Active
 * (Task 3+): a dense key-value approval ticket. Reuses the existing
 * submitApproval flow (Task 4) — presentation-only, no execution change.
 */
import { useState } from 'react';
import {
  useStore, selectTradeProposal, selectActiveSessionId, selectStatus, selectCurrentStage,
} from '@/store';
import {
  isTicketActive, getProposalSymbol, getProposalMarketType, formatCurrency,
  getRiskLevel, actionTextColor,
} from './orderTicket';
import { useMarketHours } from '@/hooks/useMarketHours';
import { MarkdownRenderer } from '@/components/common/MarkdownRenderer';

export function OrderTicketRail() {
  const proposal = useStore(selectTradeProposal);
  const sessionId = useStore(selectActiveSessionId);
  const status = useStore(selectStatus);
  const currentStage = useStore(selectCurrentStage);

  const active = isTicketActive(proposal, sessionId);

  const [feedback, setFeedback] = useState('');
  const marketType = active ? getProposalMarketType(proposal!) : 'stock';
  const { status: marketStatus, countdownFormatted, nextEventFormatted } = useMarketHours({
    market: marketType === 'kiwoom' ? 'krx' : 'crypto',
    enableCountdown: true,
  });
  const isMarketClosed = marketType === 'kiwoom' && marketStatus && !marketStatus.is_open;
  const risk = active ? getRiskLevel(proposal!.risk_score) : null;

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
      {active && risk && (
        <div className="flex-1 flex flex-col gap-2 p-2.5 text-[12px]">
          {isMarketClosed && (
            <div className="rounded border border-hairline bg-elevated p-2 text-[11px]">
              <div className="text-warn font-medium">현재 장이 마감되어 있습니다</div>
              <div className="text-dim mt-0.5">이 주문은 다음 장 오픈 시 실행됩니다</div>
              <div className="mt-1 flex justify-between tabular-nums"><span className="text-dim">예상 실행</span><span className="text-ink">{nextEventFormatted}</span></div>
              <div className="flex justify-between tabular-nums"><span className="text-dim">대기</span><span className="text-warn">{countdownFormatted}</span></div>
            </div>
          )}
          <div className={`inline-flex items-center gap-1.5 self-start rounded border border-hairline bg-elevated px-2 py-1 font-bold ${actionTextColor(proposal!.action)}`}>
            {proposal!.action.toUpperCase()}
          </div>
          <TicketRow label="SYMBOL" value={getProposalSymbol(proposal!)} />
          <TicketRow label="QTY" value={proposal!.quantity.toString()} num />
          <TicketRow label="ENTRY" value={formatCurrency(proposal!.entry_price, marketType)} num />
          <TicketRow label="STOP" value={formatCurrency(proposal!.stop_loss, marketType)} num valueColor="text-down" />
          <TicketRow label="TAKE" value={formatCurrency(proposal!.take_profit, marketType)} num valueColor="text-up" />
          <div className="mt-1">
            <div className="flex justify-between text-[11px]">
              <span className="text-dim">RISK</span>
              <span className={`font-medium ${risk.textColor}`}><span>{risk.label}</span> · {proposal!.risk_score}/10</span>
            </div>
            <div className="mt-1 h-1.5 bg-elevated rounded-full overflow-hidden">
              <div className={`h-full rounded-full ${risk.barColor}`} style={{ width: `${(proposal!.risk_score / 10) * 100}%` }} />
            </div>
          </div>
          {proposal!.rationale && (
            <div className="mt-1 rounded border border-hairline bg-elevated p-2 max-h-40 overflow-y-auto text-[11px]">
              <MarkdownRenderer content={proposal!.rationale} compact />
            </div>
          )}
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="Feedback (reject reason)…"
            className="mt-1 w-full h-16 resize-none rounded border border-hairline bg-canvas px-2 py-1 text-[11px] text-ink placeholder:text-dim"
          />
          <div className="flex gap-2 mt-1">
            <button type="button" className="flex-1 rounded border border-hairline bg-elevated py-1.5 text-warn font-medium">REJECT</button>
            <button type="button" className="flex-1 rounded border border-hairline bg-elevated py-1.5 text-up font-medium">APPROVE</button>
          </div>
          <button type="button" className="text-[11px] text-dim hover:text-ink py-1">Cancel Analysis</button>
        </div>
      )}
    </aside>
  );
}

function TicketRow({ label, value, num, valueColor = 'text-ink' }: {
  label: string; value: string; num?: boolean; valueColor?: string;
}) {
  return (
    <div className="flex justify-between items-baseline">
      <span className="text-[11px] text-dim">{label}</span>
      <span className={`${valueColor} ${num ? 'tabular-nums' : ''}`}>{value}</span>
    </div>
  );
}
