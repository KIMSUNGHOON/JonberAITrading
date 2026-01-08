/**
 * Proposal Card Component
 *
 * Compact display of trade proposal in dashboard.
 */

import {
  TrendingUp,
  TrendingDown,
  Bell,
  ChevronRight,
} from 'lucide-react';
import { useStore } from '@/store';
import type { TradeProposal, CoinTradeProposal, KRStockTradeProposal } from '@/types';

// Union type for all proposal types
type AnyTradeProposal = TradeProposal | CoinTradeProposal | KRStockTradeProposal;

interface ProposalCardProps {
  proposal: AnyTradeProposal;
}

// Helper to get symbol from stock, coin, or kiwoom proposal
function getProposalSymbol(proposal: AnyTradeProposal): string {
  if ('ticker' in proposal) {
    return proposal.ticker;
  }
  if ('market' in proposal) {
    return proposal.market;
  }
  if ('stk_cd' in proposal) {
    return proposal.stk_cd;
  }
  return 'UNKNOWN';
}

// Helper to check if it's a coin proposal
function isCoinProposal(proposal: AnyTradeProposal): proposal is CoinTradeProposal {
  return 'market' in proposal;
}

// Helper to check if it's a kiwoom proposal
function isKiwoomProposal(proposal: AnyTradeProposal): proposal is KRStockTradeProposal {
  return 'stk_cd' in proposal;
}

export function ProposalCard({ proposal }: ProposalCardProps) {
  const setShowApprovalDialog = useStore((state) => state.setShowApprovalDialog);

  const isBuy = proposal.action === 'BUY';
  const riskLevel = proposal.risk_score <= 3 ? 'Low' : proposal.risk_score <= 6 ? 'Medium' : 'High';
  const isCoin = isCoinProposal(proposal);
  const isKiwoom = isKiwoomProposal(proposal);
  const symbol = getProposalSymbol(proposal);

  // Determine proposal type label
  const proposalTypeLabel = isCoin ? 'Coin' : isKiwoom ? 'Korean Stock' : 'Stock';

  return (
    <div
      className={`card cursor-pointer hover:border-yellow-500/50 transition-colors ${
        'border-yellow-500/30'
      }`}
      onClick={() => setShowApprovalDialog(true)}
    >
      <div className="flex items-center gap-4">
        {/* Alert Icon */}
        <div className="w-12 h-12 rounded-xl bg-yellow-500/20 flex items-center justify-center flex-shrink-0">
          <Bell className="w-6 h-6 text-yellow-500 animate-pulse" />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-semibold">{proposalTypeLabel} Trade Proposal</span>
            <span
              className={`px-2 py-0.5 rounded text-xs font-medium ${
                isBuy ? 'signal-buy' : 'signal-sell'
              }`}
            >
              {proposal.action.toUpperCase()}
            </span>
          </div>

          <div className="flex items-center gap-4 text-sm text-gray-400">
            <span className="flex items-center gap-1">
              {isBuy ? (
                <TrendingUp className="w-4 h-4 text-bull" />
              ) : (
                <TrendingDown className="w-4 h-4 text-bear" />
              )}
              {symbol}
            </span>
            <span>{proposal.quantity} {isCoin ? 'KRW' : isKiwoom ? '주' : 'shares'}</span>
            <span>{(isCoin || isKiwoom) ? '' : '$'}{proposal.entry_price?.toFixed(2) ?? 'N/A'}{(isCoin || isKiwoom) ? ' KRW' : ''}</span>
            <span className={
              proposal.risk_score <= 3
                ? 'text-bull'
                : proposal.risk_score <= 6
                ? 'text-yellow-500'
                : 'text-bear'
            }>
              {riskLevel} Risk
            </span>
          </div>
        </div>

        {/* Action Arrow */}
        <div className="flex items-center gap-2">
          <span className="text-sm text-yellow-500 font-medium">
            Review
          </span>
          <ChevronRight className="w-5 h-5 text-yellow-500" />
        </div>
      </div>
    </div>
  );
}
