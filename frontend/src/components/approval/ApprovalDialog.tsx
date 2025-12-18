/**
 * Approval Dialog Component
 *
 * Modal dialog for HITL trade approval.
 */

import { useState } from 'react';
import {
  X,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Shield,
  DollarSign,
  Target,
  Loader2,
} from 'lucide-react';
import { useShallow } from 'zustand/shallow';
import { useStore } from '@/store';
import { submitApproval } from '@/api/client';
import { MarkdownRenderer } from '@/components/common/MarkdownRenderer';

export function ApprovalDialog() {
  const { proposal } = useStore(
    useShallow((state) => ({
      proposal: state.tradeProposal,
    }))
  );
  const sessionId = useStore((state) => state.activeSessionId);
  const setShowApprovalDialog = useStore((state) => state.setShowApprovalDialog);
  const setAwaitingApproval = useStore((state) => state.setAwaitingApproval);
  const setTradeProposal = useStore((state) => state.setTradeProposal);
  const setError = useStore((state) => state.setError);
  const addChatMessage = useStore((state) => state.addChatMessage);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedback, setFeedback] = useState('');

  if (!proposal || !sessionId) return null;

  const handleDecision = async (decision: 'approved' | 'rejected') => {
    setIsSubmitting(true);

    try {
      await submitApproval({
        session_id: sessionId,
        decision,
        feedback: feedback.trim() || undefined,
      });

      // Update state
      setAwaitingApproval(false);
      if (decision === 'rejected') {
        setTradeProposal(null);
      }

      // Add chat message
      addChatMessage({
        role: 'system',
        content: decision === 'approved'
          ? `Trade approved: ${proposal.action.toUpperCase()} ${proposal.quantity} ${proposal.ticker}`
          : `Trade rejected${feedback ? `: ${feedback}` : ''}`,
      });

      setShowApprovalDialog(false);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to submit decision');
    } finally {
      setIsSubmitting(false);
    }
  };

  const isBuy = proposal.action === 'BUY';
  const riskLevel = getRiskLevel(proposal.risk_score);

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
              label="Ticker"
              value={proposal.ticker}
            />
            <DetailRow
              icon={<Shield className="w-4 h-4" />}
              label="Quantity"
              value={proposal.quantity.toString()}
            />
            <DetailRow
              icon={<Target className="w-4 h-4" />}
              label="Entry Price"
              value={`$${proposal.entry_price?.toFixed(2) ?? 'N/A'}`}
            />
            <DetailRow
              icon={<AlertTriangle className="w-4 h-4" />}
              label="Stop Loss"
              value={`$${proposal.stop_loss?.toFixed(2) ?? 'N/A'}`}
              valueColor="text-bear"
            />
            <DetailRow
              icon={<CheckCircle2 className="w-4 h-4" />}
              label="Take Profit"
              value={`$${proposal.take_profit?.toFixed(2) ?? 'N/A'}`}
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
                className="btn-danger flex-1 flex items-center justify-center gap-2"
              >
                {isSubmitting ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <>
                    <XCircle className="w-5 h-5" />
                    Reject
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
              onClick={() => setShowApprovalDialog(false)}
              disabled={isSubmitting}
              className="w-full py-2 text-sm text-gray-400 hover:text-gray-300 hover:bg-surface rounded-lg transition-colors"
            >
              Cancel (Decide Later)
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
