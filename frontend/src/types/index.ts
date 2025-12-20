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

export type ChatMessageRole = 'user' | 'assistant' | 'system';

export interface ChatMessage {
  id: string;
  role: ChatMessageRole;
  content: string;
  timestamp: Date;
  metadata?: {
    stage?: string;
    agent?: string;
    isThinking?: boolean;
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
