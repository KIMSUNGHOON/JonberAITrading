/**
 * Order-ticket domain logic (pure, no JSX). Consumed by OrderTicketRail.
 * Symbol/market/currency helpers are ported from the retired ApprovalDialog.
 */
import type {
  CoinTradeProposal, KRStockTradeProposal,
  ApprovalRequest, ApprovalDecision,
} from '@/types';

export type AnyTradeProposal = CoinTradeProposal | KRStockTradeProposal;

export function getProposalSymbol(proposal: AnyTradeProposal): string {
  if ('stk_cd' in proposal && proposal.stk_cd) {
    const k = proposal as KRStockTradeProposal;
    return k.stk_nm || k.stk_cd;
  }
  if ('market' in proposal && proposal.market) return proposal.market;
  return 'UNKNOWN';
}

export function getProposalMarketType(proposal: AnyTradeProposal): 'coin' | 'kiwoom' {
  if ('stk_cd' in proposal) return 'kiwoom';
  return 'coin';
}

export function formatCurrency(
  value: number | null | undefined,
  _marketType: 'coin' | 'kiwoom',
): string {
  if (value === null || value === undefined) return 'N/A';
  return `₩${value.toLocaleString('ko-KR')}`;
}

/** Risk 0-10 → dense-terminal tokens (green→amber→red = up→warn→down, NOT accent). */
export function getRiskLevel(score: number): { label: string; textColor: string; barColor: string } {
  if (score <= 3) return { label: 'Low Risk', textColor: 'text-up', barColor: 'bg-up' };
  if (score <= 6) return { label: 'Medium Risk', textColor: 'text-warn', barColor: 'bg-warn' };
  return { label: 'High Risk', textColor: 'text-down', barColor: 'bg-down' };
}

/** Directional trade-action → pnl token (app-wide ACTION convention). */
export function actionTextColor(action: string): string {
  const a = action.toUpperCase();
  if (a === 'BUY' || a === 'ADD') return 'text-up';
  if (a === 'SELL' || a === 'REDUCE') return 'text-down';
  return 'text-muted';
}

export function isTicketActive(
  proposal: AnyTradeProposal | null | undefined,
  sessionId: string | null | undefined,
): boolean {
  if (!proposal || !sessionId) return false;
  return getProposalSymbol(proposal) !== 'UNKNOWN';
}

export function buildApprovalRequest(
  sessionId: string,
  decision: ApprovalDecision,
  feedback: string,
): ApprovalRequest {
  return { session_id: sessionId, decision, feedback: feedback.trim() || undefined };
}
