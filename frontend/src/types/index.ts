/**
 * Type Definitions for Agentic Trading Frontend
 */

// -------------------------------------------
// Analysis Types
// -------------------------------------------

export type SignalType = 'strong_buy' | 'buy' | 'hold' | 'sell' | 'strong_sell';
export type TradeAction = 'BUY' | 'SELL' | 'HOLD';
export type SessionStatus = 'running' | 'awaiting_approval' | 'completed' | 'cancelled' | 'error';
export type TimeFrame = '1m' | '5m' | '15m' | '1h' | '1d' | '1w' | '1M';

export interface AnalysisSummary {
  agent_type: string;
  signal: SignalType;
  confidence: number;
  summary: string;
  key_factors: string[];
}

// -------------------------------------------
// Detailed Analysis Result Types (Phase 9)
// -------------------------------------------

/**
 * Technical Analysis Result with indicators
 */
export interface TechnicalAnalysisResult {
  summary: string;
  recommendation: TradeAction;
  confidence: number;  // 0-100
  indicators: {
    rsi: number | null;
    macd: {
      value: number;
      signal: number;
      histogram: number;
    } | null;
    sma50: number | null;
    sma200: number | null;
    bollingerBands: {
      upper: number;
      middle: number;
      lower: number;
    } | null;
  };
  signals: string[];  // ["골든크로스", "RSI 과매수"]
  priceAction: {
    currentPrice: number;
    change24h: number;
    changePercent24h: number;
    high52w: number | null;
    low52w: number | null;
  } | null;
}

/**
 * Fundamental Analysis Result with financial metrics
 */
export interface FundamentalAnalysisResult {
  summary: string;
  recommendation: TradeAction;
  confidence: number;
  metrics: {
    per: number | null;        // Price-to-Earnings Ratio
    pbr: number | null;        // Price-to-Book Ratio
    roe: number | null;        // Return on Equity
    eps: number | null;        // Earnings Per Share
    debtRatio: number | null;  // 부채비율
    revenueGrowth: number | null;  // 매출 성장률
    operatingMargin: number | null;  // 영업이익률
  };
  highlights: string[];  // 주요 포인트
  financialHealth: 'strong' | 'moderate' | 'weak' | 'unknown';
}

/**
 * Sentiment Analysis Result with news data
 */
export interface SentimentAnalysisResult {
  summary: string;
  recommendation: TradeAction;
  confidence: number;
  sentiment: 'positive' | 'neutral' | 'negative';
  sentimentScore: number;  // -100 ~ 100
  newsCount: number;
  recentNews: {
    title: string;
    source: string;
    sentiment: 'positive' | 'neutral' | 'negative';
    publishedAt: string;
  }[];
  socialMentions: number | null;
  analystRatings: {
    buy: number;
    hold: number;
    sell: number;
  } | null;
}

/**
 * Risk Assessment Result
 */
export interface RiskAssessmentResult {
  summary: string;
  riskLevel: 'low' | 'medium' | 'high' | 'very_high';
  confidence: number;
  riskScore: number;  // 0-100 (higher = riskier)
  factors: {
    name: string;
    impact: 'positive' | 'negative' | 'neutral';
    weight: number;  // 0-1
    description: string;
  }[];
  volatility: {
    daily: number | null;
    weekly: number | null;
    monthly: number | null;
  } | null;
  suggestedStopLoss: number | null;
  suggestedTakeProfit: number | null;
  maxPositionSize: number | null;  // % of portfolio
}

/**
 * Combined detailed analysis results
 */
export interface DetailedAnalysisResults {
  technical: TechnicalAnalysisResult | null;
  fundamental: FundamentalAnalysisResult | null;
  sentiment: SentimentAnalysisResult | null;
  risk: RiskAssessmentResult | null;
}

// -------------------------------------------
// Phase 13: Trading Context Types
// -------------------------------------------

/**
 * Active analysis context for chat
 */
export interface ActiveAnalysisContext {
  ticker: string;
  displayName: string;
  marketType: MarketType;
  status: SessionStatus;
  recommendation?: TradeAction;
  confidence?: number;
  currentPrice?: number;
  entryPrice?: number;
  stopLoss?: number;
  takeProfit?: number;
  keySignals?: string[];
}

