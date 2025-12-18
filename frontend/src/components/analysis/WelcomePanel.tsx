/**
 * Welcome Panel Component
 *
 * Displayed when no analysis is active.
 */

import { Activity, BarChart3, Brain, Shield } from 'lucide-react';

export function WelcomePanel() {
  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="max-w-2xl text-center">
        {/* Logo */}
        <div className="w-20 h-20 mx-auto mb-6 bg-blue-600/20 rounded-2xl flex items-center justify-center">
          <Activity className="w-10 h-10 text-blue-400" />
        </div>

        {/* Title */}
        <h1 className="text-3xl font-bold mb-4">
          Welcome to{' '}
          <span className="text-gradient">Agentic Trading</span>
        </h1>

        {/* Description */}
        <p className="text-gray-400 mb-8 text-lg">
          AI-powered market analysis with human-in-the-loop approval.
          Enter a ticker symbol to start comprehensive analysis.
        </p>

        {/* Features */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          <FeatureCard
            icon={<Brain className="w-6 h-6" />}
            title="Multi-Agent Analysis"
            description="Technical, fundamental, and sentiment analysis by specialized AI agents"
          />
          <FeatureCard
            icon={<BarChart3 className="w-6 h-6" />}
            title="Real-time Charts"
            description="Interactive candlestick charts with moving averages and indicators"
          />
          <FeatureCard
            icon={<Shield className="w-6 h-6" />}
            title="Risk Management"
            description="Automated risk assessment with stop-loss and position sizing"
          />
        </div>

        {/* Getting Started */}
        <div className="bg-surface-light rounded-xl p-6 text-left">
          <h2 className="font-semibold mb-3">Getting Started</h2>
          <ol className="space-y-2 text-sm text-gray-400">
            <li className="flex items-start gap-2">
              <span className="w-5 h-5 rounded-full bg-blue-600 text-white text-xs flex items-center justify-center flex-shrink-0 mt-0.5">
                1
              </span>
              <span>Enter a stock ticker in the sidebar (e.g., AAPL, TSLA, NVDA)</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="w-5 h-5 rounded-full bg-blue-600 text-white text-xs flex items-center justify-center flex-shrink-0 mt-0.5">
                2
              </span>
              <span>Watch as AI agents analyze the stock from multiple perspectives</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="w-5 h-5 rounded-full bg-blue-600 text-white text-xs flex items-center justify-center flex-shrink-0 mt-0.5">
                3
              </span>
              <span>Review the trade proposal and approve or reject the recommendation</span>
            </li>
          </ol>
        </div>
      </div>
    </div>
  );
}

interface FeatureCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
}

function FeatureCard({ icon, title, description }: FeatureCardProps) {
  return (
    <div className="bg-surface-light rounded-xl p-4 text-left">
      <div className="w-10 h-10 rounded-lg bg-blue-600/20 text-blue-400 flex items-center justify-center mb-3">
        {icon}
      </div>
      <h3 className="font-medium mb-1">{title}</h3>
      <p className="text-sm text-gray-400">{description}</p>
    </div>
  );
}
