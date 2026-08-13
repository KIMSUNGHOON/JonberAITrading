/**
 * Analysis Panel Component
 *
 * Displays analysis results from different agents.
 */

import {
  TrendingUp,
  TrendingDown,
  Minus,
  BarChart3,
  Building2,
  MessageSquare,
  Shield,
} from 'lucide-react';
import type { AnalysisSummary } from '@/types';
import { pnlColor } from '@/utils/pnl';

interface AnalysisPanelProps {
  analyses: AnalysisSummary[];
}

export function AnalysisPanel({ analyses }: AnalysisPanelProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {analyses.map((analysis) => (
        <AnalysisCard key={analysis.agent_type} analysis={analysis} />
      ))}
    </div>
  );
}

interface AnalysisCardProps {
  analysis: AnalysisSummary;
}

function AnalysisCard({ analysis }: AnalysisCardProps) {
  const { agent_type, signal, confidence, summary } = analysis;

  const agentConfig = getAgentConfig(agent_type);
  const signalConfig = getSignalConfig(signal);

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <div
            className={`w-10 h-10 rounded-lg flex items-center justify-center ${agentConfig.bgColor}`}
          >
            {agentConfig.icon}
          </div>
          <div>
            <h3 className="font-medium">{agentConfig.label}</h3>
            <p className="text-xs text-muted">{agentConfig.description}</p>
          </div>
        </div>

        {/* Signal Badge — text-only chip on a neutral bg (trading colors are text-only, never a fill) */}
        <div
          className={`px-2 py-1 rounded border border-hairline bg-elevated text-xs font-medium flex items-center gap-1 ${signalConfig.textColor}`}
        >
          {signalConfig.icon}
          {signal.toUpperCase()}
        </div>
      </div>

      {/* Confidence Bar */}
      <div className="mb-3">
        <div className="flex items-center justify-between text-xs mb-1">
          <span className="text-muted">Confidence</span>
          <span className="font-medium tabular-nums">{Math.round(confidence * 100)}%</span>
        </div>
        <div className="h-2 bg-elevated rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${signalConfig.barColor}`}
            style={{ width: `${confidence * 100}%` }}
          />
        </div>
      </div>

      {/* Summary */}
      <p className="text-sm text-ink line-clamp-3">{summary}</p>
    </div>
  );
}

function getAgentConfig(agent: string) {
  const configs: Record<
    string,
    {
      label: string;
      description: string;
      icon: React.ReactNode;
      bgColor: string;
    }
  > = {
    technical: {
      label: 'Technical Analysis',
      description: 'Price patterns & indicators',
      icon: <BarChart3 className="w-5 h-5 text-blue-400" />,
      bgColor: 'bg-blue-500/20',
    },
    fundamental: {
      label: 'Fundamental Analysis',
      description: 'Financials & valuations',
      icon: <Building2 className="w-5 h-5 text-purple-400" />,
      bgColor: 'bg-purple-500/20',
    },
    sentiment: {
      label: 'Sentiment Analysis',
      description: 'News & social signals',
      icon: <MessageSquare className="w-5 h-5 text-yellow-400" />,
      bgColor: 'bg-yellow-500/20',
    },
    risk: {
      label: 'Risk Assessment',
      description: 'Risk evaluation',
      icon: <Shield className="w-5 h-5 text-red-400" />,
      bgColor: 'bg-red-500/20',
    },
  };

  return (
    configs[agent] || {
      label: agent,
      description: 'Analysis',
      icon: <BarChart3 className="w-5 h-5 text-muted" />,
      bgColor: 'bg-gray-500/20',
    }
  );
}

// Signal color routes through the shared P&L helper: buy is bullish (up),
// sell is bearish (down), hold is neutral (muted) — never a raw green/red.
function getSignalConfig(signal: string) {
  const configs: Record<
    string,
    {
      icon: React.ReactNode;
      textColor: string;
      barColor: string;
    }
  > = {
    buy: {
      icon: <TrendingUp className="w-3 h-3" />,
      textColor: pnlColor(1),
      barColor: 'bg-up',
    },
    sell: {
      icon: <TrendingDown className="w-3 h-3" />,
      textColor: pnlColor(-1),
      barColor: 'bg-down',
    },
    hold: {
      icon: <Minus className="w-3 h-3" />,
      textColor: 'text-muted',
      barColor: 'bg-dim',
    },
  };

  return (
    configs[signal.toLowerCase()] || {
      icon: <Minus className="w-3 h-3" />,
      textColor: 'text-muted',
      barColor: 'bg-dim',
    }
  );
}
