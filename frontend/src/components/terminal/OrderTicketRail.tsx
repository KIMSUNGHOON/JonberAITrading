/**
 * OrderTicketRail — the docked HITL order ticket on the right edge of the shell.
 * Idle: slim "NO PENDING ORDER" + the active market's session stage. Active
 * (Task 3+): a dense key-value approval ticket. Reuses the existing
 * submitApproval flow (Task 4) — presentation-only, no execution change.
 */
import { useEffect, useRef, useState } from 'react';
import {
  useStore, selectTradeProposal, selectActiveSessionId, selectStatus, selectCurrentStage,
  selectAwaitingApproval,
} from '@/store';
import {
  isTicketActive, getProposalSymbol, getProposalMarketType, formatCurrency,
  getRiskLevel, actionTextColor, buildApprovalRequest,
} from './orderTicket';
import { useMarketHours } from '@/hooks/useMarketHours';
import { MarkdownRenderer } from '@/components/common/MarkdownRenderer';
import { submitApproval } from '@/api/client';

export function OrderTicketRail() {
  const proposal = useStore(selectTradeProposal);
  const sessionId = useStore(selectActiveSessionId);
  const status = useStore(selectStatus);
  const currentStage = useStore(selectCurrentStage);
  const awaitingApproval = useStore(selectAwaitingApproval);
  const setAwaitingApproval = useStore((s) => s.setAwaitingApproval);
  const setStatus = useStore((s) => s.setStatus);
  const setError = useStore((s) => s.setError);
  const addChatMessage = useStore((s) => s.addChatMessage);

  // R3 autonomous mode: badge for the active market + auto-approve countdown
  // (kiwoom multi-session only — coin has no live WS status consumer).
  const activeMarket = useStore((s) => s.activeMarket);
  const tradingModes = useStore((s) => s.tradingModes);
  const autoApproveAt = useStore((s) =>
    s.activeMarket === 'kiwoom'
      ? s.kiwoom.sessions.find((x) => x.sessionId === s.kiwoom.activeSessionId)
          ?.autoApproveAt ?? null
      : null
  );
  const isAutonomous = tradingModes?.[activeMarket] === 'autonomous';

  const active = awaitingApproval && isTicketActive(proposal, sessionId);

  // Tick every 1s while an auto-approve deadline is pending so the countdown
  // re-renders; the remaining seconds are derived from Date.now() vs the ISO.
  const [nowTs, setNowTs] = useState(() => Date.now());
  useEffect(() => {
    if (!autoApproveAt) return;
    setNowTs(Date.now());
    const id = setInterval(() => setNowTs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [autoApproveAt]);
  const autoApproveSecondsLeft = autoApproveAt
    ? Math.max(0, Math.ceil((Date.parse(autoApproveAt) - nowTs) / 1000))
    : null;

  const [feedback, setFeedback] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const approveRef = useRef<HTMLButtonElement>(null);
  const marketType = active ? getProposalMarketType(proposal!) : 'kiwoom';
  const { status: marketStatus, countdownFormatted, nextEventFormatted } = useMarketHours({
    market: marketType === 'kiwoom' ? 'krx' : 'crypto',
    enableCountdown: true,
  });
  const isMarketClosed = marketType === 'kiwoom' && marketStatus && !marketStatus.is_open;
  const risk = active ? getRiskLevel(proposal!.risk_score) : null;

  // Keyboard: ⌘⏎ focuses Approve (deliberate 2-step; does NOT activate).
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        approveRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active]);

  // Decision handler — reuses the EXISTING submitApproval endpoint only.
  // Ported from ApprovalDialog.tsx:96-144 (decision submission, not execution).
  async function handleDecision(decision: 'approved' | 'rejected' | 'cancelled') {
    if (!sessionId) return;
    setIsSubmitting(true);
    setAwaitingApproval(false);
    const symbol = getProposalSymbol(proposal!);
    const label = `${proposal!.action.toUpperCase()} ${proposal!.quantity} ${symbol}`;
    if (decision === 'cancelled') {
      setStatus('cancelled');
    }
    try {
      await submitApproval(buildApprovalRequest(sessionId, decision, feedback));
      addChatMessage({
        role: 'system',
        content: decision === 'approved'
          ? `Trade approved: ${label}`
          : decision === 'rejected'
            ? `Trade rejected - Re-analyzing${feedback ? `: "${feedback}"` : '…'}`
            : `Analysis cancelled for ${symbol}`,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit decision');
    } finally {
      setIsSubmitting(false);
    }
  }

  const hasCases = active && (!!proposal!.bull_case || !!proposal!.bear_case);

  return (
    <aside
      className={`${active ? 'w-96' : 'w-40'} transition-[width] duration-200 flex-none border-l border-hairline bg-card flex flex-col min-h-0 overflow-y-auto`}
    >
      <div className="flex-none px-3 py-2 border-b border-hairline text-[11px] font-semibold uppercase tracking-wide text-muted flex items-center justify-between gap-2">
        <span>Order</span>
        {isAutonomous && (
          <span className="text-[10px] font-normal tracking-wide text-accent bg-elevated border border-hairline rounded px-1.5 py-px">
            AUTONOMOUS
          </span>
        )}
      </div>
      {!active && (
        <div className="flex-1 flex flex-col items-center justify-center gap-1 p-3 text-center">
          <div className="text-dim text-[13px]">NO PENDING ORDER</div>
          <div className="text-[11px] text-dim tabular-nums">
            {currentStage || status || '—'}
          </div>
        </div>
      )}
      {active && risk && (
        <div className="flex-1 flex flex-col min-h-0 gap-2 p-2.5 text-[12px]">
          {isMarketClosed && (
            <div className="flex-none rounded border border-hairline bg-elevated p-2 text-[11px]">
              <div className="text-warn font-medium">현재 장이 마감되어 있습니다</div>
              <div className="text-dim mt-0.5">이 주문은 다음 장 오픈 시 실행됩니다</div>
              <div className="mt-1 flex justify-between tabular-nums"><span className="text-dim">예상 실행</span><span className="text-ink">{nextEventFormatted}</span></div>
              <div className="flex justify-between tabular-nums"><span className="text-dim">대기</span><span className="text-warn">{countdownFormatted}</span></div>
            </div>
          )}
          {autoApproveAt !== null && (
            <div className="flex-none rounded border border-hairline bg-elevated px-2 py-1.5 text-[11px]">
              <div className="text-accent font-medium tabular-nums">
                {autoApproveSecondsLeft !== null && autoApproveSecondsLeft > 0
                  ? `자율 승인까지 ${autoApproveSecondsLeft}초`
                  : '자율 승인 처리 중…'}
              </div>
              <div className="text-dim mt-0.5">REJECT로 즉시 거부할 수 있습니다</div>
            </div>
          )}
          <div className={`flex-none inline-flex items-center gap-1.5 self-start rounded border border-hairline bg-elevated px-2 py-1 font-bold ${actionTextColor(proposal!.action)}`}>
            {proposal!.action.toUpperCase()}
          </div>

          {/* label-value ticket grid — right-aligned tabular-nums values */}
          <div className="flex-none grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded border border-hairline bg-elevated px-2 py-1.5">
            <TicketRow label="SYMBOL" value={getProposalSymbol(proposal!)} />
            <TicketRow label="QTY" value={proposal!.quantity.toString()} />
            <TicketRow label="ENTRY" value={formatCurrency(proposal!.entry_price, marketType)} />
            <TicketRow label="STOP" value={formatCurrency(proposal!.stop_loss, marketType)} valueColor="text-down" />
            <TicketRow label="TAKE" value={formatCurrency(proposal!.take_profit, marketType)} valueColor="text-up" />
          </div>

          <div className="flex-none">
            <div className="flex justify-between text-[11px]">
              <span className="text-dim">RISK</span>
              <span className={`font-medium ${risk.textColor}`}><span>{risk.label}</span> · {proposal!.risk_score}/10</span>
            </div>
            <div className="mt-1 h-1.5 bg-elevated rounded-full overflow-hidden">
              <div className={`h-full rounded-full ${risk.barColor}`} style={{ width: `${(proposal!.risk_score / 10) * 100}%` }} />
            </div>
          </div>

          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="Feedback (reject reason)…"
            className="flex-none w-full h-14 resize-none rounded border border-hairline bg-canvas px-2 py-1 text-[11px] text-ink placeholder:text-dim"
          />

          {/* actions — pinned above the scrollable rationale/case block below;
              the operator never has to scroll to find the veto button. */}
          <div className="flex-none flex flex-col gap-1">
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => handleDecision('rejected')}
                disabled={isSubmitting}
                className="flex-1 rounded border border-hairline bg-elevated py-1.5 text-warn font-medium"
              >
                REJECT
              </button>
              <button
                ref={approveRef}
                type="button"
                onClick={() => handleDecision('approved')}
                disabled={isSubmitting}
                className="flex-1 rounded border border-hairline bg-elevated py-1.5 text-up font-medium"
              >
                APPROVE
              </button>
            </div>
            <button
              type="button"
              onClick={() => handleDecision('cancelled')}
              disabled={isSubmitting}
              className="text-[11px] text-dim hover:text-ink py-1"
            >
              Cancel Analysis
            </button>
          </div>

          {/* rationale + bull/bear — the only part that scrolls */}
          <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-2">
            {proposal!.rationale && (
              <div className="rounded border border-hairline bg-elevated p-2 max-h-40 overflow-y-auto text-[12px] leading-relaxed">
                <div className="text-[10px] uppercase tracking-wide text-muted mb-1">Rationale</div>
                <MarkdownRenderer content={proposal!.rationale} compact />
              </div>
            )}
            {hasCases && (
              <details className="rounded border border-hairline bg-elevated group">
                <summary className="cursor-pointer select-none list-none px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted flex items-center justify-between">
                  <span>Bull / Bear Case</span>
                  <span className="text-dim transition-transform group-open:rotate-90">›</span>
                </summary>
                <div className="px-2 pb-2 flex flex-col gap-2">
                  {proposal!.bull_case && (
                    <div>
                      <div className="text-[10px] uppercase tracking-wide text-up mb-0.5">Bull</div>
                      <div className="text-[12px] leading-relaxed text-muted">
                        <MarkdownRenderer content={proposal!.bull_case} compact />
                      </div>
                    </div>
                  )}
                  {proposal!.bear_case && (
                    <div>
                      <div className="text-[10px] uppercase tracking-wide text-down mb-0.5">Bear</div>
                      <div className="text-[12px] leading-relaxed text-muted">
                        <MarkdownRenderer content={proposal!.bear_case} compact />
                      </div>
                    </div>
                  )}
                </div>
              </details>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}

function TicketRow({ label, value, valueColor = 'text-ink' }: {
  label: string; value: string; valueColor?: string;
}) {
  return (
    <>
      <span className="text-[11px] text-dim self-center">{label}</span>
      <span className={`text-right tabular-nums ${valueColor}`}>{value}</span>
    </>
  );
}