/**
 * Trade decision record for chat context
 */
export interface TradeDecisionRecord {
  ticker: string;
  displayName: string;
  action: 'approved' | 'rejected';
  tradeAction: TradeAction;
  timestamp: string;
  quantity?: number;
  price?: number;
  rationale?: string;
}

/**
 * Structured trading context for enhanced chat
 */
export interface TradingContext {
  activeAnalysis?: ActiveAnalysisContext;
  recentDecisions: TradeDecisionRecord[];
  positions?: Array<{
    ticker: string;
    displayName?: string;
    quantity: number;
    entryPrice?: number;
    currentPrice?: number;
  }>;
}

// -------------------------------------------

/**
 * Extended history item with full analysis data
 */
export interface AnalysisHistoryItem {
  sessionId: string;
  ticker: string;
  displayName: string;
  marketType: MarketType;
  timestamp: Date;
  completedAt: Date | null;
  status: SessionStatus;

  // Detailed analysis results
  analysisResults: DetailedAnalysisResults | null;

  // Legacy analysis summaries (backward compatibility)
  analyses: AnalysisSummary[];

  // Trade proposal
  tradeProposal: TradeProposal | CoinTradeProposal | KRStockTradeProposal | null;

  // Reasoning summary (condensed from full log)
  reasoningSummary: string | null;

  // Metadata
  duration: number | null;  // Analysis duration in ms
  dataVersion: string;  // Schema version for migration
}

export interface TradeProposal {
  id: string;
  ticker: string;
  action: TradeAction;
  quantity: number;
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  risk_score: number;
  position_size_pct: number;
  rationale: string;
  bull_case: string;
  bear_case: string;
  created_at: string;
}

export interface Position {
  ticker: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  pnl: number;
  pnl_percent: number;
}

export interface SessionInfo {
  session_id: string;
  ticker: string;
  status: SessionStatus;
  created_at?: string;
}

export interface AnalysisStatus {
  session_id: string;
  ticker: string;
  status: SessionStatus;
  current_stage: string | null;
  awaiting_approval: boolean;
  trade_proposal: TradeProposal | null;
  analyses: AnalysisSummary[];
  reasoning_log: string[];
  error: string | null;
}

// -------------------------------------------
// WebSocket Message Types
// -------------------------------------------

export interface WSMessage {
  type: 'reasoning' | 'status' | 'proposal' | 'position' | 'complete';
  data: unknown;
}

export interface WSReasoningMessage {
  type: 'reasoning';
  data: string;
}

export interface WSStatusMessage {
  type: 'status';
  data: {
    status: SessionStatus;
    stage: string;
    awaiting_approval: boolean;
  };
}

export interface WSProposalMessage {
  type: 'proposal';
  data: TradeProposal;
}

export interface WSPositionMessage {
  type: 'position';
  data: Position;
}

export interface WSCompleteMessage {
  type: 'complete';
  data: {
    status: SessionStatus;
    error?: string;
  };
}

// -------------------------------------------
// Chat Types (for hybrid UI)
// -------------------------------------------

export type ChatMessageRole = 'user' | 'assistant' | 'system' | 'proposal';

// Union type for all proposal types
export type AnyTradeProposal = TradeProposal | CoinTradeProposal | KRStockTradeProposal;

export interface ChatMessage {
  id: string;
  role: ChatMessageRole;
  content: string;
  timestamp: Date;
  metadata?: {
    stage?: string;
    agent?: string;
    isThinking?: boolean;
    proposal?: AnyTradeProposal;
  };
}

// -------------------------------------------
// Chart Types
// -------------------------------------------

export interface CandlestickData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface VolumeData {
  time: string;
  value: number;
  color?: string;
}

export interface LineData {
  time: string;
  value: number;
}

export interface ChartConfig {
  timeframe: TimeFrame;
  showSMA50: boolean;
  showSMA200: boolean;
  showVolume: boolean;
}

// -------------------------------------------
// API Request Types
// -------------------------------------------

export interface AnalysisRequest {
  ticker: string;
}

