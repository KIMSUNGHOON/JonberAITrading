/**
 * AnalysisDetailPage Component
 *
 * Shows detailed report for a completed analysis.
 * - Trade proposal summary
 * - Technical analysis details
 * - Fundamental analysis details
 * - Sentiment analysis details
 * - Risk assessment details
 * - Full reasoning log
 */

import { useMemo } from 'react';
import {
  ArrowLeft,
  FileText,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Brain,
  Shield,
  MessageSquare,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  Bitcoin,
  Building2,
  Activity,
  DollarSign,
  Newspaper,
  AlertOctagon,
} from 'lucide-react';
import { useStore, selectTickerHistory, selectKiwoomHistoryById, type MarketType, type TickerHistoryItem } from '@/store';
import { MarkdownRenderer } from '@/components/common/MarkdownRenderer';
import type {
  DetailedAnalysisResults,
  TechnicalAnalysisResult,
  FundamentalAnalysisResult,
  SentimentAnalysisResult,
  RiskAssessmentResult,
  TradeAction,
} from '@/types';

interface AnalysisDetailPageProps {
  sessionId?: string;
  onBack?: () => void;
}

// Market type icon component
function MarketIcon({ marketType, size = 20 }: { marketType: MarketType; size?: number }) {
  switch (marketType) {
    case 'stock':
      return <TrendingUp size={size} className="text-green-400" />;
    case 'coin':
      return <Bitcoin size={size} className="text-yellow-400" />;
    case 'kiwoom':
      return <Building2 size={size} className="text-blue-400" />;
  }
}

function getMarketLabel(marketType: MarketType): string {
  switch (marketType) {
    case 'stock': return 'US Stock';
    case 'coin': return 'Crypto';
    case 'kiwoom': return 'KR Stock';
  }
}

