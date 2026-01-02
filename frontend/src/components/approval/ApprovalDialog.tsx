/**
 * Approval Dialog Component
 *
 * Modal dialog for HITL trade approval.
 */

import { useState } from 'react';
import {
  X,
  CheckCircle2,
  RefreshCw,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Shield,
  DollarSign,
  Target,
  Loader2,
  Clock,
} from 'lucide-react';
import { useStore, selectTradeProposal, selectActiveSessionId } from '@/store';
import { submitApproval } from '@/api/client';
import { MarkdownRenderer } from '@/components/common/MarkdownRenderer';
import { useMarketHours } from '@/hooks/useMarketHours';
import type { TradeProposal, CoinTradeProposal, KRStockTradeProposal } from '@/types';

// Union type for all proposal types
type AnyTradeProposal = TradeProposal | CoinTradeProposal | KRStockTradeProposal;

// Helper to get symbol from stock, coin, or kiwoom proposal
function getProposalSymbol(proposal: AnyTradeProposal): string {
  // Check for kiwoom proposals first (Korean stocks use stk_cd)
  if ('stk_cd' in proposal && proposal.stk_cd) {
    const kiwoomProposal = proposal as KRStockTradeProposal;
    return kiwoomProposal.stk_nm || kiwoomProposal.stk_cd;
  }
  // Coin proposals use market
  if ('market' in proposal && proposal.market) {
    return proposal.market;
  }
  // US stock proposals use ticker
  if ('ticker' in proposal && proposal.ticker) {
    return proposal.ticker;
  }
  return 'UNKNOWN';
}

// Helper to detect market type from proposal
function getProposalMarketType(proposal: AnyTradeProposal): 'stock' | 'coin' | 'kiwoom' {
  if ('stk_cd' in proposal) {
    return 'kiwoom';
  }
  if ('market' in proposal) {
    return 'coin';
  }
  return 'stock';
}

// Helper to format currency based on market type
function formatCurrency(value: number | null | undefined, marketType: 'stock' | 'coin' | 'kiwoom'): string {
  if (value === null || value === undefined) return 'N/A';

  if (marketType === 'kiwoom' || marketType === 'coin') {
    // Korean Won formatting
    return `₩${value.toLocaleString('ko-KR')}`;
  }

  // US Dollar formatting
  return `$${value.toFixed(2)}`;
}