export type ApprovalDecision = 'approved' | 'rejected' | 'modified' | 'cancelled';

export interface ApprovalRequest {
  session_id: string;
  decision: ApprovalDecision;
  feedback?: string;
  modifications?: Record<string, unknown>;
}

// -------------------------------------------
// API Response Types
// -------------------------------------------

export interface ApiResponse<T> {
  data: T;
  error?: string;
}

export interface StartAnalysisResponse {
  session_id: string;
  ticker: string;
  status: string;
  message: string;
}

// Alias for backward compatibility
export type AnalysisResponse = StartAnalysisResponse;

export interface ApprovalResponse {
  session_id: string;
  decision: string;
  status: string;
  message: string;
  execution_status?: string;
}

// -------------------------------------------
// Coin (Cryptocurrency) Types
// -------------------------------------------

export interface CoinMarketInfo {
  market: string;
  korean_name: string;
  english_name: string;
  market_warning: string | null;
}

export interface CoinAnalysisRequest {
  market: string;
  query?: string;
}

export interface CoinAnalysisResponse {
  session_id: string;
  market: string;
  status: string;
  message: string;
}

export interface CoinTradeProposal {
  id: string;
  market: string;
  korean_name: string | null;
  action: TradeAction;
  quantity: number;
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  risk_score: number;
  position_size_pct: number;
  rationale: string;
  bull_case: string;
  bear_case: string;
  created_at: string;
}

export interface CoinAnalysisStatus {
  session_id: string;
  market: string;
  korean_name: string | null;
  status: SessionStatus;
  current_stage: string | null;
  awaiting_approval: boolean;
  trade_proposal: CoinTradeProposal | null;
  analyses: AnalysisSummary[];
  reasoning_log: string[];
  error: string | null;
}

// -------------------------------------------
// Settings Types
// -------------------------------------------

export interface UpbitApiKeyStatus {
  is_configured: boolean;
  access_key_masked: string | null;
  trading_mode: string;
  is_valid: boolean | null;
  last_validated: string | null;
}

export interface UpbitApiKeyRequest {
  access_key: string;
  secret_key: string;
}

export interface UpbitApiKeyResponse {
  success: boolean;
  message: string;
  status: UpbitApiKeyStatus;
}

export interface UpbitValidateResponse {
  is_valid: boolean;
  message: string;
  account_count: number | null;
}

export interface SettingsStatus {
  upbit: UpbitApiKeyStatus;
  llm_provider: string;
  llm_model: string;
  market_data_mode: string;
}

// -------------------------------------------
// Coin Trading Types
// -------------------------------------------

export interface CoinAccount {
  currency: string;
  balance: number;
  locked: number;
  avg_buy_price: number;
  avg_buy_price_modified: boolean;
  unit_currency: string;
}

export interface CoinAccountListResponse {
  accounts: CoinAccount[];
  total_krw_value: number | null;
}

export interface CoinPosition {
  market: string;
  currency: string;
  quantity: number;
  avg_entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  stop_loss: number | null;
  take_profit: number | null;
  session_id: string | null;
  created_at: string;
}

export interface CoinPositionListResponse {
  positions: CoinPosition[];
  total_value_krw: number;
  total_pnl: number;
  total_pnl_pct: number;
}

export type OrderSide = 'bid' | 'ask';
export type OrderType = 'limit' | 'price' | 'market';
export type OrderState = 'wait' | 'watch' | 'done' | 'cancel';

export interface CoinOrder {
  uuid: string;
  side: OrderSide;
  ord_type: OrderType;
  price: number | null;
  state: OrderState;
  market: string;
  created_at: string;
  volume: number | null;
  remaining_volume: number | null;
  reserved_fee: number | null;
  remaining_fee: number | null;
  paid_fee: number | null;
  locked: number | null;
  executed_volume: number | null;
  trades_count: number | null;
}

export interface CoinOrderListResponse {
  orders: CoinOrder[];
  total: number;
}

export interface CoinOrderRequest {
  market: string;
  side: OrderSide;
  ord_type: OrderType;
  price?: number;
  volume?: number;
}