function formatDate(date: Date): string {
  const d = new Date(date);
  return d.toLocaleString('ko-KR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// Helper to get display name from history item
function getDisplayName(item: TickerHistoryItem): string {
  if ('stk_nm' in item && (item as { stk_nm?: string }).stk_nm) {
    return (item as { stk_nm: string }).stk_nm;
  }
  if ('koreanName' in item && (item as { koreanName?: string }).koreanName) {
    return (item as { koreanName: string }).koreanName;
  }
  return item.ticker;
}

// Helper to get action from history item
function getAction(item: TickerHistoryItem): string | null {
  if ('action' in item && (item as { action?: string }).action) {
    return (item as { action: string }).action;
  }
  return null;
}

// Signal color helper
function getSignalColor(signal?: string) {
  switch (signal?.toUpperCase()) {
    case 'BULLISH':
    case 'BUY':
      return 'text-green-400 bg-green-500/20';
    case 'BEARISH':
    case 'SELL':
      return 'text-red-400 bg-red-500/20';
    default:
      return 'text-gray-400 bg-gray-500/20';
  }
}

// Analysis card component
function AnalysisCard({
  icon,
  title,
  signal,
  confidence,
  summary,
  highlights,
  indicators,
  notAvailable = false,
}: {
  icon: React.ReactNode;
  title: string;
  signal?: string;
  confidence?: number;
  summary?: string;
  highlights?: string[];
  indicators?: React.ReactNode;
  notAvailable?: boolean;
}) {
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {icon}
          <h3 className="font-semibold">{title}</h3>
        </div>
        {signal && (
          <span className={`px-2 py-1 text-xs font-medium rounded ${getSignalColor(signal)}`}>
            {signal}
          </span>
        )}
      </div>

      {notAvailable ? (
        <p className="text-sm text-gray-500 italic">데이터 없음</p>
      ) : (
        <>
          {confidence !== undefined && confidence > 0 && (
            <div className="mb-3">
              <div className="flex items-center justify-between text-sm mb-1">
                <span className="text-gray-400">신뢰도</span>
                <span className="font-medium">{confidence.toFixed(0)}%</span>
              </div>
              <div className="h-2 bg-surface rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 transition-all"
                  style={{ width: `${Math.min(confidence, 100)}%` }}
                />
              </div>
            </div>
          )}

          {summary && (
            <p className="text-sm text-gray-300 mb-3">{summary}</p>
          )}

          {indicators && (
            <div className="mb-3">
              {indicators}
            </div>
          )}

          {highlights && highlights.length > 0 && (
            <div className="text-sm bg-surface rounded-lg p-3 max-h-36 overflow-y-auto">
              <ul className="space-y-1">
                {highlights.map((h, i) => (
                  <li key={i} className="text-gray-400 flex items-start gap-2">
                    <span className="text-blue-400 mt-1">•</span>
                    <span>{h}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// Technical Indicators Component
function TechnicalIndicators({ data }: { data: TechnicalAnalysisResult }) {
  const { indicators, priceAction } = data;

  return (
    <div className="grid grid-cols-2 gap-2 text-xs">
      {indicators.rsi !== null && (
        <div className="bg-surface rounded p-2">
          <span className="text-gray-500">RSI</span>
          <span className={`ml-2 font-medium ${
            indicators.rsi > 70 ? 'text-red-400' :
            indicators.rsi < 30 ? 'text-green-400' : 'text-gray-300'
          }`}>
            {indicators.rsi.toFixed(1)}
          </span>
        </div>
      )}
      {indicators.sma50 !== null && (
        <div className="bg-surface rounded p-2">
          <span className="text-gray-500">SMA50</span>
          <span className="ml-2 font-medium text-gray-300">
            ₩{indicators.sma50.toLocaleString('ko-KR')}
          </span>
        </div>
      )}
      {indicators.macd && (
        <div className="bg-surface rounded p-2">
          <span className="text-gray-500">MACD</span>
          <span className={`ml-2 font-medium ${
            (indicators.macd.histogram ?? 0) > 0 ? 'text-green-400' : 'text-red-400'
          }`}>
            {(indicators.macd.histogram ?? 0).toFixed(2)}
          </span>
        </div>
      )}
      {priceAction && (
        <div className="bg-surface rounded p-2">
          <span className="text-gray-500">변동</span>
          <span className={`ml-2 font-medium ${
            priceAction.changePercent24h > 0 ? 'text-green-400' :
            priceAction.changePercent24h < 0 ? 'text-red-400' : 'text-gray-300'
          }`}>
            {priceAction.changePercent24h > 0 ? '+' : ''}{priceAction.changePercent24h.toFixed(2)}%
          </span>
        </div>
      )}
    </div>
  );
}

// Fundamental Metrics Component
function FundamentalMetrics({ data }: { data: FundamentalAnalysisResult }) {
  const { metrics } = data;
  const financialHealth = data.financialHealth || 'unknown';

  const healthColor: Record<string, string> = {
    strong: 'text-green-400',
    moderate: 'text-yellow-400',
    weak: 'text-red-400',
    unknown: 'text-gray-400',
  };

  const healthLabel: Record<string, string> = {
    strong: '양호',
    moderate: '보통',
    weak: '취약',
    unknown: '알 수 없음',
  };

  const hasMetrics = metrics && (metrics.per != null || metrics.pbr != null || metrics.roe != null);

  return (
    <div className="space-y-2">
      {hasMetrics && (
        <div className="grid grid-cols-3 gap-2 text-xs">
          {metrics.per != null && (
            <div className="bg-surface rounded p-2 text-center">
              <div className="text-gray-500">PER</div>
              <div className="font-medium text-gray-300">{metrics.per.toFixed(1)}</div>
            </div>
          )}
          {metrics.pbr != null && (
            <div className="bg-surface rounded p-2 text-center">
              <div className="text-gray-500">PBR</div>
              <div className="font-medium text-gray-300">{metrics.pbr.toFixed(2)}</div>
            </div>
          )}
          {metrics.roe != null && (
            <div className="bg-surface rounded p-2 text-center">
              <div className="text-gray-500">ROE</div>
              <div className="font-medium text-gray-300">{metrics.roe.toFixed(1)}%</div>
            </div>
          )}
        </div>
      )}
      <div className="flex items-center gap-2 text-sm">
        <span className="text-gray-500">재무 건전성:</span>
        <span className={`font-medium ${healthColor[financialHealth] || healthColor.unknown}`}>
          {healthLabel[financialHealth] || '알 수 없음'}
        </span>
      </div>
    </div>
  );
}

// Sentiment Indicators Component
function SentimentIndicators({ data }: { data: SentimentAnalysisResult }) {
  const sentimentColor: Record<string, string> = {
    positive: 'text-green-400',
    neutral: 'text-gray-400',
    negative: 'text-red-400',
  };

  const sentimentLabel: Record<string, string> = {
    positive: '긍정적',
    neutral: '중립',
    negative: '부정적',
  };

  const sentiment = data.sentiment || 'neutral';
  const score = data.sentimentScore ?? 0;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="text-gray-500">시장 심리:</span>
        <span className={`font-medium ${sentimentColor[sentiment] || sentimentColor.neutral}`}>
          {sentimentLabel[sentiment] || '중립'} {score !== 0 && `(${score > 0 ? '+' : ''}${score.toFixed(0)})`}
        </span>
      </div>
      {data.newsCount > 0 && (
        <div className="text-xs text-gray-500">
          최근 뉴스 {data.newsCount}건 분석
        </div>
      )}
      {data.recentNews && data.recentNews.length > 0 && (
        <div className="bg-surface rounded p-2 max-h-24 overflow-y-auto">
          {data.recentNews.slice(0, 3).map((news, i) => (
            <div key={i} className="text-xs text-gray-400 truncate py-0.5">
              <span className={sentimentColor[news.sentiment] || sentimentColor.neutral}>●</span> {news.title}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Risk Factors Component
function RiskFactors({ data }: { data: RiskAssessmentResult }) {
  const riskColor: Record<string, string> = {
    low: 'text-green-400 bg-green-500/20',
    medium: 'text-yellow-400 bg-yellow-500/20',
    high: 'text-orange-400 bg-orange-500/20',
    very_high: 'text-red-400 bg-red-500/20',
  };

  const riskLabel: Record<string, string> = {
    low: '낮음',
    medium: '보통',
    high: '높음',
    very_high: '매우 높음',
  };

  const riskLevel = data.riskLevel || 'medium';

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm text-gray-500">리스크 수준:</span>
        <span className={`px-2 py-0.5 text-xs font-medium rounded ${riskColor[riskLevel] || riskColor.medium}`}>
          {riskLabel[riskLevel] || '보통'}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        {data.suggestedStopLoss != null && (
          <div className="bg-surface rounded p-2">
            <span className="text-gray-500">손절가</span>
            <span className="ml-2 font-medium text-red-400">
              ₩{data.suggestedStopLoss.toLocaleString('ko-KR')}
            </span>
          </div>
        )}
        {data.suggestedTakeProfit != null && (
          <div className="bg-surface rounded p-2">
            <span className="text-gray-500">목표가</span>
            <span className="ml-2 font-medium text-green-400">
              ₩{data.suggestedTakeProfit.toLocaleString('ko-KR')}
            </span>
          </div>
        )}
      </div>
      {data.factors && data.factors.length > 0 && (
        <div className="text-xs bg-surface rounded-lg p-2 max-h-24 overflow-y-auto">
          <ul className="space-y-1">
            {data.factors.slice(0, 3).map((f, i) => (
              <li key={i} className="text-gray-400 flex items-start gap-2">
                <span className={
                  f.impact === 'positive' ? 'text-green-400' :
                  f.impact === 'negative' ? 'text-red-400' : 'text-gray-400'
                }>•</span>
                <span>{f.description || f.name}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function AnalysisDetailPage({ sessionId: propSessionId, onBack }: AnalysisDetailPageProps) {
  const setCurrentView = useStore((state) => state.setCurrentView);
  const storeSessionId = useStore((state) => state.selectedSessionId);
  const history = useStore(selectTickerHistory);

  // Use prop sessionId if provided, otherwise use store's selectedSessionId
  const sessionId = propSessionId || storeSessionId;

  // Find the analysis by session ID
  const analysis = useMemo(() => {
    if (!sessionId) return null;
    return history.find((h) => h.sessionId === sessionId);
  }, [history, sessionId]);

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else {
      setCurrentView('analysis');
    }
  };

  // If no analysis found, show not found state
  if (!analysis) {
    return (
      <div className="h-full flex flex-col bg-surface">
        <div className="flex items-center gap-3 px-6 py-4 border-b border-border bg-surface-dark">
          <button
            onClick={handleBack}
            className="p-2 rounded-lg hover:bg-surface transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-gray-400" />
          </button>
          <h1 className="text-xl font-semibold">Analysis Detail</h1>
        </div>

        <div className="flex-1 flex items-center justify-center">
          <div className="text-center text-gray-500">
            <FileText className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p className="text-lg">Analysis not found</p>
            <p className="text-sm mt-2">
              The analysis may have been removed or expired
            </p>
            <button
              onClick={handleBack}
              className="mt-4 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-white text-sm"
            >
              Back to Analysis
            </button>
          </div>
        </div>
      </div>
    );
  }

  const displayName = getDisplayName(analysis);
  const action = getAction(analysis);
  const marketType: MarketType = 'market' in analysis ? 'coin' : 'stk_cd' in analysis ? 'kiwoom' : 'stock';

  // Get analysis results from the new structure (Phase 9)
  const analysisResults = 'analysisResults' in analysis
    ? (analysis as { analysisResults?: DetailedAnalysisResults }).analysisResults
    : null;

  // Extract individual analyses
  const technicalAnalysis = analysisResults?.technical ?? null;
  const fundamentalAnalysis = analysisResults?.fundamental ?? null;
  const sentimentAnalysis = analysisResults?.sentiment ?? null;
  const riskAssessment = analysisResults?.risk ?? null;

  // Get reasoning summary or log
  const reasoningSummary = 'reasoningSummary' in analysis
    ? (analysis as { reasoningSummary?: string }).reasoningSummary
    : null;

  // Check if we have any analysis data
  const hasAnalysisData = technicalAnalysis || fundamentalAnalysis || sentimentAnalysis || riskAssessment;

  // Get trade proposal from history if available
  const tradeProposal = 'tradeProposal' in analysis
    ? (analysis as { tradeProposal?: { action?: TradeAction; entry_price?: number; stop_loss?: number; take_profit?: number; rationale?: string } }).tradeProposal
    : null;

  return (
    <div className="h-full flex flex-col bg-surface">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-border bg-surface-dark">
        <button
          onClick={handleBack}
          className="p-2 rounded-lg hover:bg-surface transition-colors"
          title="Back to Analysis"
        >
          <ArrowLeft className="w-5 h-5 text-gray-400" />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <MarketIcon marketType={marketType} />
            <div>
              <h1 className="text-xl font-semibold">{displayName}</h1>
              <div className="flex items-center gap-2 text-sm text-gray-500">
                {displayName !== analysis.ticker && (
                  <span>{analysis.ticker}</span>
                )}
                <span className="px-2 py-0.5 text-xs bg-surface rounded">
                  {getMarketLabel(marketType)}
                </span>
                <span>·</span>
                <span>{formatDate(analysis.timestamp)}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Status & Action Badge */}
        <div className="flex items-center gap-2">
          {action && (
            <span
              className={`px-3 py-1.5 text-sm font-medium rounded-lg flex items-center gap-1 ${
                action === 'BUY'
                  ? 'bg-green-500/20 text-green-400'
                  : action === 'SELL'
                    ? 'bg-red-500/20 text-red-400'
                    : 'bg-gray-500/20 text-gray-400'
              }`}
            >
              {action === 'BUY' ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
              {action}
            </span>
          )}
          <span
            className={`px-3 py-1.5 text-sm rounded-lg flex items-center gap-1 ${
              analysis.status === 'completed'
                ? 'bg-green-500/20 text-green-400'
                : analysis.status === 'cancelled'
                  ? 'bg-yellow-500/20 text-yellow-400'
                  : 'bg-red-500/20 text-red-400'
            }`}
          >
            {analysis.status === 'completed' ? (
              <CheckCircle2 className="w-4 h-4" />
            ) : (
              <XCircle className="w-4 h-4" />
            )}
            {analysis.status}
          </span>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto space-y-6">
          {/* Summary Card */}
          <div className="card bg-gradient-to-r from-blue-600/10 to-purple-600/10 border-blue-500/30">
            <h2 className="text-lg font-semibold mb-4">Analysis Summary</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="text-center">
                <div className="text-2xl font-bold text-blue-400">
                  {action || 'HOLD'}
                </div>
                <div className="text-xs text-gray-500 mt-1">Recommendation</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-green-400">
                  {analysis.status === 'completed' ? '100%' : '-'}
                </div>
                <div className="text-xs text-gray-500 mt-1">Complete</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-purple-400">
                  {getMarketLabel(marketType)}
                </div>
                <div className="text-xs text-gray-500 mt-1">Market</div>
              </div>
              <div className="text-center">
                <div className="flex items-center justify-center gap-1 text-2xl font-bold text-gray-400">
                  <Clock className="w-5 h-5" />
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  {formatDate(analysis.timestamp).split(' ').slice(-2).join(' ')}
                </div>
              </div>
            </div>
          </div>

          {/* Trade Proposal Card (if available) */}
          {tradeProposal && (
            <div className="card bg-gradient-to-r from-green-600/10 to-blue-600/10 border-green-500/30">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Activity className="w-5 h-5 text-green-400" />
                거래 제안
              </h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                {tradeProposal.entry_price && (
                  <div className="text-center">
                    <div className="text-lg font-bold text-blue-400">
                      ₩{tradeProposal.entry_price.toLocaleString('ko-KR')}
                    </div>
                    <div className="text-xs text-gray-500">진입가</div>
                  </div>
                )}
                {tradeProposal.stop_loss && (
                  <div className="text-center">
                    <div className="text-lg font-bold text-red-400">
                      ₩{tradeProposal.stop_loss.toLocaleString('ko-KR')}
                    </div>
                    <div className="text-xs text-gray-500">손절가</div>
                  </div>
                )}
                {tradeProposal.take_profit && (
                  <div className="text-center">
                    <div className="text-lg font-bold text-green-400">
                      ₩{tradeProposal.take_profit.toLocaleString('ko-KR')}
                    </div>
                    <div className="text-xs text-gray-500">목표가</div>
                  </div>
                )}
              </div>
              {tradeProposal.rationale && (
                <div className="text-sm text-gray-300 bg-surface rounded-lg p-3">
                  <p className="font-medium text-gray-400 mb-1">분석 근거:</p>
                  {tradeProposal.rationale}
                </div>
              )}
            </div>
          )}

          {/* Analysis Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Technical Analysis */}
            <AnalysisCard
              icon={<BarChart3 className="w-5 h-5 text-blue-400" />}
              title="기술적 분석"
              signal={technicalAnalysis?.recommendation}
              confidence={technicalAnalysis?.confidence}
              summary={technicalAnalysis?.summary}
              indicators={technicalAnalysis ? <TechnicalIndicators data={technicalAnalysis} /> : undefined}
              highlights={technicalAnalysis?.signals}
              notAvailable={!technicalAnalysis}
            />

            {/* Fundamental Analysis */}
            <AnalysisCard
              icon={<DollarSign className="w-5 h-5 text-green-400" />}
              title="펀더멘털 분석"
              signal={fundamentalAnalysis?.recommendation}
              confidence={fundamentalAnalysis?.confidence}
              summary={fundamentalAnalysis?.summary}
              indicators={fundamentalAnalysis ? <FundamentalMetrics data={fundamentalAnalysis} /> : undefined}
              highlights={fundamentalAnalysis?.highlights}
              notAvailable={!fundamentalAnalysis}
            />

            {/* Sentiment Analysis */}
            <AnalysisCard
              icon={<Newspaper className="w-5 h-5 text-purple-400" />}
              title="심리 분석"
              signal={sentimentAnalysis?.recommendation}
              confidence={sentimentAnalysis?.confidence}
              summary={sentimentAnalysis?.summary}
              indicators={sentimentAnalysis ? <SentimentIndicators data={sentimentAnalysis} /> : undefined}
              notAvailable={!sentimentAnalysis}
            />

            {/* Risk Assessment */}
            <AnalysisCard
              icon={<Shield className="w-5 h-5 text-yellow-400" />}
              title="리스크 평가"
              signal={riskAssessment?.riskLevel}
              confidence={riskAssessment?.confidence}
              summary={riskAssessment?.summary}
              indicators={riskAssessment ? <RiskFactors data={riskAssessment} /> : undefined}
              notAvailable={!riskAssessment}
            />
          </div>

          {/* Reasoning Summary */}
          {reasoningSummary && (
            <div className="card">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Brain className="w-5 h-5 text-gray-400" />
                분석 요약
              </h2>
              <div className="text-sm text-gray-300 bg-surface rounded-lg p-4 whitespace-pre-wrap">
                {reasoningSummary}
              </div>
            </div>
          )}

          {/* No detail data fallback */}
          {!hasAnalysisData && !reasoningSummary && (
            <div className="card text-center py-8">
              <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-yellow-400" />
              <p className="text-gray-400">
                상세 분석 데이터가 없습니다.
              </p>
              <p className="text-sm text-gray-500 mt-1">
                이전 버전에서 완료된 분석일 수 있습니다.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
