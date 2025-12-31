/**
 * UI Translations for the Trading Application
 *
 * Provides Korean and English translations for all UI components.
 * Phase 4: Expanded i18n support across the entire application.
 */

import type { Language } from '@/store';

// ============================================
// Translation Key Types
// ============================================

// Navigation
type NavKeys =
  | 'nav_dashboard'
  | 'nav_analysis'
  | 'nav_charts'
  | 'nav_positions'
  | 'nav_basket'
  | 'nav_trades'
  | 'nav_auto_trading'
  | 'nav_documentation'
  | 'nav_help'
  | 'nav_settings';

// Common UI
type CommonKeys =
  | 'loading'
  | 'error'
  | 'success'
  | 'cancel'
  | 'confirm'
  | 'save'
  | 'delete'
  | 'edit'
  | 'close'
  | 'refresh'
  | 'search'
  | 'filter'
  | 'sort'
  | 'no_data'
  | 'view_all'
  | 'view_details'
  | 'go_back'
  | 'submit'
  | 'start'
  | 'stop'
  | 'pause'
  | 'resume'
  | 'running'
  | 'completed'
  | 'pending'
  | 'failed'
  | 'active'
  | 'inactive'
  | 'items'
  | 'stocks';

// Trading Dashboard
type TradingDashboardKeys =
  | 'trading_title'
  | 'trading_subtitle'
  | 'trading_status'
  | 'trading_started'
  | 'trading_trades'
  | 'trading_portfolio'
  | 'trading_equity'
  | 'trading_cash'
  | 'trading_pnl'
  | 'trading_positions'
  | 'trading_no_positions'
  | 'trading_alerts'
  | 'trading_start_btn'
  | 'trading_stop_btn'
  | 'trading_pause_btn'
  | 'trading_resume_btn';

// Watch List
type WatchListKeys =
  | 'watch_list_title'
  | 'watch_list_subtitle'
  | 'watch_list_empty'
  | 'watch_list_empty_desc'
  | 'watch_list_current_price'
  | 'watch_list_target_price'
  | 'watch_list_risk'
  | 'watch_list_stop_loss'
  | 'watch_list_take_profit'
  | 'watch_list_added_date'
  | 'watch_list_add_to_queue'
  | 'watch_list_remove'
  | 'watch_list_reanalyze'
  | 'watch_list_avg_confidence'
  | 'watch_list_avg_risk'
  | 'watch_list_confidence';

// Trade Queue
type TradeQueueKeys =
  | 'trade_queue_title'
  | 'trade_queue_subtitle'
  | 'trade_queue_empty'
  | 'trade_queue_empty_desc'
  | 'trade_queue_pending_orders'
  | 'trade_queue_execute'
  | 'trade_queue_cancel'
  | 'trade_queue_buy'
  | 'trade_queue_sell'
  | 'trade_queue_hold'
  | 'trade_queue_quantity'
  | 'trade_queue_price'
  | 'trade_queue_total';

// Agent Status
type AgentStatusKeys =
  | 'agent_status_title'
  | 'agent_status_coordinator'
  | 'agent_status_risk_monitor'
  | 'agent_status_technical'
  | 'agent_status_fundamental'
  | 'agent_status_sentiment'
  | 'agent_status_execution'
  | 'agent_status_idle'
  | 'agent_status_working'
  | 'agent_status_waiting'
  | 'agent_status_error';

// Strategy Config
type StrategyConfigKeys =
  | 'strategy_title'
  | 'strategy_risk_level'
  | 'strategy_max_position'
  | 'strategy_stop_loss_pct'
  | 'strategy_take_profit_pct'
  | 'strategy_max_daily_trades'
  | 'strategy_save_changes';

// Analysis (original keys)
type AnalysisKeys =
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

// Market Tabs
type MarketTabKeys =
  | 'market_kr_stock'
  | 'market_us_stock'
  | 'market_coin'
  | 'market_all';

// Basket
type BasketKeys =
  | 'basket_title'
  | 'basket_empty'
  | 'basket_empty_desc'
  | 'basket_analyze_all'
  | 'basket_clear_all'
  | 'basket_add_stock'
  | 'basket_remove';