export interface CoinTradeRecord {
  id: string;
  session_id: string | null;
  market: string;
  side: OrderSide;
  order_type: string;
  price: number;
  volume: number;
  executed_volume: number;
  fee: number;
  total_krw: number;
  state: string;
  order_uuid: string | null;
  created_at: string;
}

export interface CoinTradeListResponse {
  trades: CoinTradeRecord[];
  total: number;
  page: number;
  limit: number;
}

export interface CoinTicker {
  market: string;
  trade_price: number;
  change: string;
  change_rate: number;
  change_price: number;
  high_price: number;
  low_price: number;
  trade_volume: number;
  acc_trade_price_24h: number;
  timestamp: string;
}

// -------------------------------------------
// Korean Stock (Kiwoom) Types
// -------------------------------------------

export interface KRStockInfo {
  stk_cd: string;           // Stock code (e.g., "005930")
  stk_nm: string;           // Stock name (e.g., "삼성전자")
  cur_prc: number;          // Current price (KRW)
  prdy_ctrt: number;        // Previous day change rate (%)
  prdy_vrss: number;        // Previous day price change
  trde_qty: number;         // Trading volume
  trde_prica: number;       // Trading value (KRW)
}

export interface KRStockListResponse {
  stocks: KRStockInfo[];
  total: number;
}

export interface KRStockTickerResponse {
  stk_cd: string;
  stk_nm: string;
  cur_prc: number;
  prdy_vrss: number;
  prdy_ctrt: number;
  opng_prc: number;
  high_prc: number;
  low_prc: number;
  trde_qty: number;
  trde_prica: number;
  per: number | null;
  pbr: number | null;
  eps: number | null;
  bps: number | null;
  timestamp: string;
}

export interface KRStockAnalysisRequest {
  stk_cd: string;
  query?: string;
}

export interface KRStockAnalysisResponse {
  session_id: string;
  stk_cd: string;
  stk_nm: string | null;
  status: string;
  message: string;
}

export interface KRStockTradeProposal {
  id: string;
  stk_cd: string;
  stk_nm: string | null;
  action: TradeAction;
  quantity: number;
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  risk_score: number;
  position_size_pct: number;
  rationale: string;
  bull_case: string;
  bear_case: string;
  created_at: string;
}

export interface KRStockAnalysisStatus {
  session_id: string;
  stk_cd: string;
  stk_nm: string | null;
  status: SessionStatus;
  current_stage: string | null;
  awaiting_approval: boolean;
  trade_proposal: KRStockTradeProposal | null;
  analyses: AnalysisSummary[];
  reasoning_log: string[];
  error: string | null;
}

export interface KRStockPosition {
  stk_cd: string;
  stk_nm: string;
  quantity: number;
  avg_entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  stop_loss: number | null;
  take_profit: number | null;
  session_id: string | null;
  created_at: string;
}

export interface KRStockPositionListResponse {
  positions: KRStockPosition[];
  total_value_krw: number;
  total_pnl: number;
  total_pnl_pct: number;
}

export type KRStockOrderSide = 'buy' | 'sell';
export type KRStockOrderType = 'limit' | 'market';
export type KRStockOrderStatus = 'pending' | 'partial' | 'completed' | 'cancelled';

export interface KRStockOrder {
  order_id: string;
  stk_cd: string;
  stk_nm: string | null;
  side: KRStockOrderSide;
  ord_type: KRStockOrderType;
  price: number | null;
  quantity: number;
  executed_quantity: number;
  remaining_quantity: number;
  status: KRStockOrderStatus;
  created_at: string;
}

export interface KRStockOrderListResponse {
  orders: KRStockOrder[];
  total: number;
}

export interface KRStockOrderRequest {
  stk_cd: string;
  side: KRStockOrderSide;
  ord_type: KRStockOrderType;
  price?: number;
  quantity: number;
}

export interface KRStockTradeRecord {
  id: string;
  session_id: string | null;
  stk_cd: string;
  stk_nm: string | null;
  side: KRStockOrderSide;
  order_type: string;
  price: number;
  quantity: number;
  executed_quantity: number;
  fee: number;
  total_krw: number;
  status: string;
  order_id: string | null;
  created_at: string;
}

