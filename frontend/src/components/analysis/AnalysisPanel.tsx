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

interface AnalysisPanelProps {
  analyses: AnalysisSummary[];
}

export function AnalysisPanel({ analyses }: AnalysisPanelProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {analyses.map((analysis) => (
        <AnalysisCard key={analysis.agent} analysis={analysis} />
      ))}
    </div>
  );
}

interface AnalysisCardProps {
  analysis: AnalysisSummary;
}

function AnalysisCard({ analysis }: AnalysisCardProps) {
  const { agent, signal, confidence, summary } = analysis;

  const agentConfig = getAgentConfig(agent);
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
            <p className="text-xs text-gray-400">{agentConfig.description}</p>
          </div>
        </div>

        {/* Signal Badge */}
        <div
          className={`px-2 py-1 rounded text-xs font-medium flex items-center gap-1 ${signalConfig.className}`}
        >
          {signalConfig.icon}
          {signal.toUpperCase()}
        </div>
      </div>

      {/* Confidence Bar */}
      <div className="mb-3">
        <div className="flex items-center justify-between text-xs mb-1">
          <span className="text-gray-400">Confidence</span>
          <span className="font-medium">{Math.round(confidence * 100)}%</span>
        </div>
        <div className="h-2 bg-surface rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${signalConfig.barColor}`}
            style={{ width: `${confidence * 100}%` }}
          />
        </div>
      </div>

      {/* Summary */}
      <p className="text-sm text-gray-300 line-clamp-3">{summary}</p>
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
      icon: <BarChart3 className="w-5 h-5 text-gray-400" />,
      bgColor: 'bg-gray-500/20',
    }
  );
}

function getSignalConfig(signal: string) {
  const configs: Record<
    string,
    {
      icon: React.ReactNode;
      className: string;
      barColor: string;
    }
  > = {
    buy: {
      icon: <TrendingUp className="w-3 h-3" />,
      className: 'signal-buy',
      barColor: 'bg-bull',
    },
    sell: {
      icon: <TrendingDown className="w-3 h-3" />,
      className: 'signal-sell',
      barColor: 'bg-bear',
    },
    hold: {
      icon: <Minus className="w-3 h-3" />,
      className: 'signal-hold',
      barColor: 'bg-yellow-500',
    },
  };

  return (
    configs[signal.toLowerCase()] || {
      icon: <Minus className="w-3 h-3" />,
      className: 'signal-hold',
      barColor: 'bg-gray-500',
    }
  );
}
