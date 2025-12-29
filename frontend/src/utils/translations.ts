/**
 * UI Translations for Analysis Reports
 *
 * Provides Korean and English translations for analysis page labels.
 */

import type { Language } from '@/store';

type TranslationKey =
  | 'analysis_summary'
  | 'trade_proposal'
  | 'technical_analysis'
  | 'fundamental_analysis'
  | 'sentiment_analysis'
  | 'risk_assessment'
  | 'analysis_rationale'
  | 'reasoning_summary'
  | 'recommendation'
  | 'complete'
  | 'market'
  | 'entry_price'
  | 'stop_loss'
  | 'take_profit'
  | 'financial_health'
  | 'strong'
  | 'moderate'
  | 'weak'
  | 'unknown'
  | 'market_sentiment'
  | 'positive'
  | 'neutral'
  | 'negative'
  | 'recent_news'
  | 'news_analyzed'
  | 'risk_level'
  | 'low'
  | 'medium'
  | 'high'
  | 'risk_factors'
  | 'suggested_stop_loss'
  | 'suggested_take_profit'
  | 'signals'
  | 'highlights'
  | 'price_change'
  | 'no_data_available'
  | 'legacy_analysis_note'
  | 'data_not_available';

const translations: Record<Language, Record<TranslationKey, string>> = {
  ko: {
    analysis_summary: '분석 요약',
    trade_proposal: '거래 제안',
    technical_analysis: '기술적 분석',
    fundamental_analysis: '펀더멘털 분석',
    sentiment_analysis: '심리 분석',
    risk_assessment: '리스크 평가',
    analysis_rationale: '분석 근거',
    reasoning_summary: '분석 요약',
    recommendation: '권고',
    complete: '완료',
    market: '시장',
    entry_price: '진입가',
    stop_loss: '손절가',
    take_profit: '목표가',
    financial_health: '재무 건전성',
    strong: '양호',
    moderate: '보통',
    weak: '취약',
    unknown: '알 수 없음',
    market_sentiment: '시장 심리',
    positive: '긍정적',
    neutral: '중립',
    negative: '부정적',
    recent_news: '최근 뉴스',
    news_analyzed: '건 분석',
    risk_level: '리스크 수준',
    low: '낮음',
    medium: '중간',
    high: '높음',
    risk_factors: '리스크 요인',
    suggested_stop_loss: '권장 손절',
    suggested_take_profit: '권장 목표',
    signals: '시그널',
    highlights: '주요 사항',
    price_change: '변동',
    no_data_available: '상세 분석 데이터가 없습니다.',
    legacy_analysis_note: '이전 버전에서 완료된 분석일 수 있습니다.',
    data_not_available: '데이터 없음',
  },
  en: {
    analysis_summary: 'Analysis Summary',
    trade_proposal: 'Trade Proposal',
    technical_analysis: 'Technical Analysis',
    fundamental_analysis: 'Fundamental Analysis',
    sentiment_analysis: 'Sentiment Analysis',
    risk_assessment: 'Risk Assessment',
    analysis_rationale: 'Analysis Rationale',
    reasoning_summary: 'Reasoning Summary',
    recommendation: 'Recommendation',
    complete: 'Complete',
    market: 'Market',
    entry_price: 'Entry Price',
    stop_loss: 'Stop Loss',
    take_profit: 'Take Profit',
    financial_health: 'Financial Health',
    strong: 'Strong',
    moderate: 'Moderate',
    weak: 'Weak',
    unknown: 'Unknown',
    market_sentiment: 'Market Sentiment',
    positive: 'Positive',
    neutral: 'Neutral',
    negative: 'Negative',
    recent_news: 'Recent News',
    news_analyzed: ' analyzed',
    risk_level: 'Risk Level',
    low: 'Low',
    medium: 'Medium',
    high: 'High',
    risk_factors: 'Risk Factors',
    suggested_stop_loss: 'Suggested Stop Loss',
    suggested_take_profit: 'Suggested Take Profit',
    signals: 'Signals',
    highlights: 'Highlights',
    price_change: 'Change',
    no_data_available: 'Detailed analysis data is not available.',
    legacy_analysis_note: 'This may be from an older version of the analysis.',
    data_not_available: 'No data',
  },
};

export function t(key: TranslationKey, language: Language): string {
  return translations[language][key] || key;
}

export function useTranslations(language: Language) {
  return (key: TranslationKey) => t(key, language);
}