// Settings
type SettingsKeys =
  | 'settings_title'
  | 'settings_language'
  | 'settings_theme'
  | 'settings_notifications'
  | 'settings_api_keys'
  | 'settings_dark_mode'
  | 'settings_light_mode'
  | 'settings_language_ko'
  | 'settings_language_en';

// Time & Date
type TimeKeys =
  | 'time_just_now'
  | 'time_minutes_ago'
  | 'time_hours_ago'
  | 'time_days_ago'
  | 'time_today'
  | 'time_yesterday';

// Combined Translation Key Type
export type TranslationKey =
  | NavKeys
  | CommonKeys
  | TradingDashboardKeys
  | WatchListKeys
  | TradeQueueKeys
  | AgentStatusKeys
  | StrategyConfigKeys
  | AnalysisKeys
  | MarketTabKeys
  | BasketKeys
  | SettingsKeys
  | TimeKeys;

// ============================================
// Translations
// ============================================

const translations: Record<Language, Record<TranslationKey, string>> = {
  ko: {
    // Navigation
    nav_dashboard: '대시보드',
    nav_analysis: '분석',
    nav_charts: '차트',
    nav_positions: '포지션',
    nav_basket: '관심종목',
    nav_trades: '거래내역',
    nav_auto_trading: '자동매매',
    nav_documentation: '문서',
    nav_help: '도움말',
    nav_settings: '설정',

    // Common UI
    loading: '로딩중...',
    error: '오류',
    success: '성공',
    cancel: '취소',
    confirm: '확인',
    save: '저장',
    delete: '삭제',
    edit: '수정',
    close: '닫기',
    refresh: '새로고침',
    search: '검색',
    filter: '필터',
    sort: '정렬',
    no_data: '데이터 없음',
    view_all: '전체 보기',
    view_details: '상세 보기',
    go_back: '뒤로 가기',
    submit: '제출',
    start: '시작',
    stop: '중지',
    pause: '일시정지',
    resume: '재개',
    running: '진행중',
    completed: '완료',
    pending: '대기중',
    failed: '실패',
    active: '활성',
    inactive: '비활성',
    items: '개',
    stocks: '종목',

    // Trading Dashboard
    trading_title: '자동매매',
    trading_subtitle: '자동매매 관리',
    trading_status: '상태',
    trading_started: '시작 시간',
    trading_trades: '거래',
    trading_portfolio: '포트폴리오',
    trading_equity: '총 자산',
    trading_cash: '현금',
    trading_pnl: '손익',
    trading_positions: '포지션',
    trading_no_positions: '활성 포지션 없음',
    trading_alerts: '알림',
    trading_start_btn: '시작',
    trading_stop_btn: '중지',
    trading_pause_btn: '일시정지',
    trading_resume_btn: '재개',

    // Watch List
    watch_list_title: 'Watch List',
    watch_list_subtitle: '매수 대기 중인 관심 종목 목록',
    watch_list_empty: 'Watch List가 비어있습니다',
    watch_list_empty_desc: 'WATCH 추천을 받은 종목이 여기에 표시됩니다',
    watch_list_current_price: '현재가',
    watch_list_target_price: '목표가',
    watch_list_risk: '리스크',
    watch_list_stop_loss: '손절',
    watch_list_take_profit: '익절',
    watch_list_added_date: '추가일',
    watch_list_add_to_queue: '매수 대기열 추가',
    watch_list_remove: 'Watch List에서 제거',
    watch_list_reanalyze: '재분석',
    watch_list_avg_confidence: '평균 신뢰도',
    watch_list_avg_risk: '평균 리스크',
    watch_list_confidence: '신뢰도',

    // Trade Queue
    trade_queue_title: '매수 대기열',
    trade_queue_subtitle: '실행 대기중인 주문 목록',
    trade_queue_empty: '대기중인 주문이 없습니다',
    trade_queue_empty_desc: '매수 주문이 추가되면 여기에 표시됩니다',
    trade_queue_pending_orders: '대기 주문',
    trade_queue_execute: '실행',
    trade_queue_cancel: '취소',
    trade_queue_buy: '매수',
    trade_queue_sell: '매도',
    trade_queue_hold: '보유',
    trade_queue_quantity: '수량',
    trade_queue_price: '가격',
    trade_queue_total: '총액',

    // Agent Status
    agent_status_title: '에이전트 상태',
    agent_status_coordinator: '코디네이터',
    agent_status_risk_monitor: '리스크 모니터',
    agent_status_technical: '기술적 분석',
    agent_status_fundamental: '펀더멘털 분석',
    agent_status_sentiment: '감성 분석',
    agent_status_execution: '실행 에이전트',
    agent_status_idle: '대기중',
    agent_status_working: '작업중',
    agent_status_waiting: '대기',
    agent_status_error: '오류',

    // Strategy Config
    strategy_title: '전략 설정',
    strategy_risk_level: '리스크 수준',
    strategy_max_position: '최대 포지션 크기',
    strategy_stop_loss_pct: '손절 비율 (%)',
    strategy_take_profit_pct: '익절 비율 (%)',
    strategy_max_daily_trades: '일일 최대 거래 수',
    strategy_save_changes: '변경사항 저장',

    // Analysis (original)
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

    // Market Tabs
    market_kr_stock: '국내주식',
    market_us_stock: '해외주식',
    market_coin: '암호화폐',
    market_all: '전체',

    // Basket
    basket_title: '관심종목',
    basket_empty: '관심종목이 비어있습니다',
    basket_empty_desc: '종목을 추가하여 분석을 시작하세요',
    basket_analyze_all: '전체 분석',
    basket_clear_all: '전체 삭제',
    basket_add_stock: '종목 추가',
    basket_remove: '제거',

    // Settings
    settings_title: '설정',
    settings_language: '언어',
    settings_theme: '테마',
    settings_notifications: '알림',
    settings_api_keys: 'API 키',
    settings_dark_mode: '다크 모드',
    settings_light_mode: '라이트 모드',
    settings_language_ko: '한국어',
    settings_language_en: 'English',

    // Time
    time_just_now: '방금 전',
    time_minutes_ago: '분 전',
    time_hours_ago: '시간 전',
    time_days_ago: '일 전',
    time_today: '오늘',
    time_yesterday: '어제',
  },
  en: {
    // Navigation
    nav_dashboard: 'Dashboard',
    nav_analysis: 'Analysis',
    nav_charts: 'Charts',
    nav_positions: 'Positions',
    nav_basket: 'My Basket',
    nav_trades: 'Trades',
    nav_auto_trading: 'Auto-Trading',
    nav_documentation: 'Documentation',
    nav_help: 'Help',
    nav_settings: 'Settings',

    // Common UI
    loading: 'Loading...',
    error: 'Error',
    success: 'Success',
    cancel: 'Cancel',
    confirm: 'Confirm',
    save: 'Save',
    delete: 'Delete',
    edit: 'Edit',
    close: 'Close',
    refresh: 'Refresh',
    search: 'Search',
    filter: 'Filter',
    sort: 'Sort',
    no_data: 'No data',
    view_all: 'View All',
    view_details: 'View Details',
    go_back: 'Go Back',
    submit: 'Submit',
    start: 'Start',
    stop: 'Stop',
    pause: 'Pause',
    resume: 'Resume',
    running: 'Running',
    completed: 'Completed',
    pending: 'Pending',
    failed: 'Failed',
    active: 'Active',
    inactive: 'Inactive',
    items: '',
    stocks: 'stocks',

    // Trading Dashboard
    trading_title: 'Auto-Trading',
    trading_subtitle: 'Automated trading management',
    trading_status: 'Status',
    trading_started: 'Started',
    trading_trades: 'Trades',
    trading_portfolio: 'Portfolio',
    trading_equity: 'Equity',
    trading_cash: 'Cash',
    trading_pnl: 'P&L',
    trading_positions: 'Positions',
    trading_no_positions: 'No active positions',
    trading_alerts: 'Alerts',
    trading_start_btn: 'Start',
    trading_stop_btn: 'Stop',
    trading_pause_btn: 'Pause',
    trading_resume_btn: 'Resume',

    // Watch List
    watch_list_title: 'Watch List',
    watch_list_subtitle: 'Stocks pending buy signal',
    watch_list_empty: 'Watch List is empty',
    watch_list_empty_desc: 'Stocks with WATCH recommendation will appear here',
    watch_list_current_price: 'Current',
    watch_list_target_price: 'Target',
    watch_list_risk: 'Risk',
    watch_list_stop_loss: 'Stop Loss',
    watch_list_take_profit: 'Take Profit',
    watch_list_added_date: 'Added',
    watch_list_add_to_queue: 'Add to Queue',
    watch_list_remove: 'Remove from Watch List',
    watch_list_reanalyze: 'Re-analyze',
    watch_list_avg_confidence: 'Avg Confidence',
    watch_list_avg_risk: 'Avg Risk',
    watch_list_confidence: 'Confidence',

    // Trade Queue
    trade_queue_title: 'Trade Queue',
    trade_queue_subtitle: 'Orders pending execution',
    trade_queue_empty: 'No pending orders',
    trade_queue_empty_desc: 'Buy orders will appear here',
    trade_queue_pending_orders: 'Pending Orders',
    trade_queue_execute: 'Execute',
    trade_queue_cancel: 'Cancel',
    trade_queue_buy: 'BUY',
    trade_queue_sell: 'SELL',
    trade_queue_hold: 'HOLD',
    trade_queue_quantity: 'Quantity',
    trade_queue_price: 'Price',
    trade_queue_total: 'Total',

    // Agent Status
    agent_status_title: 'Agent Status',
    agent_status_coordinator: 'Coordinator',
    agent_status_risk_monitor: 'Risk Monitor',
    agent_status_technical: 'Technical',
    agent_status_fundamental: 'Fundamental',
    agent_status_sentiment: 'Sentiment',
    agent_status_execution: 'Execution',
    agent_status_idle: 'Idle',
    agent_status_working: 'Working',
    agent_status_waiting: 'Waiting',
    agent_status_error: 'Error',

    // Strategy Config
    strategy_title: 'Strategy Settings',
    strategy_risk_level: 'Risk Level',
    strategy_max_position: 'Max Position Size',
    strategy_stop_loss_pct: 'Stop Loss (%)',
    strategy_take_profit_pct: 'Take Profit (%)',
    strategy_max_daily_trades: 'Max Daily Trades',
    strategy_save_changes: 'Save Changes',

    // Analysis (original)
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

    // Market Tabs
    market_kr_stock: 'KR Stock',
    market_us_stock: 'US Stock',
    market_coin: 'Crypto',
    market_all: 'All',

    // Basket
    basket_title: 'My Basket',
    basket_empty: 'Basket is empty',
    basket_empty_desc: 'Add stocks to start analysis',
    basket_analyze_all: 'Analyze All',
    basket_clear_all: 'Clear All',
    basket_add_stock: 'Add Stock',
    basket_remove: 'Remove',

    // Settings
    settings_title: 'Settings',
    settings_language: 'Language',
    settings_theme: 'Theme',
    settings_notifications: 'Notifications',
    settings_api_keys: 'API Keys',
    settings_dark_mode: 'Dark Mode',
    settings_light_mode: 'Light Mode',
    settings_language_ko: '한국어',
    settings_language_en: 'English',

    // Time
    time_just_now: 'just now',
    time_minutes_ago: 'm ago',
    time_hours_ago: 'h ago',
    time_days_ago: 'd ago',
    time_today: 'Today',
    time_yesterday: 'Yesterday',
  },
};

// ============================================
// Translation Functions
// ============================================

export function t(key: TranslationKey, language: Language): string {
  return translations[language][key] || key;
}

export function useTranslations(language: Language) {
  return (key: TranslationKey) => t(key, language);
}

// Format with variables (e.g., "{{count}} items")
export function tFormat(
  key: TranslationKey,
  language: Language,
  vars: Record<string, string | number>
): string {
  let text = translations[language][key] || key;
  Object.entries(vars).forEach(([varKey, value]) => {
    text = text.replace(new RegExp(`{{${varKey}}}`, 'g'), String(value));
  });
  return text;
}

// Hook that returns both t and tFormat functions
export function useTranslationsWithFormat(language: Language) {
  return {
    t: (key: TranslationKey) => t(key, language),
    tFormat: (key: TranslationKey, vars: Record<string, string | number>) =>
      tFormat(key, language, vars),
  };
}