export interface KRStockTradeListResponse {
  trades: KRStockTradeRecord[];
  total: number;
  page: number;
  limit: number;
}

export interface KRStockAccountBalance {
  deposit: number;
  orderable_amount: number;
  withdrawable_amount: number;
}

export interface KRStockHolding {
  stk_cd: string;
  stk_nm: string;
  quantity: number;
  avg_buy_price: number;
  current_price: number;
  eval_amount: number;
  profit_loss: number;
  profit_loss_rate: number;
}

export interface KRStockAccountResponse {
  cash: KRStockAccountBalance;
  holdings: KRStockHolding[];
  total_eval_amount: number;
  total_profit_loss: number;
  total_profit_loss_rate: number;
}

// -------------------------------------------
// Multi-Session Support Types
// -------------------------------------------

export type MarketType = 'stock' | 'coin' | 'kiwoom';

/**
 * Unified session data for multi-session support.
 * Each session represents an independent analysis workflow.
 */
export interface SessionData {
  sessionId: string;
  ticker: string;           // stock: ticker, coin: market, kiwoom: stk_cd
  displayName: string;      // Human-readable name (종목명)
  marketType: MarketType;
  status: SessionStatus;
  currentStage: string | null;
  reasoningLog: string[];
  analyses: AnalysisSummary[];
  tradeProposal: TradeProposal | CoinTradeProposal | KRStockTradeProposal | null;
  awaitingApproval: boolean;
  activePosition: Position | null;
  error: string | null;
  createdAt: Date;
  updatedAt: Date;
}

// Kiwoom Settings Types
export interface KiwoomApiKeyStatus {
  is_configured: boolean;
  account_masked: string | null;
  trading_mode: 'live' | 'paper';
  is_valid: boolean | null;
  last_validated: string | null;
}

export interface KiwoomApiKeyRequest {
  app_key: string;
  app_secret: string;
  account_number: string;
  is_mock: boolean;
}

export interface KiwoomApiKeyResponse {
  success: boolean;
  message: string;
  status: KiwoomApiKeyStatus;
}

export interface KiwoomValidateResponse {
  is_valid: boolean;
  message: string;
  account_info: Record<string, unknown> | null;
}

// -------------------------------------------
// Technical Indicators API Types (Phase 10)
// -------------------------------------------

export interface MovingAveragesData {
  sma_5: number | null;
  sma_20: number | null;
  sma_60: number | null;
  sma_120: number | null;
}

export interface MomentumData {
  rsi: number | null;
  rsi_signal: 'overbought' | 'oversold' | 'neutral';
  stochastic_k: number | null;
  stochastic_d: number | null;
}

export interface MACDData {
  line: number | null;
  signal: number | null;
  histogram: number | null;
}

export interface BollingerBandsData {
  upper: number | null;
  middle: number | null;
  lower: number | null;
  width_pct: number | null;
}

export interface VolatilityData {
  atr: number | null;
  daily_pct: number | null;
}

export interface VolumeData {
  current: number | null;
  avg_20: number | null;
  ratio: number | null;
}

export interface LevelsData {
  support_20d: number | null;
  resistance_20d: number | null;
}

export interface TrendData {
  direction: 'bullish' | 'bearish' | 'neutral';
  price_vs_sma20_pct: number | null;
}

export type IndicatorSignalType = 'strong_buy' | 'buy' | 'neutral' | 'sell' | 'strong_sell';

export interface IndicatorSignal {
  type: 'opportunity' | 'warning' | 'info';
  source: string;
  signal: IndicatorSignalType;
  value: number | null;
  description: string;
}

export interface TechnicalIndicatorsResponse {
  ticker: string;
  current_price: number;
  moving_averages: MovingAveragesData;
  momentum: MomentumData;
  macd: MACDData;
  bollinger_bands: BollingerBandsData;
  volatility: VolatilityData;
  volume: VolumeData;
  levels: LevelsData;
  trend: TrendData;
  signals: IndicatorSignal[];
}

export interface IndicatorsSummaryResponse {
  ticker: string;
  recommendation: TradeAction;
  confidence: number;
  key_signals: string[];
  summary: string;
}
