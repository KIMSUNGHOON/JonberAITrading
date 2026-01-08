/**
 * ProposalChatMessage Component
 *
 * Displays trade proposals as chat messages with approve/reject actions.
 */

import { useState, useCallback } from 'react';
import {
  TrendingUp,
  TrendingDown,
  ChevronDown,
  ChevronUp,
  Check,
  X,
  RefreshCw,
  Bot,
  Languages,
  Loader2,
} from 'lucide-react';
import { format } from 'date-fns';
import ReactMarkdown from 'react-markdown';
import { useStore } from '@/store';
import { cancelSession, cancelCoinSession, cancelKRStockSession, translateText } from '@/api/client';
import type { TradeProposal, CoinTradeProposal, KRStockTradeProposal } from '@/types';

type Language = 'original' | 'en' | 'ko';

interface TranslatedContent {
  rationale?: string;
  bull_case?: string;
  bear_case?: string;
}

type AnyTradeProposal = TradeProposal | CoinTradeProposal | KRStockTradeProposal;

interface ProposalChatMessageProps {
  proposal: AnyTradeProposal;
  timestamp: Date;
}

// Helper to get display name
function getProposalDisplayName(proposal: AnyTradeProposal): string {
  if ('ticker' in proposal) return proposal.ticker;
  if ('market' in proposal) {
    const coinProposal = proposal as CoinTradeProposal;
    return coinProposal.korean_name || proposal.market.replace('KRW-', '');
  }
  if ('stk_cd' in proposal) {
    const stockProposal = proposal as KRStockTradeProposal;
    return stockProposal.stk_nm || proposal.stk_cd;
  }
  return 'UNKNOWN';
}

// Helper to check proposal type
function isCoinProposal(proposal: AnyTradeProposal): proposal is CoinTradeProposal {
  return 'market' in proposal;
}

function isKiwoomProposal(proposal: AnyTradeProposal): proposal is KRStockTradeProposal {
  return 'stk_cd' in proposal;
}

// Helper to format currency
function formatCurrency(value: number | null, isCoin: boolean, isKiwoom: boolean): string {
  if (value === null) return 'N/A';
  if (isCoin || isKiwoom) {
    return `₩${value.toLocaleString('ko-KR')}`;
  }
  return `$${value.toFixed(2)}`;
}

// Helper to format quantity
function formatQuantity(quantity: number, isCoin: boolean, isKiwoom: boolean): string {
  if (isCoin) return `₩${quantity.toLocaleString('ko-KR')}`;
  if (isKiwoom) return `${quantity.toLocaleString('ko-KR')}주`;
  return `${quantity} shares`;
}

