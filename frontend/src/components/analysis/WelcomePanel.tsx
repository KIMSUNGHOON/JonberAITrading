/**
 * Welcome Panel Component
 *
 * Displayed when no analysis is active.
 * Includes popular coin widgets for quick access.
 */

import { Activity, BarChart3, Brain, Shield, Bitcoin, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { useStore } from '@/store';
import { useCoinTicker } from '@/hooks/useCoinTicker';
import { startCoinAnalysis } from '@/api/client';
import { createStoreWebSocket, type TradingWebSocket } from '@/api/websocket';
import { useState } from 'react';

// Popular coins for quick selection
const POPULAR_COINS = [
  { market: 'KRW-BTC', name: '비트코인', english: 'Bitcoin' },
  { market: 'KRW-ETH', name: '이더리움', english: 'Ethereum' },
  { market: 'KRW-XRP', name: '리플', english: 'Ripple' },
  { market: 'KRW-SOL', name: '솔라나', english: 'Solana' },
  { market: 'KRW-DOGE', name: '도지코인', english: 'Dogecoin' },
  { market: 'KRW-ADA', name: '에이다', english: 'Cardano' },
];

// WebSocket reference for coin sessions
let activeCoinWebSocket: TradingWebSocket | null = null;

export function WelcomePanel() {
  const activeMarket = useStore((state) => state.activeMarket);
  const upbitApiConfigured = useStore((state) => state.upbitApiConfigured);

  return (
    <div className="h-full overflow-y-auto p-4 md:p-8">
      <div className="max-w-4xl mx-auto">
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

        {/* Popular Coins Widget - Show only when coin market is active and API is configured */}
        {activeMarket === 'coin' && upbitApiConfigured && (
          <div className="mb-8">
            <h2 className="text-lg font-semibold mb-4 text-center">인기 코인 실시간 시세</h2>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {POPULAR_COINS.map((coin) => (
                <CoinWidget key={coin.market} {...coin} />
              ))}
            </div>
          </div>
        )}

        {/* Getting Started */}
        <div className="bg-surface-light rounded-xl p-6 text-left">
          <h2 className="font-semibold mb-3">Getting Started</h2>
          <ol className="space-y-2 text-sm text-gray-400">
            <li className="flex items-start gap-2">
              <span className="w-5 h-5 rounded-full bg-blue-600 text-white text-xs flex items-center justify-center flex-shrink-0 mt-0.5">
                1
              </span>
              <span>
                {activeMarket === 'coin'
                  ? 'Enter a coin ticker in the sidebar (e.g., BTC, ETH) or click a coin below'
                  : 'Enter a stock ticker in the sidebar (e.g., AAPL, TSLA, NVDA)'}
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="w-5 h-5 rounded-full bg-blue-600 text-white text-xs flex items-center justify-center flex-shrink-0 mt-0.5">
                2
              </span>
              <span>Watch as AI agents analyze from multiple perspectives</span>
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

// Coin Widget with real-time price
interface CoinWidgetProps {
  market: string;
  name: string;
  english: string;
}

function CoinWidget({ market, name }: CoinWidgetProps) {
  const { data, isLoading, error } = useCoinTicker(market);
  const [isStarting, setIsStarting] = useState(false);

  // Store actions for coin analysis
  const startCoinSession = useStore((state) => state.startCoinSession);
  const addCoinReasoning = useStore((state) => state.addCoinReasoning);
  const setCoinStatus = useStore((state) => state.setCoinStatus);
  const setCoinStage = useStore((state) => state.setCoinStage);
  const setCoinProposal = useStore((state) => state.setCoinProposal);
  const setCoinAwaitingApproval = useStore((state) => state.setCoinAwaitingApproval);
  const setCoinPosition = useStore((state) => state.setCoinPosition);
  const setCoinError = useStore((state) => state.setCoinError);
  const addChatMessage = useStore((state) => state.addChatMessage);

  const handleClick = async () => {
    if (isStarting) return;
    setIsStarting(true);

    try {
      const response = await startCoinAnalysis({ market });
      startCoinSession(response.session_id, market, name);

      addChatMessage({
        role: 'system',
        content: `Coin analysis started for ${name}`,
      });

      if (activeCoinWebSocket) {
        activeCoinWebSocket.disconnect();
      }

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      activeCoinWebSocket = createStoreWebSocket(response.session_id, {
        addReasoningEntry: addCoinReasoning,
        setStatus: setCoinStatus,
        setCurrentStage: setCoinStage,
        setTradeProposal: setCoinProposal as any,
        setAwaitingApproval: setCoinAwaitingApproval,
        setActivePosition: setCoinPosition,
        setError: setCoinError,
      });

      activeCoinWebSocket.connect();
    } catch (err) {
      setCoinError(err instanceof Error ? err.message : 'Failed to start analysis');
    } finally {
      setIsStarting(false);
    }
  };

  const formatPrice = (price: number) => {
    if (price >= 1000) {
      return price.toLocaleString('ko-KR');
    }
    return price.toFixed(price < 1 ? 4 : 2);
  };

  const formatPercent = (rate: number) => {
    const sign = rate > 0 ? '+' : '';
    return `${sign}${rate.toFixed(2)}%`;
  };

  const getChangeColor = (change: string) => {
    switch (change) {
      case 'RISE':
        return 'text-green-400';
      case 'FALL':
        return 'text-red-400';
      default:
        return 'text-gray-400';
    }
  };

  const ChangeIcon =
    data?.change === 'RISE'
      ? TrendingUp
      : data?.change === 'FALL'
        ? TrendingDown
        : Minus;

  return (
    <button
      onClick={handleClick}
      disabled={isStarting || isLoading}
      className="bg-surface-light hover:bg-surface border border-border hover:border-blue-500/50 rounded-xl p-4 text-left transition-all group disabled:opacity-60"
    >
      <div className="flex items-center gap-2 mb-2">
        <Bitcoin className="w-5 h-5 text-yellow-500" />
        <div>
          <span className="font-medium text-sm">{name}</span>
          <span className="text-xs text-gray-500 ml-1.5">{market.replace('KRW-', '')}</span>
        </div>
      </div>

      {isLoading || error || !data ? (
        <div className="animate-pulse">
          <div className="h-5 bg-surface rounded w-20 mb-1" />
          <div className="h-4 bg-surface rounded w-14" />
        </div>
      ) : (
        <>
          <div className="text-lg font-semibold">
            ₩{formatPrice(data.tradePrice)}
          </div>
          <div className={`flex items-center gap-1 ${getChangeColor(data.change)}`}>
            <ChangeIcon className="w-3 h-3" />
            <span className="text-sm">{formatPercent(data.changeRate)}</span>
          </div>
        </>
      )}

      <div className="mt-2 text-xs text-blue-400 opacity-0 group-hover:opacity-100 transition-opacity">
        Click to analyze →
      </div>
    </button>
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