export function ApprovalDialog() {
  const proposal = useStore(selectTradeProposal);
  const sessionId = useStore(selectActiveSessionId);
  const setShowApprovalDialog = useStore((state) => state.setShowApprovalDialog);
  const setAwaitingApproval = useStore((state) => state.setAwaitingApproval);
  const setTradeProposal = useStore((state) => state.setTradeProposal);
  const setError = useStore((state) => state.setError);
  const addChatMessage = useStore((state) => state.addChatMessage);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedback, setFeedback] = useState('');
  const setStatus = useStore((state) => state.setStatus);

  // Don't render if no proposal or session
  if (!proposal || !sessionId) return null;

  // Check if proposal has a valid identifier (not UNKNOWN)
  // This prevents showing the dialog with incomplete data
  const symbol = getProposalSymbol(proposal);
  if (symbol === 'UNKNOWN') {
    console.log('[ApprovalDialog] Skipping render - proposal has no valid identifier:', proposal);
    return null;
  }

  const handleDecision = async (decision: 'approved' | 'rejected' | 'cancelled') => {
    setIsSubmitting(true);

    // Optimistic update: immediately close dialog and update state
    // This prevents WebSocket updates from reopening the dialog during the API call
    setShowApprovalDialog(false);
    setAwaitingApproval(false);

    // Store proposal info for chat message before potentially clearing it
    // Note: symbol is already computed above and validated (not UNKNOWN)
    const action = proposal.action.toUpperCase();
    const quantity = proposal.quantity;

    // Clear proposal immediately for cancelled
    if (decision === 'cancelled') {
      setTradeProposal(null);
      setStatus('cancelled');
    } else if (decision === 'rejected') {
      setTradeProposal(null);
    }

    try {
      await submitApproval({
        session_id: sessionId,
        decision,
        feedback: feedback.trim() || undefined,
      });

      // Add chat message on success
      let chatContent = '';
      if (decision === 'approved') {
        chatContent = `Trade approved: ${action} ${quantity} ${symbol}`;
      } else if (decision === 'rejected') {
        chatContent = `Trade rejected - Re-analyzing with feedback${feedback ? `: "${feedback}"` : '...'}`;
      } else {
        chatContent = `Analysis cancelled for ${symbol}`;
      }
      addChatMessage({
        role: 'system',
        content: chatContent,
      });
    } catch (error) {
      // On error, revert the optimistic update
      setError(error instanceof Error ? error.message : 'Failed to submit decision');
      // Optionally restore proposal - but for simplicity, just show error
    } finally {
      setIsSubmitting(false);
    }
  };

  const isBuy = proposal.action === 'BUY';
  const riskLevel = getRiskLevel(proposal.risk_score);
  const marketType = getProposalMarketType(proposal);

  // Get market status for Korean stocks (kiwoom)
  const { status: marketStatus, countdownFormatted, nextEventFormatted } = useMarketHours({
    market: marketType === 'kiwoom' ? 'krx' : 'crypto',
    enableCountdown: true,
  });

  // Check if this is a market-hours dependent trade
  const isMarketClosed = marketType === 'kiwoom' && marketStatus && !marketStatus.is_open;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70"
        onClick={() => !isSubmitting && setShowApprovalDialog(false)}
      />

      {/* Dialog */}
      <div className="relative bg-surface-light rounded-2xl max-w-lg w-full shadow-2xl border border-border">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-yellow-500" />
            Trade Approval Required
          </h2>
          <button
            onClick={() => setShowApprovalDialog(false)}
            disabled={isSubmitting}
            className="p-2 hover:bg-surface rounded-lg"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6">
          {/* Market Closed Warning */}
          {isMarketClosed && (
            <div className="mb-4 p-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
              <div className="flex items-start gap-3">
                <Clock className="w-5 h-5 text-yellow-400 mt-0.5 flex-shrink-0" />
                <div>
                  <div className="text-sm font-medium text-yellow-400">
                    현재 장이 마감되어 있습니다
                  </div>
                  <div className="text-xs text-yellow-300/80 mt-1">
                    이 주문은 다음 장 오픈 시 실행됩니다
                  </div>
                  <div className="flex items-center gap-2 mt-2 text-xs">
                    <span className="text-gray-400">예상 실행 시간:</span>
                    <span className="text-white font-medium">{nextEventFormatted}</span>
                  </div>
                  <div className="flex items-center gap-2 mt-1 text-xs">
                    <span className="text-gray-400">대기 시간:</span>
                    <span className="text-yellow-400 font-medium">{countdownFormatted}</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Action Badge */}
          <div className="flex items-center justify-center mb-6">
            <div
              className={`flex items-center gap-2 px-6 py-3 rounded-xl ${
                isBuy
                  ? 'bg-bull/20 text-bull'
                  : 'bg-bear/20 text-bear'
              }`}
            >
              {isBuy ? (
                <TrendingUp className="w-6 h-6" />
              ) : (
                <TrendingDown className="w-6 h-6" />
              )}
              <span className="text-2xl font-bold">
                {proposal.action.toUpperCase()}
              </span>
            </div>
          </div>

          {/* Trade Details */}
          <div className="grid grid-cols-2 gap-4 mb-6">
            <DetailRow
              icon={<DollarSign className="w-4 h-4" />}
              label="Symbol"
              value={getProposalSymbol(proposal)}
            />
            <DetailRow
              icon={<Shield className="w-4 h-4" />}
              label="Quantity"
              value={proposal.quantity.toString()}
            />
            <DetailRow
              icon={<Target className="w-4 h-4" />}
              label="Entry Price"
              value={formatCurrency(proposal.entry_price, marketType)}
            />
            <DetailRow
              icon={<AlertTriangle className="w-4 h-4" />}
              label="Stop Loss"
              value={formatCurrency(proposal.stop_loss, marketType)}
              valueColor="text-bear"
            />
            <DetailRow
              icon={<CheckCircle2 className="w-4 h-4" />}
              label="Take Profit"
              value={formatCurrency(proposal.take_profit, marketType)}
              valueColor="text-bull"
            />
            <DetailRow
              icon={<Shield className="w-4 h-4" />}
              label="Risk Score"
              value={`${proposal.risk_score}/10`}
              valueColor={riskLevel.color}
            />
          </div>

          {/* Risk Indicator */}
          <div className="mb-6">
            <div className="flex items-center justify-between text-sm mb-2">
              <span className="text-gray-400">Risk Level</span>
              <span className={`font-medium ${riskLevel.color}`}>
                {riskLevel.label}
              </span>
            </div>
            <div className="h-2 bg-surface rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${riskLevel.barColor}`}
                style={{ width: `${(proposal.risk_score / 10) * 100}%` }}
              />
            </div>
          </div>

          {/* Rationale */}
          {proposal.rationale && (
            <div className="mb-6">
              <h3 className="text-sm font-medium text-gray-400 mb-2">
                Rationale
              </h3>
              <div className="text-sm bg-surface rounded-lg p-4 max-h-48 overflow-y-auto">
                <MarkdownRenderer content={proposal.rationale} compact />
              </div>
            </div>
          )}

          {/* Feedback Input */}
          <div className="mb-6">
            <label className="text-sm font-medium text-gray-400 block mb-2">
              Feedback (optional)
            </label>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="Add notes or reason for rejection..."
              className="input resize-none h-20"
              disabled={isSubmitting}
            />
          </div>

          {/* Action Buttons */}
          <div className="flex flex-col gap-3">
            <div className="flex gap-3">
              <button
                onClick={() => handleDecision('rejected')}
                disabled={isSubmitting}
                className="btn-warning flex-1 flex items-center justify-center gap-2"
              >
                {isSubmitting ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <>
                    <RefreshCw className="w-5 h-5" />
                    Re-analyze
                  </>
                )}
              </button>
              <button
                onClick={() => handleDecision('approved')}
                disabled={isSubmitting}
                className="btn-success flex-1 flex items-center justify-center gap-2"
              >
                {isSubmitting ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <>
                    <CheckCircle2 className="w-5 h-5" />
                    Approve
                  </>
                )}
              </button>
            </div>
            <button
              onClick={() => handleDecision('cancelled')}
              disabled={isSubmitting}
              className="w-full py-2 text-sm text-gray-400 hover:text-gray-300 hover:bg-surface rounded-lg transition-colors"
            >
              Cancel Analysis
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

interface DetailRowProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  valueColor?: string;
}

function DetailRow({ icon, label, value, valueColor = 'text-white' }: DetailRowProps) {
  return (
    <div className="flex items-center gap-2 bg-surface rounded-lg p-3">
      <span className="text-gray-400">{icon}</span>
      <div className="flex-1">
        <span className="text-xs text-gray-400 block">{label}</span>
        <span className={`font-medium ${valueColor}`}>{value}</span>
      </div>
    </div>
  );
}

function getRiskLevel(score: number) {
  if (score <= 3) {
    return { label: 'Low Risk', color: 'text-bull', barColor: 'bg-bull' };
  }
  if (score <= 6) {
    return { label: 'Medium Risk', color: 'text-yellow-500', barColor: 'bg-yellow-500' };
  }
  return { label: 'High Risk', color: 'text-bear', barColor: 'bg-bear' };
}
