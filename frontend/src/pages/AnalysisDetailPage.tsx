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

import { useState, useMemo } from 'react';
import {
  ArrowLeft,
  FileText,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Brain,
  Shield,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  Bitcoin,
  Building2,
  Activity,
  DollarSign,
  Newspaper,
  Languages,
  Plus,
  Loader2,
  Eye,
} from 'lucide-react';
import { useStore, selectTickerHistory, type MarketType, type TickerHistoryItem } from '@/store';
import { useGoTo } from '@/hooks/useNav';
import { addToTradeQueue } from '@/api/client';
import { MarkdownRenderer } from '@/components/common/MarkdownRenderer';
import { ReadingPane } from '@/components/common/ReadingPane';
import { useTranslations } from '@/utils/translations';
import { pnlColor } from '@/utils/pnl';
import { Awaiting } from '@/components/terminal/panels/shared';
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

// Market type icon component. Colors are market IDENTITY (which market this
// analysis belongs to), not a P&L/direction value, so they stay raw — same
// precedent as AnalysisPage's MarketIcon/getMarketColor.
function MarketIcon({ marketType, size = 16 }: { marketType: MarketType; size?: number }) {
  switch (marketType) {
    case 'stock':
      return <TrendingUp size={size} className="text-green-400" />; // color-ok: market identity, not directional
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

// Signal color routes through the shared P&L helper: bullish/buy is up
// (green), bearish/sell is down (red), anything else (HOLD, or a riskLevel
// string reused through this same helper) is neutral. Text-only — the badge
// itself supplies the neutral bg-elevated/border-hairline chip.
function getSignalColor(signal?: string): string {
  switch (signal?.toUpperCase()) {
    case 'BULLISH':
    case 'BUY':
      return pnlColor(1);
    case 'BEARISH':
    case 'SELL':
      return pnlColor(-1);
    default:
      return 'text-muted';
  }
}

// Trade-action color — mirrors the ACTION_TEXT_COLOR convention from
// ScannerResultsPage/AnalysisPage: BUY/ADD and SELL/REDUCE are genuinely
// bullish/bearish and route through the shared P&L helper; WATCH/AVOID/HOLD
// are non-directional statuses that use direct semantic tokens instead.
const ACTION_COLOR: Record<string, string> = {
  BUY: pnlColor(1),
  ADD: pnlColor(1),
  SELL: pnlColor(-1),
  REDUCE: pnlColor(-1),
  WATCH: 'text-warn',
  AVOID: 'text-accent',
  HOLD: 'text-muted',
};

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
          <span className={`px-2 py-1 text-xs font-medium rounded border border-hairline bg-elevated ${getSignalColor(signal)}`}>
            {signal}
          </span>
        )}
      </div>

      {notAvailable ? (
        <Awaiting label="데이터 없음" />
      ) : (
        <>
          {confidence !== undefined && confidence > 0 && (
            <div className="mb-3">
              <div className="flex items-center justify-between text-sm mb-1">
                <span className="text-muted">신뢰도</span>
                <span className="font-medium tabular-nums">{confidence.toFixed(0)}%</span>
              </div>
              <div className="h-2 bg-elevated rounded-full overflow-hidden">
                <div
                  className="h-full bg-accent transition-all"
                  style={{ width: `${Math.min(confidence, 100)}%` }}
                />
              </div>
            </div>
          )}

          {summary && (
            <div className="text-sm text-ink mb-3 bg-elevated/50 rounded-lg p-3 max-h-64 overflow-y-auto">
              <ReadingPane><MarkdownRenderer content={summary} compact /></ReadingPane>
            </div>
          )}

          {indicators && (
            <div className="mb-3">
              {indicators}
            </div>
          )}

          {highlights && highlights.length > 0 && (
            <div className="text-sm bg-elevated rounded-lg p-3 max-h-36 overflow-y-auto">
              <ul className="space-y-1">
                {highlights.map((h, i) => (
                  <li key={i} className="text-muted flex items-start gap-2">
                    <span className="text-accent mt-1">•</span>
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
  const language = useStore((state) => state.language);
  const t = useTranslations(language);

  return (
    <div className="grid grid-cols-2 gap-2 text-xs">
      {indicators.rsi !== null && (
        <div className="bg-elevated rounded p-2">
          <span className="text-dim">RSI</span>
          <span className={`ml-2 font-medium tabular-nums ${
            indicators.rsi > 70 ? pnlColor(-1) :
            indicators.rsi < 30 ? pnlColor(1) : 'text-ink'
          }`}>
            {indicators.rsi.toFixed(1)}
          </span>
        </div>
      )}
      {indicators.sma50 !== null && (
        <div className="bg-elevated rounded p-2">
          <span className="text-dim">SMA50</span>
          <span className="ml-2 font-medium text-ink tabular-nums">
            ₩{indicators.sma50.toLocaleString('ko-KR')}
          </span>
        </div>
      )}
      {indicators.macd && (
        <div className="bg-elevated rounded p-2">
          <span className="text-dim">MACD</span>
          <span className={`ml-2 font-medium tabular-nums ${pnlColor(indicators.macd.histogram ?? 0)}`}>
            {(indicators.macd.histogram ?? 0).toFixed(2)}
          </span>
        </div>
      )}
      {priceAction && (
        <div className="bg-elevated rounded p-2">
          <span className="text-dim">{t('price_change')}</span>
          <span className={`ml-2 font-medium tabular-nums ${pnlColor(priceAction.changePercent24h)}`}>
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
  const language = useStore((state) => state.language);
  const t = useTranslations(language);

  // Financial-health is a non-directional status (not a raw P&L value), so it
  // maps to direct semantic tokens rather than routing through pnlColor.
  const healthColor: Record<string, string> = {
    strong: 'text-up',
    moderate: 'text-warn',
    weak: 'text-down',
    unknown: 'text-muted',
  };

  const hasMetrics = metrics && (metrics.per != null || metrics.pbr != null || metrics.roe != null);

  return (
    <div className="space-y-2">
      {hasMetrics && (
        <div className="grid grid-cols-3 gap-2 text-xs">
          {metrics.per != null && (
            <div className="bg-elevated rounded p-2 text-center">
              <div className="text-dim">PER</div>
              <div className="font-medium text-ink tabular-nums">{metrics.per.toFixed(1)}</div>
            </div>
          )}
          {metrics.pbr != null && (
            <div className="bg-elevated rounded p-2 text-center">
              <div className="text-dim">PBR</div>
              <div className="font-medium text-ink tabular-nums">{metrics.pbr.toFixed(2)}</div>
            </div>
          )}
          {metrics.roe != null && (
            <div className="bg-elevated rounded p-2 text-center">
              <div className="text-dim">ROE</div>
              <div className="font-medium text-ink tabular-nums">{metrics.roe.toFixed(1)}%</div>
            </div>
          )}
        </div>
      )}
      <div className="flex items-center gap-2 text-sm">
        <span className="text-dim">{t('financial_health')}:</span>
        <span className={`font-medium ${healthColor[financialHealth] || healthColor.unknown}`}>
          {t(financialHealth as 'strong' | 'moderate' | 'weak' | 'unknown')}
        </span>
      </div>
    </div>
  );
}

// Sentiment Indicators Component
function SentimentIndicators({ data }: { data: SentimentAnalysisResult }) {
  const language = useStore((state) => state.language);
  const t = useTranslations(language);

  // Sentiment valence is directional (positive/negative ~ bullish/bearish),
  // so it routes through the same pnlColor helper as the signal badges.
  const sentimentColor: Record<string, string> = {
    positive: pnlColor(1),
    neutral: 'text-muted',
    negative: pnlColor(-1),
  };

  const sentiment = data.sentiment || 'neutral';
  const score = data.sentimentScore ?? 0;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="text-dim">{t('market_sentiment')}:</span>
        <span className={`font-medium tabular-nums ${sentimentColor[sentiment] || sentimentColor.neutral}`}>
          {t(sentiment as 'positive' | 'neutral' | 'negative')} {score !== 0 && `(${score > 0 ? '+' : ''}${score.toFixed(0)})`}
        </span>
      </div>
      {data.newsCount > 0 && (
        <div className="text-xs text-dim">
          {language === 'ko' ? `최근 뉴스 ${data.newsCount}건 분석` : `${data.newsCount} news articles analyzed`}
        </div>
      )}
      {data.recentNews && data.recentNews.length > 0 && (
        <div className="bg-elevated rounded p-2 max-h-24 overflow-y-auto">
          {data.recentNews.slice(0, 3).map((news, i) => (
            <div key={i} className="text-xs text-muted truncate py-0.5">
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
  const language = useStore((state) => state.language);
  const t = useTranslations(language);

  // Risk-level severity is a non-directional status (low/medium/high/very_high),
  // not a raw P&L value, so it maps to direct semantic tokens. The reduced
  // palette (only up/warn/down) means high and very_high share a token.
  const riskColor: Record<string, string> = {
    low: 'text-up',
    medium: 'text-warn',
    high: 'text-down',
    very_high: 'text-down',
  };

  const riskLevel = data.riskLevel || 'medium';

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm text-dim">{t('risk_level')}:</span>
        <span className={`px-2 py-0.5 text-xs font-medium rounded border border-hairline bg-elevated ${riskColor[riskLevel] || riskColor.medium}`}>
          {t(riskLevel as 'low' | 'medium' | 'high')}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        {data.suggestedStopLoss != null && (
          <div className="bg-elevated rounded p-2">
            <span className="text-dim">{t('suggested_stop_loss')}</span>
            <span className={`ml-2 font-medium tabular-nums ${pnlColor(-1)}`}>
              ₩{data.suggestedStopLoss.toLocaleString('ko-KR')}
            </span>
          </div>
        )}
        {data.suggestedTakeProfit != null && (
          <div className="bg-elevated rounded p-2">
            <span className="text-dim">{t('suggested_take_profit')}</span>
            <span className={`ml-2 font-medium tabular-nums ${pnlColor(1)}`}>
              ₩{data.suggestedTakeProfit.toLocaleString('ko-KR')}
            </span>
          </div>
        )}
      </div>
      {data.factors && data.factors.length > 0 && (
        <div className="text-xs bg-elevated rounded-lg p-2 max-h-24 overflow-y-auto">
          <ul className="space-y-1">
            {data.factors.slice(0, 3).map((f, i) => (
              <li key={i} className="text-muted flex items-start gap-2">
                <span className={
                  f.impact === 'positive' ? pnlColor(1) :
                  f.impact === 'negative' ? pnlColor(-1) : 'text-muted'
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
  const goTo = useGoTo();
  const storeSessionId = useStore((state) => state.selectedSessionId);
  const history = useStore(selectTickerHistory);
  const language = useStore((state) => state.language);
  const setLanguage = useStore((state) => state.setLanguage);
  const t = useTranslations(language);

  // State for Add to Queue
  const [addingToQueue, setAddingToQueue] = useState(false);
  const [queueMessage, setQueueMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Use prop sessionId if provided, otherwise use store's selectedSessionId
  const sessionId = propSessionId || storeSessionId;

  // Toggle language between 'ko' and 'en'
  const toggleLanguage = () => {
    setLanguage(language === 'ko' ? 'en' : 'ko');
  };

  // Find the analysis by session ID
  const analysis = useMemo(() => {
    if (!sessionId) return null;
    return history.find((h) => h.sessionId === sessionId);
  }, [history, sessionId]);

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else {
      goTo('analysis');
    }
  };

  // Handle adding trade to queue
  const handleAddToQueue = async () => {
    if (!analysis) return;

    // Get required data
    const ticker = 'stk_cd' in analysis ? (analysis as { stk_cd: string }).stk_cd : analysis.ticker;
    const stockName = getDisplayName(analysis);
    const action = getAction(analysis);

    // Get trade proposal data if available
    const proposal = 'tradeProposal' in analysis
      ? (analysis as { tradeProposal?: { entry_price?: number; stop_loss?: number; take_profit?: number } }).tradeProposal
      : null;

    if (!action || action === 'HOLD' || action === 'WATCH' || action === 'AVOID') {
      setQueueMessage({ type: 'error', text: `Cannot queue ${action || 'empty'} recommendations` });
      setTimeout(() => setQueueMessage(null), 3000);
      return;
    }

    if (!proposal?.entry_price) {
      setQueueMessage({ type: 'error', text: 'No entry price available' });
      setTimeout(() => setQueueMessage(null), 3000);
      return;
    }

    try {
      setAddingToQueue(true);
      setQueueMessage(null);

      const result = await addToTradeQueue({
        ticker,
        stock_name: stockName,
        action,
        entry_price: proposal.entry_price,
        stop_loss: proposal.stop_loss,
        take_profit: proposal.take_profit,
        session_id: sessionId || undefined,
        reason: `From completed analysis: ${stockName}`,
      });

      setQueueMessage({ type: 'success', text: result.message });
      setTimeout(() => setQueueMessage(null), 5000);
    } catch (err) {
      setQueueMessage({
        type: 'error',
        text: err instanceof Error ? err.message : 'Failed to add to queue',
      });
      setTimeout(() => setQueueMessage(null), 5000);
    } finally {
      setAddingToQueue(false);
    }
  };

  // If no analysis found, show not found state
  if (!analysis) {
    return (
      <div className="h-full flex flex-col bg-canvas">
        <div className="flex-1 flex items-center justify-center p-4">
          <div className="text-center text-dim">
            <FileText className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p className="text-lg">Analysis not found</p>
            <p className="text-sm mt-2">The analysis may have been removed or expired</p>
            <button
              onClick={handleBack}
              className="mt-4 px-4 py-2 bg-accent hover:bg-accent/90 rounded-lg text-canvas text-sm transition-colors"
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

  // Debug logging for analysis data
  console.log('[AnalysisDetailPage] Analysis data:', {
    sessionId,
    hasAnalysisResultsKey: 'analysisResults' in analysis,
    analysisResults,
    analysisResultsKeys: analysisResults ? Object.keys(analysisResults) : [],
    status: analysis.status,
  });

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
    <div className="h-full flex flex-col bg-canvas">
      {/* Header */}
      <div className="flex-none border-b border-hairline bg-card">
        <div className="max-w-4xl mx-auto px-4 py-2.5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={handleBack}
              className="p-1.5 rounded hover:bg-elevated transition-colors"
              title="Back to Analysis"
            >
              <ArrowLeft className="w-4 h-4 text-muted" />
            </button>
            <MarketIcon marketType={marketType} />
            <div>
              <h1 className="text-sm font-semibold text-ink">{displayName}</h1>
              <div className="flex items-center gap-2 text-[11px] text-dim">
                {displayName !== analysis.ticker && <span>{analysis.ticker}</span>}
                <span className="px-1.5 py-0.5 text-[10px] bg-elevated rounded text-muted">{getMarketLabel(marketType)}</span>
                <span>·</span>
                <span>{formatDate(analysis.timestamp)}</span>
              </div>
            </div>
          </div>
          {/* Status & Action Badge + Language Toggle */}
          <div className="flex items-center gap-2">
            {/* Language Toggle */}
            <button
              onClick={toggleLanguage}
              className="px-2 py-1 text-xs rounded bg-elevated hover:bg-hairline flex items-center gap-1 text-muted hover:text-ink transition-colors"
              title={language === 'ko' ? 'Switch to English' : '한국어로 변경'}
            >
              <Languages className="w-3 h-3" />
              {language === 'ko' ? 'EN' : 'KO'}
            </button>
            {/* Action badge — a real trade recommendation, so it's a text-only
                chip on a neutral bg-elevated/border-hairline background,
                routed through ACTION_COLOR (pnlColor-backed for BUY/SELL). */}
            {action && (
              <span className={`px-2 py-1 text-xs font-medium rounded border border-hairline bg-elevated flex items-center gap-1 ${ACTION_COLOR[action] ?? 'text-muted'}`}>
                {(action === 'BUY' || action === 'ADD') ? <TrendingUp className="w-3 h-3" /> :
                 (action === 'SELL' || action === 'REDUCE' || action === 'AVOID') ? <TrendingDown className="w-3 h-3" /> :
                 <Eye className="w-3 h-3" />}
                {action}
              </span>
            )}
            {/* Session-status badge — non-trading status, direct semantic tokens. */}
            <span className={`px-2 py-1 text-xs rounded border border-hairline bg-elevated flex items-center gap-1 ${
              analysis.status === 'completed' ? 'text-up' :
              analysis.status === 'cancelled' ? 'text-warn' : 'text-down'
            }`}>
              {analysis.status === 'completed' ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
              {analysis.status}
            </span>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="max-w-4xl mx-auto space-y-4">
          {/* Summary Card */}
          <div className="card">
            <h2 className="text-sm font-semibold mb-3 text-ink">{t('analysis_summary')}</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="text-center">
                <div className={`text-lg font-bold tabular-nums ${ACTION_COLOR[action ?? 'HOLD'] ?? 'text-muted'}`}>
                  {action || 'HOLD'}
                </div>
                <div className="text-[11px] text-dim mt-1">{t('recommendation')}</div>
              </div>
              <div className="text-center">
                <div className="text-lg font-bold tabular-nums text-up">
                  {analysis.status === 'completed' ? '100%' : '-'}
                </div>
                <div className="text-[11px] text-dim mt-1">{t('complete')}</div>
              </div>
              <div className="text-center">
                <div className="text-lg font-bold text-ink">
                  {getMarketLabel(marketType)}
                </div>
                <div className="text-[11px] text-dim mt-1">{t('market')}</div>
              </div>
              <div className="text-center">
                <div className="flex items-center justify-center gap-1 text-lg font-bold text-muted">
                  <Clock className="w-4 h-4" />
                </div>
                <div className="text-[11px] text-dim mt-1">
                  {formatDate(analysis.timestamp).split(' ').slice(-2).join(' ')}
                </div>
              </div>
            </div>
          </div>

          {/* Trade Proposal Card (if available) */}
          {tradeProposal && (
            <div className="card">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold flex items-center gap-2 text-ink">
                  <Activity className="w-4 h-4 text-accent" />
                  {t('trade_proposal')}
                </h2>
                {/* Add to Queue Button */}
                {action && !['HOLD', 'WATCH', 'AVOID'].includes(action) && tradeProposal.entry_price && (
                  <button
                    onClick={handleAddToQueue}
                    disabled={addingToQueue}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-accent hover:bg-accent/90 text-canvas rounded disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {addingToQueue ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Plus className="w-4 h-4" />
                    )}
                    Add to Queue
                  </button>
                )}
              </div>

              {/* Queue Message — a system toast (success/error), not a trading
                  recommendation badge, so a tinted fill is fine here. */}
              {queueMessage && (
                <div className={`mb-4 p-3 rounded-lg text-sm border ${
                  queueMessage.type === 'success'
                    ? 'bg-up/10 text-up border-up/30'
                    : 'bg-down/10 text-down border-down/30'
                }`}>
                  {queueMessage.text}
                </div>
              )}

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                {tradeProposal.entry_price && (
                  <div className="text-center">
                    <div className="text-lg font-bold text-ink tabular-nums">
                      ₩{tradeProposal.entry_price.toLocaleString('ko-KR')}
                    </div>
                    <div className="text-[11px] text-dim">{t('entry_price')}</div>
                  </div>
                )}
                {tradeProposal.stop_loss && (
                  <div className="text-center">
                    <div className={`text-lg font-bold tabular-nums ${pnlColor(-1)}`}>
                      ₩{tradeProposal.stop_loss.toLocaleString('ko-KR')}
                    </div>
                    <div className="text-[11px] text-dim">{t('stop_loss')}</div>
                  </div>
                )}
                {tradeProposal.take_profit && (
                  <div className="text-center">
                    <div className={`text-lg font-bold tabular-nums ${pnlColor(1)}`}>
                      ₩{tradeProposal.take_profit.toLocaleString('ko-KR')}
                    </div>
                    <div className="text-[11px] text-dim">{t('take_profit')}</div>
                  </div>
                )}
              </div>
              {tradeProposal.rationale && (
                <div className="text-sm text-ink bg-elevated rounded-lg p-3">
                  <p className="font-medium text-muted mb-2">{t('analysis_rationale')}:</p>
                  <ReadingPane><MarkdownRenderer content={tradeProposal.rationale} compact /></ReadingPane>
                </div>
              )}
            </div>
          )}

          {/* Analysis Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Technical Analysis */}
            <AnalysisCard
              icon={<BarChart3 className="w-5 h-5 text-blue-400" />}
              title={t('technical_analysis')}
              signal={technicalAnalysis?.recommendation}
              confidence={technicalAnalysis?.confidence}
              summary={technicalAnalysis?.summary}
              indicators={technicalAnalysis ? <TechnicalIndicators data={technicalAnalysis} /> : undefined}
              highlights={technicalAnalysis?.signals}
              notAvailable={!technicalAnalysis}
            />

            {/* Fundamental Analysis */}
            <AnalysisCard
              icon={<DollarSign className="w-5 h-5 text-green-400" />} // color-ok: analysis-category icon, not directional
              title={t('fundamental_analysis')}
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
              title={t('sentiment_analysis')}
              signal={sentimentAnalysis?.recommendation}
              confidence={sentimentAnalysis?.confidence}
              summary={sentimentAnalysis?.summary}
              indicators={sentimentAnalysis ? <SentimentIndicators data={sentimentAnalysis} /> : undefined}
              notAvailable={!sentimentAnalysis}
            />

            {/* Risk Assessment */}
            <AnalysisCard
              icon={<Shield className="w-5 h-5 text-yellow-400" />}
              title={t('risk_assessment')}
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
              <h2 className="text-sm font-semibold mb-3 flex items-center gap-2 text-ink">
                <Brain className="w-4 h-4 text-muted" />
                {t('reasoning_summary')}
              </h2>
              <div className="text-sm text-ink bg-elevated rounded-lg p-4 whitespace-pre-wrap">
                {reasoningSummary}
              </div>
            </div>
          )}

          {/* No detail data fallback */}
          {!hasAnalysisData && !reasoningSummary && (
            <div className="card text-center py-8">
              <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-warn" />
              <p className="text-muted">
                {t('no_data_available')}
              </p>
              <p className="text-sm text-dim mt-1">
                {t('legacy_analysis_note')}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