export function ProposalChatMessage({ proposal, timestamp }: ProposalChatMessageProps) {
  const [showRationale, setShowRationale] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [language, setLanguage] = useState<Language>('original');
  const [isTranslating, setIsTranslating] = useState(false);
  const [translations, setTranslations] = useState<Record<Language, TranslatedContent>>({
    original: {},
    en: {},
    ko: {},
  });
  const setShowApprovalDialog = useStore((state) => state.setShowApprovalDialog);

  // Detect original language (heuristic: check if rationale contains Korean characters)
  const hasKorean = /[\u3131-\u314e|\u314f-\u3163|\uac00-\ud7a3]/g.test(proposal.rationale || '');
  const originalLang = hasKorean ? 'ko' : 'en';
  const targetLang = originalLang === 'ko' ? 'en' : 'ko';

  // Handle language toggle
  const handleTranslate = useCallback(async () => {
    const newLang = language === 'original' ? targetLang : 'original';

    // If switching back to original, just update state
    if (newLang === 'original') {
      setLanguage('original');
      return;
    }

    // If already translated, just switch
    if (translations[newLang].rationale) {
      setLanguage(newLang);
      return;
    }

    // Translate
    setIsTranslating(true);
    try {
      const [rationaleRes, bullRes, bearRes] = await Promise.all([
        proposal.rationale ? translateText(proposal.rationale, newLang) : Promise.resolve(null),
        proposal.bull_case ? translateText(proposal.bull_case, newLang) : Promise.resolve(null),
        proposal.bear_case ? translateText(proposal.bear_case, newLang) : Promise.resolve(null),
      ]);

      setTranslations((prev) => ({
        ...prev,
        [newLang]: {
          rationale: rationaleRes?.translated || '',
          bull_case: bullRes?.translated || '',
          bear_case: bearRes?.translated || '',
        },
      }));
      setLanguage(newLang);
    } catch (error) {
      console.error('Translation failed:', error);
    } finally {
      setIsTranslating(false);
    }
  }, [language, targetLang, translations, proposal.rationale, proposal.bull_case, proposal.bear_case]);

  // Get content based on selected language
  const getContent = (field: 'rationale' | 'bull_case' | 'bear_case'): string => {
    if (language === 'original') {
      return proposal[field] || '';
    }
    return translations[language][field] || proposal[field] || '';
  };

  // Get cancel actions for different market types
  const setStockProposal = useStore((state) => state.setStockProposal);
  const setCoinProposal = useStore((state) => state.setCoinProposal);
  const setKiwoomProposal = useStore((state) => state.setKiwoomProposal);
  const stockSessionId = useStore((state) => state.stock.activeSessionId);
  const coinSessionId = useStore((state) => state.coin.activeSessionId);
  const kiwoomSessionId = useStore((state) => state.kiwoom.activeSessionId);
  const setActiveMarket = useStore((state) => state.setActiveMarket);

  const isBuy = proposal.action === 'BUY';
  const isCoin = isCoinProposal(proposal);
  const isKiwoom = isKiwoomProposal(proposal);
  const displayName = getProposalDisplayName(proposal);

  // Handle cancel/reject
  const handleCancel = async () => {
    setIsCancelling(true);
    try {
      if (isKiwoom && kiwoomSessionId) {
        await cancelKRStockSession(kiwoomSessionId);
        setKiwoomProposal(null);
      } else if (isCoin && coinSessionId) {
        await cancelCoinSession(coinSessionId);
        setCoinProposal(null);
      } else if (stockSessionId) {
        await cancelSession(stockSessionId);
        setStockProposal(null);
      }
    } catch (error) {
      console.error('Failed to cancel analysis:', error);
    } finally {
      setIsCancelling(false);
    }
  };

  // Risk level
  const riskLevel = proposal.risk_score <= 3 ? 'Low' : proposal.risk_score <= 6 ? 'Medium' : 'High';
  const riskColor =
    proposal.risk_score <= 3
      ? 'text-green-400'
      : proposal.risk_score <= 6
      ? 'text-yellow-400'
      : 'text-red-400';
  const riskBgColor =
    proposal.risk_score <= 3
      ? 'bg-green-400'
      : proposal.risk_score <= 6
      ? 'bg-yellow-400'
      : 'bg-red-400';

  return (
    <div className="flex items-start gap-3">
      {/* Bot Avatar */}
      <div className="w-8 h-8 rounded-full bg-blue-600/20 flex items-center justify-center flex-shrink-0">
        <Bot className="w-4 h-4 text-blue-400" />
      </div>

      {/* Proposal Card */}
      <div className="flex-1 max-w-[90%]">
        <div className="bg-surface border border-yellow-500/30 rounded-lg overflow-hidden">
          {/* Header */}
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-gray-300">Trade Proposal</span>
              <span className="text-sm font-semibold">{displayName}</span>
            </div>
            <span
              className={`px-2 py-0.5 rounded text-xs font-bold ${
                isBuy ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
              }`}
            >
              {proposal.action}
            </span>
          </div>

          {/* Content */}
          <div className="px-4 py-3 space-y-3">
            {/* Key Metrics */}
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <span className="text-gray-500 block text-xs">Quantity</span>
                <span className="font-medium">{formatQuantity(proposal.quantity, isCoin, isKiwoom)}</span>
              </div>
              <div>
                <span className="text-gray-500 block text-xs">Entry Price</span>
                <span className="font-medium">
                  {formatCurrency(proposal.entry_price, isCoin, isKiwoom)}
                </span>
              </div>
              <div>
                <span className="text-gray-500 block text-xs">Stop Loss</span>
                <span className="font-medium text-red-400">
                  {formatCurrency(proposal.stop_loss, isCoin, isKiwoom)}
                </span>
              </div>
              <div>
                <span className="text-gray-500 block text-xs">Take Profit</span>
                <span className="font-medium text-green-400">
                  {formatCurrency(proposal.take_profit, isCoin, isKiwoom)}
                </span>
              </div>
            </div>

            {/* Risk Score */}
            <div className="flex items-center gap-3">
              <span className="text-gray-500 text-xs">Risk Score</span>
              <div className="flex-1 h-2 bg-surface-dark rounded-full overflow-hidden">
                <div
                  className={`h-full ${riskBgColor} transition-all`}
                  style={{ width: `${(proposal.risk_score / 10) * 100}%` }}
                />
              </div>
              <span className={`text-xs font-medium ${riskColor}`}>
                {proposal.risk_score.toFixed(1)}/10 ({riskLevel})
              </span>
            </div>

            {/* Rationale Toggle */}
            <div className="flex items-center justify-between">
              <button
                onClick={() => setShowRationale(!showRationale)}
                className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 transition-colors"
              >
                {showRationale ? (
                  <ChevronUp className="w-3 h-3" />
                ) : (
                  <ChevronDown className="w-3 h-3" />
                )}
                {showRationale ? 'Hide' : 'View'} Rationale
              </button>

              {/* Language Toggle */}
              {showRationale && (
                <button
                  onClick={handleTranslate}
                  disabled={isTranslating}
                  className="flex items-center gap-1 px-2 py-0.5 text-xs rounded border border-border hover:bg-surface-light transition-colors disabled:opacity-50"
                  title={language === 'original' ? `Translate to ${targetLang === 'en' ? 'English' : '한국어'}` : 'Show Original'}
                >
                  {isTranslating ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <Languages className="w-3 h-3" />
                  )}
                  <span>
                    {language === 'original'
                      ? targetLang === 'en' ? 'EN' : 'KO'
                      : 'Original'}
                  </span>
                </button>
              )}
            </div>

            {/* Rationale Content */}
            {showRationale && (
              <div className="space-y-2 pt-2 border-t border-border text-sm">
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-gray-500 text-xs">Rationale</span>
                    {language !== 'original' && (
                      <span className="text-xs text-purple-400 bg-purple-500/10 px-1.5 py-0.5 rounded">
                        {language === 'en' ? 'Translated to English' : '한국어로 번역됨'}
                      </span>
                    )}
                  </div>
                  <div className="text-gray-300 text-xs leading-relaxed prose prose-invert prose-xs max-w-none">
                    <ReactMarkdown>{getContent('rationale')}</ReactMarkdown>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="bg-green-500/10 rounded p-2">
                    <div className="flex items-center gap-1 text-green-400 text-xs mb-1">
                      <TrendingUp className="w-3 h-3" />
                      Bull Case
                    </div>
                    <div className="text-xs text-gray-400 prose prose-invert prose-xs max-w-none">
                      <ReactMarkdown>{getContent('bull_case')}</ReactMarkdown>
                    </div>
                  </div>
                  <div className="bg-red-500/10 rounded p-2">
                    <div className="flex items-center gap-1 text-red-400 text-xs mb-1">
                      <TrendingDown className="w-3 h-3" />
                      Bear Case
                    </div>
                    <div className="text-xs text-gray-400 prose prose-invert prose-xs max-w-none">
                      <ReactMarkdown>{getContent('bear_case')}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="px-4 py-3 border-t border-border flex items-center justify-between gap-2 bg-surface-dark/50">
            <button
              onClick={() => {
                // Set correct active market and proposal, then open dialog for re-analysis
                if (isKiwoom) {
                  setActiveMarket('kiwoom');
                  setKiwoomProposal(proposal as KRStockTradeProposal);
                } else if (isCoin) {
                  setActiveMarket('coin');
                  setCoinProposal(proposal as CoinTradeProposal);
                } else {
                  setActiveMarket('stock');
                  setStockProposal(proposal as TradeProposal);
                }
                setShowApprovalDialog(true);
              }}
              className="flex items-center gap-1 px-3 py-1.5 text-xs text-gray-400 hover:text-gray-300 hover:bg-surface rounded transition-colors"
            >
              <RefreshCw className="w-3 h-3" />
              Re-analyze
            </button>
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  // Set the correct active market and ensure proposal is in store
                  if (isKiwoom) {
                    setActiveMarket('kiwoom');
                    setKiwoomProposal(proposal as KRStockTradeProposal);
                  } else if (isCoin) {
                    setActiveMarket('coin');
                    setCoinProposal(proposal as CoinTradeProposal);
                  } else {
                    setActiveMarket('stock');
                    setStockProposal(proposal as TradeProposal);
                  }
                  setShowApprovalDialog(true);
                }}
                className="flex items-center gap-1 px-4 py-1.5 text-xs font-medium bg-green-600 hover:bg-green-500 text-white rounded transition-colors"
              >
                <Check className="w-3 h-3" />
                Approve
              </button>
              <button
                onClick={handleCancel}
                disabled={isCancelling}
                className="flex items-center gap-1 px-3 py-1.5 text-xs text-gray-400 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isCancelling ? (
                  <RefreshCw className="w-3 h-3 animate-spin" />
                ) : (
                  <X className="w-3 h-3" />
                )}
                {isCancelling ? 'Cancelling...' : 'Cancel'}
              </button>
            </div>
          </div>
        </div>

        {/* Timestamp */}
        <span className="text-xs text-gray-500 mt-1 block">
          {format(timestamp, 'HH:mm')}
        </span>
      </div>
    </div>
  );
}
