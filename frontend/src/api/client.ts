/**
 * API Client for Agentic Trading Backend
 *
 * Provides typed methods for all API endpoints.
 */

import axios, { type AxiosInstance, type AxiosError } from 'axios';
import type {
  AnalysisRequest,
  AnalysisResponse,
  ApprovalRequest,
  ApprovalResponse,
  SessionStatus,
  CoinAnalysisRequest,
  CoinAnalysisResponse,
  CoinMarketInfo,
  CoinAccountListResponse,
  CoinPositionListResponse,
  CoinPosition,
  CoinOrderListResponse,
  CoinOrder,
  CoinOrderRequest,
  CoinTradeListResponse,
  CoinTradeRecord,
  SettingsStatus,
  UpbitApiKeyRequest,
  UpbitApiKeyResponse,
  UpbitApiKeyStatus,
  UpbitValidateResponse,
  // Korean Stock (Kiwoom) Types
  KRStockListResponse,
  KRStockTickerResponse,
  KRStockAnalysisRequest,
  KRStockAnalysisResponse,
  KRStockAnalysisStatus,
  KRStockPosition,
  KRStockPositionListResponse,
  KRStockOrder,
  KRStockOrderListResponse,
  KRStockOrderRequest,
  KRStockTradeRecord,
  KRStockTradeListResponse,
  KRStockAccountResponse,
  KiwoomApiKeyStatus,
  KiwoomApiKeyRequest,
  KiwoomApiKeyResponse,
  KiwoomValidateResponse,
  // Trading Strategy Types
  TradingStrategyRequest,
  TradingStrategyResponse,
  // Watch List Types
  WatchListResponse,
  WatchedStock,
  AddToWatchListRequest,
  AddToWatchListResponse,
  ConvertWatchToQueueRequest,
  ConvertWatchToQueueResponse,
  // Scanner Types
  ScanProgressResponse,
  ScanResultsResponse,
  StartScanRequest,
} from '@/types';

// -------------------------------------------
// Configuration
// -------------------------------------------

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

// -------------------------------------------
// Request Queue for Rate-Limited APIs
// -------------------------------------------

/**
 * Simple request queue to prevent overwhelming the Kiwoom API.
 * Ensures requests are made sequentially with a minimum delay.
 */
class RequestQueue {
  private queue: Array<() => Promise<void>> = [];
  private isProcessing = false;
  private minDelay: number;

  constructor(minDelayMs = 800) {
    this.minDelay = minDelayMs;
  }

  async enqueue<T>(fn: () => Promise<T>): Promise<T> {
    return new Promise((resolve, reject) => {
      this.queue.push(async () => {
        try {
          const result = await fn();
          resolve(result);
        } catch (error) {
          reject(error);
        }
      });
      this.process();
    });
  }

  private async process() {
    if (this.isProcessing || this.queue.length === 0) return;
    this.isProcessing = true;

    while (this.queue.length > 0) {
      const task = this.queue.shift();
      if (task) {
        await task();
        // Wait before next request to respect rate limits
        if (this.queue.length > 0) {
          await new Promise((resolve) => setTimeout(resolve, this.minDelay));
        }
      }
    }

    this.isProcessing = false;
  }
}

// Singleton queue for Kiwoom API requests (800ms delay = ~1.25 req/sec)
const kiwoomRequestQueue = new RequestQueue(800);

// -------------------------------------------
// API Client Class
// -------------------------------------------

class ApiClient {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Request interceptor
    this.client.interceptors.request.use(
      (config) => {
        // Add auth token if available
        const token = localStorage.getItem('auth_token');
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    // Response interceptor
    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        const message = this.extractErrorMessage(error);
        console.error('API Error:', message);
        return Promise.reject(new Error(message));
      }
    );
  }

  private extractErrorMessage(error: AxiosError): string {
    if (error.response?.data) {
      const data = error.response.data as { detail?: string; message?: string };
      return data.detail || data.message || 'An error occurred';
    }
    if (error.message) {
      return error.message;
    }
    return 'Network error';
  }

  // -------------------------------------------
  // Analysis Endpoints
  // -------------------------------------------

  /**
   * Start a new analysis session.
   */
  async startAnalysis(request: AnalysisRequest): Promise<AnalysisResponse> {
    const response = await this.client.post<AnalysisResponse>(
      '/analysis/start',
      request
    );
    return response.data;
  }

  /**
   * Get current status of an analysis session.
   */
  async getSessionStatus(sessionId: string): Promise<{
    session_id: string;
    ticker: string;
    status: SessionStatus;
    current_stage: string | null;
    analyses_count: number;
    awaiting_approval: boolean;
    error: string | null;
  }> {
    const response = await this.client.get(`/analysis/status/${sessionId}`);
    return response.data;
  }

  /**
   * Get full analysis state.
   */
  async getSessionState(sessionId: string): Promise<{
    session_id: string;
    state: Record<string, unknown>;
    status: SessionStatus;
  }> {
    const response = await this.client.get(`/analysis/state/${sessionId}`);
    return response.data;
  }

  /**
   * Cancel an analysis session.
   */
  async cancelSession(sessionId: string): Promise<{ success: boolean }> {
    const response = await this.client.post(`/analysis/cancel/${sessionId}`);
    return response.data;
  }

  /**
   * List all active sessions.
   */
  async listSessions(): Promise<
    Array<{
      session_id: string;
      ticker: string;
      status: SessionStatus;
      created_at: string;
    }>
  > {
    const response = await this.client.get('/analysis/sessions');
    return response.data;
  }

  // -------------------------------------------
  // Approval Endpoints
  // -------------------------------------------

  /**
   * Get pending trade proposal for approval.
   */
  async getPendingProposal(sessionId: string): Promise<{
    has_pending: boolean;
    proposal: {
      id: string;
      ticker: string;
      action: string;
      quantity: number;
      entry_price: number;
      stop_loss: number;
      take_profit: number;
      risk_score: number;
      rationale: string;
    } | null;
  }> {
    const response = await this.client.get(`/approval/pending/${sessionId}`);
    return response.data;
  }

  /**
   * Submit approval decision for a trade proposal.
   */
  async submitApproval(request: ApprovalRequest): Promise<ApprovalResponse> {
    const response = await this.client.post<ApprovalResponse>(
      '/approval/decide',
      request
    );
    return response.data;
  }

  // -------------------------------------------
  // Coin Analysis Endpoints
  // -------------------------------------------

  /**
   * Get available coin markets.
   */
  async getCoinMarkets(quoteCurrency?: string): Promise<{
    markets: CoinMarketInfo[];
    total: number;
  }> {
    const params = quoteCurrency ? { quote_currency: quoteCurrency } : {};
    const response = await this.client.get('/coin/markets', { params });
    return response.data;
  }

  /**
   * Search coin markets by name or code.
   */
  async searchCoinMarkets(query: string, limit = 10): Promise<{
    markets: CoinMarketInfo[];
    total: number;
  }> {
    const response = await this.client.post('/coin/markets/search', {
      query,
      limit,
    });
    return response.data;
  }

  /**
   * Start a new coin analysis session.
   */
  async startCoinAnalysis(request: CoinAnalysisRequest): Promise<CoinAnalysisResponse> {
    const response = await this.client.post<CoinAnalysisResponse>(
      '/coin/analysis/start',
      request
    );
    return response.data;
  }

  /**
   * Get coin analysis session status.
   */
  async getCoinSessionStatus(sessionId: string): Promise<{
    session_id: string;
    market: string;
    korean_name: string | null;
    status: SessionStatus;
    current_stage: string | null;
    awaiting_approval: boolean;
    error: string | null;
  }> {
    const response = await this.client.get(`/coin/analysis/status/${sessionId}`);
    return response.data;
  }

  /**
   * Cancel a coin analysis session.
   */
  async cancelCoinSession(sessionId: string): Promise<{ message: string }> {
    const response = await this.client.post(`/coin/analysis/cancel/${sessionId}`);
    return response.data;
  }

  // -------------------------------------------
  // Coin Market Data Endpoints
  // -------------------------------------------

  /**
   * Get candle (OHLCV) data for a coin market.
   */
  async getCoinCandles(
    market: string,
    interval: string = '1d',
    count: number = 200
  ): Promise<{
    market: string;
    interval: string;
    candles: Array<{
      datetime: string;
      open: number;
      high: number;
      low: number;
      close: number;
      volume: number;
    }>;
  }> {
    const response = await this.client.get(`/coin/candles/${market}`, {
      params: { interval, count },
    });
    return response.data;
  }

  /**
   * Get current ticker for a coin market.
   */
  async getCoinTicker(market: string): Promise<{
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
  }> {
    const response = await this.client.get(`/coin/ticker/${market}`);
    return response.data;
  }

  /**
   * Get current tickers for multiple coin markets in a single request.
   * This batch endpoint avoids rate limiting by reducing API calls.
   */
  async getCoinTickers(markets: string[]): Promise<{
    tickers: Array<{
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
    }>;
    total: number;
  }> {
    const response = await this.client.get('/coin/tickers', {
      params: { markets: markets.join(',') },
    });
    return response.data;
  }

  /**
   * Get orderbook for a coin market.
   */
  async getCoinOrderbook(market: string): Promise<{
    market: string;
    total_ask_size: number;
    total_bid_size: number;
    bid_ask_ratio: number;
    asks: Array<{ price: number; size: number }>;
    bids: Array<{ price: number; size: number }>;
    timestamp: string;
  }> {
    const response = await this.client.get(`/coin/orderbook/${market}`);
    return response.data;
  }

  // -------------------------------------------
  // Coin Trading Endpoints
  // -------------------------------------------

  /**
   * Get account balances.
   */
  async getCoinAccounts(): Promise<CoinAccountListResponse> {
    const response = await this.client.get<CoinAccountListResponse>('/coin/accounts');
    return response.data;
  }

  /**
   * Get all open positions with real-time P&L.
   */
  async getCoinPositions(): Promise<CoinPositionListResponse> {
    const response = await this.client.get<CoinPositionListResponse>('/coin/positions');
    return response.data;
  }

  /**
   * Get a single position by market.
   */
  async getCoinPosition(market: string): Promise<CoinPosition> {
    const response = await this.client.get<CoinPosition>(`/coin/positions/${market}`);
    return response.data;
  }

  /**
   * Close a position by selling all holdings at market price.
   */
  async closeCoinPosition(market: string): Promise<CoinOrder> {
    const response = await this.client.post<CoinOrder>(`/coin/positions/${market}/close`);
    return response.data;
  }

  /**
   * Get list of orders.
   */
  async getCoinOrders(params?: {
    market?: string;
    state?: string;
    limit?: number;
  }): Promise<CoinOrderListResponse> {
    const response = await this.client.get<CoinOrderListResponse>('/coin/orders', { params });
    return response.data;
  }

  /**
   * Get a single order by UUID.
   */
  async getCoinOrder(orderId: string): Promise<CoinOrder> {
    const response = await this.client.get<CoinOrder>(`/coin/orders/${orderId}`);
    return response.data;
  }

  /**
   * Create a new order.
   */
  async createCoinOrder(request: CoinOrderRequest): Promise<CoinOrder> {
    const response = await this.client.post<CoinOrder>('/coin/orders', request);
    return response.data;
  }

  /**
   * Cancel an order.
   */
  async cancelCoinOrder(orderId: string): Promise<CoinOrder> {
    const response = await this.client.delete<CoinOrder>(`/coin/orders/${orderId}`);
    return response.data;
  }

  /**
   * Get trade history with pagination.
   */
  async getCoinTrades(params?: {
    market?: string;
    page?: number;
    limit?: number;
  }): Promise<CoinTradeListResponse> {
    const response = await this.client.get<CoinTradeListResponse>('/coin/trades', { params });
    return response.data;
  }

  /**
   * Get a single trade by ID.
   */
  async getCoinTrade(tradeId: string): Promise<CoinTradeRecord> {
    const response = await this.client.get<CoinTradeRecord>(`/coin/trades/${tradeId}`);
    return response.data;
  }

  // -------------------------------------------
  // Health Check
  // -------------------------------------------

  /**
   * Check API health status.
   */
  async healthCheck(): Promise<{
    status: string;
    timestamp: string;
    version: string;
  }> {
    const response = await this.client.get('/health');
    return response.data;
  }

  // -------------------------------------------
  // Settings Endpoints
  // -------------------------------------------

  /**
   * Get current settings status.
   */
  async getSettings(): Promise<SettingsStatus> {
    const response = await this.client.get<SettingsStatus>('/settings');
    return response.data;
  }

  /**
   * Get Upbit API key status.
   */
  async getUpbitApiStatus(): Promise<UpbitApiKeyStatus> {
    const response = await this.client.get<UpbitApiKeyStatus>('/settings/upbit');
    return response.data;
  }

  /**
   * Update Upbit API keys.
   */
  async updateUpbitApiKeys(request: UpbitApiKeyRequest): Promise<UpbitApiKeyResponse> {
    const response = await this.client.post<UpbitApiKeyResponse>(
      '/settings/upbit',
      request
    );
    return response.data;
  }

  /**
   * Validate Upbit API keys.
   */
  async validateUpbitApiKeys(): Promise<UpbitValidateResponse> {
    const response = await this.client.post<UpbitValidateResponse>(
      '/settings/upbit/validate'
    );
    return response.data;
  }

  /**
   * Clear Upbit API keys.
   */
  async clearUpbitApiKeys(): Promise<{ message: string }> {
    const response = await this.client.delete('/settings/upbit');
    return response.data;
  }

  // -------------------------------------------
  // Korean Stock (Kiwoom) Endpoints
  // -------------------------------------------

  /**
   * Get Korean stock list.
   */
  async getKRStocks(limit = 100): Promise<KRStockListResponse> {
    const response = await this.client.get<KRStockListResponse>('/kr_stocks/stocks', {
      params: { limit },
    });
    return response.data;
  }

  /**
   * Search Korean stocks by code or name.
   */
  async searchKRStocks(query: string, limit = 20): Promise<KRStockListResponse> {
    const response = await this.client.post<KRStockListResponse>('/kr_stocks/stocks/search', {
      query,
      limit,
    });
    return response.data;
  }

  /**
   * Get current ticker for a Korean stock.
   * Uses request queue to prevent rate limit errors.
   */
  async getKRStockTicker(stk_cd: string): Promise<KRStockTickerResponse> {
    // Queue the request to prevent overwhelming the Kiwoom API
    return kiwoomRequestQueue.enqueue(async () => {
      const response = await this.client.get<KRStockTickerResponse>(`/kr_stocks/ticker/${stk_cd}`);
      return response.data;
    });
  }

  /**
   * Get candle (OHLCV) data for a Korean stock.
   * Uses request queue to prevent rate limit errors.
   */
  async getKRStockCandles(
    stk_cd: string,
    period: string = 'D',
    count: number = 100
  ): Promise<{
    stk_cd: string;
    period: string;
    candles: Array<{
      datetime: string;
      open: number;
      high: number;
      low: number;
      close: number;
      volume: number;
    }>;
  }> {
    // Queue the request to prevent overwhelming the Kiwoom API
    return kiwoomRequestQueue.enqueue(async () => {
      const response = await this.client.get(`/kr_stocks/candles/${stk_cd}`, {
        params: { period, count },
      });

      // Transform Kiwoom API field names to standard format
      // Backend returns: stck_bsop_date, stck_oprc, stck_hgpr, stck_lwpr, stck_clpr, acml_vol
      // Frontend expects: datetime, open, high, low, close, volume
      const transformedCandles = response.data.candles.map((candle: {
        stck_bsop_date: string;
        stck_oprc: number;
        stck_hgpr: number;
        stck_lwpr: number;
        stck_clpr: number;
        acml_vol: number;
      }) => ({
        // Convert YYYYMMDD to ISO date string
        datetime: `${candle.stck_bsop_date.slice(0, 4)}-${candle.stck_bsop_date.slice(4, 6)}-${candle.stck_bsop_date.slice(6, 8)}`,
        open: candle.stck_oprc,
        high: candle.stck_hgpr,
        low: candle.stck_lwpr,
        close: candle.stck_clpr,
        volume: candle.acml_vol,
      }));

      return {
        stk_cd: response.data.stk_cd,
        period: response.data.period,
        candles: transformedCandles,
      };
    });
  }

  /**
   * Get orderbook for a Korean stock.
   * Uses request queue to prevent rate limit errors.
   */
  async getKRStockOrderbook(stk_cd: string): Promise<{
    stk_cd: string;
    asks: Array<{ price: number; volume: number }>;
    bids: Array<{ price: number; volume: number }>;
    timestamp: string;
  }> {
    // Queue the request to prevent overwhelming the Kiwoom API
    return kiwoomRequestQueue.enqueue(async () => {
      const response = await this.client.get(`/kr_stocks/orderbook/${stk_cd}`);
      return response.data;
    });
  }

  // -------------------------------------------
  // Korean Stock Analysis Endpoints
  // -------------------------------------------

  /**
   * Start a new Korean stock analysis session.
   */
  async startKRStockAnalysis(request: KRStockAnalysisRequest): Promise<KRStockAnalysisResponse> {
    const response = await this.client.post<KRStockAnalysisResponse>(
      '/kr_stocks/analysis/start',
      request
    );
    return response.data;
  }

  /**
   * Get Korean stock analysis session status.
   */
  async getKRStockSessionStatus(sessionId: string): Promise<KRStockAnalysisStatus> {
    const response = await this.client.get<KRStockAnalysisStatus>(
      `/kr_stocks/analysis/status/${sessionId}`
    );
    return response.data;
  }

  /**
   * Cancel a Korean stock analysis session.
   */
  async cancelKRStockSession(sessionId: string): Promise<{ message: string }> {
    const response = await this.client.post(`/kr_stocks/analysis/cancel/${sessionId}`);
    return response.data;
  }

  // -------------------------------------------
  // Korean Stock Trading Endpoints
  // -------------------------------------------

  /**
   * Get Kiwoom account information.
   */
  async getKRStockAccount(): Promise<KRStockAccountResponse> {
    const response = await this.client.get<KRStockAccountResponse>('/kr_stocks/accounts');
    return response.data;
  }

  /**
   * Get all Korean stock positions.
   */
  async getKRStockPositions(): Promise<KRStockPositionListResponse> {
    const response = await this.client.get<KRStockPositionListResponse>('/kr_stocks/positions');
    return response.data;
  }

  /**
   * Get a single Korean stock position.
   */
  async getKRStockPosition(stk_cd: string): Promise<KRStockPosition> {
    const response = await this.client.get<KRStockPosition>(`/kr_stocks/positions/${stk_cd}`);
    return response.data;
  }

  /**
   * Close a Korean stock position.
   */
  async closeKRStockPosition(stk_cd: string): Promise<KRStockOrder> {
    const response = await this.client.post<KRStockOrder>(`/kr_stocks/positions/${stk_cd}/close`);
    return response.data;
  }

  /**
   * Get list of Korean stock orders.
   */
  async getKRStockOrders(params?: {
    stk_cd?: string;
    status?: string;
    limit?: number;
  }): Promise<KRStockOrderListResponse> {
    const response = await this.client.get<KRStockOrderListResponse>('/kr_stocks/orders', {
      params,
    });
    return response.data;
  }

  /**
   * Get a single Korean stock order.
   */
  async getKRStockOrder(orderId: string): Promise<KRStockOrder> {
    const response = await this.client.get<KRStockOrder>(`/kr_stocks/orders/${orderId}`);
    return response.data;
  }

  /**
   * Create a new Korean stock order.
   */
  async createKRStockOrder(request: KRStockOrderRequest): Promise<KRStockOrder> {
    const response = await this.client.post<KRStockOrder>('/kr_stocks/orders', request);
    return response.data;
  }

  /**
   * Cancel a Korean stock order.
   */
  async cancelKRStockOrder(orderId: string): Promise<KRStockOrder> {
    const response = await this.client.delete<KRStockOrder>(`/kr_stocks/orders/${orderId}`);
    return response.data;
  }

  /**
   * Get Korean stock trade history.
   */
  async getKRStockTrades(params?: {
    stk_cd?: string;
    page?: number;
    limit?: number;
  }): Promise<KRStockTradeListResponse> {
    const response = await this.client.get<KRStockTradeListResponse>('/kr_stocks/trades', {
      params,
    });
    return response.data;
  }

  /**
   * Get a single Korean stock trade.
   */
  async getKRStockTrade(tradeId: string): Promise<KRStockTradeRecord> {
    const response = await this.client.get<KRStockTradeRecord>(`/kr_stocks/trades/${tradeId}`);
    return response.data;
  }

  // -------------------------------------------
  // Kiwoom Settings Endpoints
  // -------------------------------------------

  /**
   * Get Kiwoom API key status.
   */
  async getKiwoomApiStatus(): Promise<KiwoomApiKeyStatus> {
    const response = await this.client.get<KiwoomApiKeyStatus>('/settings/kiwoom');
    return response.data;
  }

  /**
   * Update Kiwoom API keys.
   */
  async updateKiwoomApiKeys(request: KiwoomApiKeyRequest): Promise<KiwoomApiKeyResponse> {
    const response = await this.client.post<KiwoomApiKeyResponse>('/settings/kiwoom', request);
    return response.data;
  }

  /**
   * Validate Kiwoom API keys.
   */
  async validateKiwoomApiKeys(): Promise<KiwoomValidateResponse> {
    const response = await this.client.post<KiwoomValidateResponse>('/settings/kiwoom/validate');
    return response.data;
  }

  /**
   * Clear Kiwoom API keys.
   */
  async clearKiwoomApiKeys(): Promise<{ message: string }> {
    const response = await this.client.delete('/settings/kiwoom');
    return response.data;
  }

  // -------------------------------------------
  // Translation Endpoints
  // -------------------------------------------

  /**
   * Translate text between Korean and English.
   */
  async translateText(
    text: string,
    targetLanguage: 'en' | 'ko' = 'en'
  ): Promise<{
    original: string;
    translated: string;
    target_language: string;
  }> {
    const response = await this.client.post('/analysis/translate', {
      text,
      target_language: targetLanguage,
    });
    return response.data;
  }

  // -------------------------------------------
  // Chat Endpoints
  // -------------------------------------------

  /**
   * Send a message to the Trading Assistant.
   * Phase 13: Now supports structured trading context.
   */
  async sendChatMessage(
    message: string,
    options?: {
      context?: string;  // Legacy simple context
      tradingContext?: {  // Phase 13 structured context
        activeAnalysis?: {
          ticker: string;
          displayName: string;
          marketType: string;
          status: string;
          recommendation?: string;
          confidence?: number;
          currentPrice?: number;
          entryPrice?: number;
          stopLoss?: number;
          takeProfit?: number;
          keySignals?: string[];
        };
        recentDecisions?: Array<{
          ticker: string;
          displayName: string;
          action: string;
          tradeAction: string;
          timestamp: string;
          quantity?: number;
          price?: number;
          rationale?: string;
        }>;
        positions?: Array<{
          ticker: string;
          displayName?: string;
          quantity: number;
        }>;
      };
      history?: Array<{ role: string; content: string }>;
    }
  ): Promise<{
    message: string;
    role: string;
  }> {
    const response = await this.client.post('/chat/', {
      message,
      context: options?.context,
      tradingContext: options?.tradingContext,
      history: options?.history,
    });
    return response.data;
  }

  // -------------------------------------------
  // Auto-Trading Endpoints
  // -------------------------------------------

  /**
   * Start the auto-trading system.
   */
  async startTrading(riskParams?: Record<string, unknown>): Promise<{
    status: string;
    mode: string;
    message: string;
  }> {
    const response = await this.client.post('/trading/start', {
      risk_params: riskParams,
    });
    return response.data;
  }

  /**
   * Stop the auto-trading system.
   */
  async stopTrading(): Promise<{
    status: string;
    mode: string;
    message: string;
  }> {
    const response = await this.client.post('/trading/stop');
    return response.data;
  }

  /**
   * Pause the auto-trading system.
   */
  async pauseTrading(reason?: string): Promise<{
    status: string;
    mode: string;
    message: string;
  }> {
    const response = await this.client.post('/trading/pause', null, {
      params: { reason },
    });
    return response.data;
  }

  /**
   * Resume the auto-trading system.
   */
  async resumeTrading(): Promise<{
    status: string;
    mode: string;
    message: string;
  }> {
    const response = await this.client.post('/trading/resume');
    return response.data;
  }

  /**
   * Get trading system status.
   */
  async getTradingStatus(): Promise<{
    mode: string;
    is_active: boolean;
    started_at: string | null;
    daily_trades: number;
    max_daily_trades: number;
    pending_alerts_count: number;
  }> {
    const response = await this.client.get('/trading/status');
    return response.data;
  }

  /**
   * Get portfolio summary.
   */
  async getTradingPortfolio(): Promise<{
    total_equity: number;
    cash: number;
    cash_ratio: number;
    stock_value: number;
    stock_ratio: number;
    positions: unknown[];
    total_unrealized_pnl: number;
    total_unrealized_pnl_pct: number;
    daily_trades: number;
    max_daily_trades: number;
  }> {
    const response = await this.client.get('/trading/portfolio');
    return response.data;
  }

  /**
   * Get full trading state.
   */
  async getTradingState(): Promise<Record<string, unknown>> {
    const response = await this.client.get('/trading/state');
    return response.data;
  }

  /**
   * Get pending alerts.
   */
  async getTradingAlerts(): Promise<{
    alerts: unknown[];
    count: number;
  }> {
    const response = await this.client.get('/trading/alerts');
    return response.data;
  }

  /**
   * Handle alert action.
   */
  async handleTradingAlertAction(
    alertId: string,
    action: string,
    data?: Record<string, unknown>
  ): Promise<{
    status: string;
    message: string;
  }> {
    const response = await this.client.post('/trading/alerts/action', {
      alert_id: alertId,
      action,
      data,
    });
    return response.data;
  }

  /**
   * Get risk parameters.
   */
  async getTradingRiskParams(): Promise<Record<string, unknown>> {
    const response = await this.client.get('/trading/risk-params');
    return response.data;
  }

  /**
   * Update risk parameters.
   */
  async updateTradingRiskParams(params: Record<string, unknown>): Promise<{
    status: string;
    risk_params: Record<string, unknown>;
  }> {
    const response = await this.client.put('/trading/risk-params', params);
    return response.data;
  }

  /**
   * Get managed positions.
   */
  async getTradingPositions(): Promise<{
    positions: unknown[];
    count: number;
  }> {
    const response = await this.client.get('/trading/positions');
    return response.data;
  }

  /**
   * Close a position.
   */
  async closeTradingPosition(ticker: string): Promise<{
    status: string;
    ticker: string;
    message: string;
  }> {
    const response = await this.client.delete(`/trading/positions/${ticker}`);
    return response.data;
  }

  /**
   * Update position stop-loss.
   */
  async updatePositionStopLoss(
    ticker: string,
    stopLoss: number
  ): Promise<{
    status: string;
    ticker: string;
    stop_loss: number;
  }> {
    const response = await this.client.put(
      `/trading/positions/${ticker}/stop-loss`,
      null,
      { params: { stop_loss: stopLoss } }
    );
    return response.data;
  }

  /**
   * Update position take-profit.
   */
  async updatePositionTakeProfit(
    ticker: string,
    takeProfit: number
  ): Promise<{
    status: string;
    ticker: string;
    take_profit: number;
  }> {
    const response = await this.client.put(
      `/trading/positions/${ticker}/take-profit`,
      null,
      { params: { take_profit: takeProfit } }
    );
    return response.data;
  }

  /**
   * Get trading activity log.
   */
  async getTradingActivity(limit = 50): Promise<{
    activities: Array<{
      id: string;
      activity_type: string;
      agent: string;
      ticker: string | null;
      message: string;
      details: Record<string, unknown> | null;
      timestamp: string;
    }>;
    count: number;
  }> {
    const response = await this.client.get('/trading/activity', {
      params: { limit },
    });
    return response.data;
  }

  /**
   * Get market hours status.
   */
  async getMarketHours(): Promise<{
    krx: {
      market: string;
      name: string;
      is_open: boolean;
      current_time: string;
      next_open: string | null;
      next_close: string | null;
      message: string;
    };
    crypto: {
      market: string;
      name: string;
      is_open: boolean;
      current_time: string;
      message: string;
    };
  }> {
    const response = await this.client.get('/trading/market-hours');
    return response.data;
  }

  // -------------------------------------------
  // Trading Strategy Endpoints
  // -------------------------------------------

  /**
   * Get all available strategy presets.
   */
  async getStrategyPresets(): Promise<{
    presets: Record<string, {
      name: string;
      description: string;
      risk_tolerance: string;
      trading_style: string;
      entry_conditions: Record<string, unknown>;
      exit_conditions: Record<string, unknown>;
      position_sizing: Record<string, unknown>;
    }>;
    risk_tolerances: string[];
    trading_styles: string[];
  }> {
    const response = await this.client.get('/trading/strategies/presets');
    return response.data;
  }

  /**
   * Get a specific preset details.
   */
  async getPresetDetails(presetName: string): Promise<TradingStrategyResponse> {
    const response = await this.client.get(`/trading/strategies/presets/${presetName}`);
    return response.data;
  }

  /**
   * Get the current trading strategy.
   */
  async getCurrentStrategy(): Promise<TradingStrategyResponse | { strategy: null; message: string }> {
    const response = await this.client.get('/trading/strategy');
    return response.data;
  }

  /**
   * Create and set a new trading strategy.
   */
  async setStrategy(request: TradingStrategyRequest): Promise<{
    status: string;
    strategy: TradingStrategyResponse;
  }> {
    const response = await this.client.post('/trading/strategy', request);
    return response.data;
  }

  /**
   * Update the current trading strategy.
   */
  async updateStrategy(request: Partial<TradingStrategyRequest>): Promise<{
    status: string;
    strategy: TradingStrategyResponse;
  }> {
    const response = await this.client.put('/trading/strategy', request);
    return response.data;
  }

  /**
   * Clear the current trading strategy.
   */
  async clearStrategy(): Promise<{
    status: string;
    message: string;
  }> {
    const response = await this.client.delete('/trading/strategy');
    return response.data;
  }

  /**
   * Apply a preset strategy directly.
   */
  async applyStrategyPreset(presetName: string): Promise<{
    status: string;
    preset: string;
    strategy: TradingStrategyResponse;
  }> {
    const response = await this.client.post(`/trading/strategy/apply-preset/${presetName}`);
    return response.data;
  }

  // -------------------------------------------
  // Trade Queue Endpoints
  // -------------------------------------------

  /**
   * Get trades in queue.
   *
   * @param includeAll - If true, returns all trades including FAILED/COMPLETED/CANCELLED.
   *                    If false (default), returns only PENDING and PROCESSING trades.
   */
  async getTradeQueue(includeAll: boolean = false): Promise<{
    queue: Array<{
      id: string;
      session_id: string;
      ticker: string;
      stock_name: string | null;
      action: string;
      entry_price: number;
      quantity: number | null;
      stop_loss: number | null;
      take_profit: number | null;
      risk_score: number;
      status: string;
      reason: string;
      queued_at: string;
      executed_at: string | null;
      error_message: string | null;
    }>;
    count: number;
  }> {
    const response = await this.client.get('/trading/queue', {
      params: { include_all: includeAll },
    });
    return response.data;
  }

  /**
   * Cancel a queued trade.
   */
  async cancelQueuedTrade(queueId: string): Promise<{
    status: string;
    queue_id: string;
  }> {
    const response = await this.client.delete(`/trading/queue/${queueId}`);
    return response.data;
  }

  /**
   * Dismiss a completed/failed/cancelled trade from the queue.
   * Removes the trade entirely from the queue.
   */
  async dismissTrade(queueId: string): Promise<{
    status: string;
    queue_id: string;
  }> {
    const response = await this.client.delete(`/trading/queue/${queueId}/dismiss`);
    return response.data;
  }

  /**
   * Manually process the trade queue.
   */
  async processTradeQueue(): Promise<{
    status: string;
    message: string;
  }> {
    const response = await this.client.post('/trading/queue/process');
    return response.data;
  }

  /**
   * Add a trade directly to the queue.
   * Bypasses the approval flow - useful for completed analyses.
   */
  async addToTradeQueue(params: {
    ticker: string;
    stock_name?: string;
    action: string;
    entry_price: number;
    stop_loss?: number;
    take_profit?: number;
    risk_score?: number;
    session_id?: string;
    reason?: string;
  }): Promise<{
    status: string;
    queue_id: string;
    ticker: string;
    action: string;
    message: string;
  }> {
    const response = await this.client.post('/trading/queue/add', params);
    return response.data;
  }

  // -------------------------------------------
  // Agent Status Endpoints
  // -------------------------------------------

  /**
   * Get status of all trading agents.
   */
  async getAgentStates(): Promise<{
    agents: Record<string, {
      name: string;
      status: 'idle' | 'working' | 'waiting' | 'error';
      current_task: string | null;
      last_action: string | null;
      last_action_time: string | null;
      error_message: string | null;
      tasks_completed: number;
      tasks_failed: number;
      // 세부 정보 (Sub Agent Status 개선)
      processing_stock?: string | null;
      processing_stock_name?: string | null;
      trade_details?: {
        action?: string;
        quantity?: number;
        entry_price?: number;
        stop_loss?: number;
        take_profit?: number;
        risk_score?: number;
        estimated_amount?: number;
        total_amount?: number;
        position_pct?: number;
      } | null;
      analysis_summary?: {
        technical?: { signal: string; confidence: number; key_factors?: string[] };
        fundamental?: { signal: string; confidence: number; key_factors?: string[] };
        sentiment?: { signal: string; confidence: number; key_factors?: string[] };
        risk?: { level: string; score: number; factors?: string[] };
      } | null;
      last_result?: {
        success: boolean;
        message: string;
        order_id?: string;
        filled_quantity?: number;
        avg_price?: number;
        quantity?: number;
        estimated_amount?: number;
      } | null;
    }>;
  }> {
    const response = await this.client.get('/trading/agents');
    return response.data;
  }

  // -------------------------------------------
  // Watch List Endpoints
  // -------------------------------------------

  /**
   * Get all stocks in watch list.
   */
  async getWatchList(): Promise<WatchListResponse> {
    const response = await this.client.get<WatchListResponse>('/trading/watch-list');
    return response.data;
  }

  /**
   * Get a watched stock by ticker.
   */
  async getWatchedStock(ticker: string): Promise<WatchedStock> {
    const response = await this.client.get<WatchedStock>(`/trading/watch-list/${ticker}`);
    return response.data;
  }

  /**
   * Add a stock to watch list.
   */
  async addToWatchList(request: AddToWatchListRequest): Promise<AddToWatchListResponse> {
    const response = await this.client.post<AddToWatchListResponse>(
      '/trading/watch-list/add',
      request
    );
    return response.data;
  }

  /**
   * Remove a stock from watch list.
   */
  async removeFromWatchList(watchId: string): Promise<{ status: string; watch_id: string }> {
    const response = await this.client.delete(`/trading/watch-list/${watchId}`);
    return response.data;
  }

  /**
   * Convert a watched stock to trade queue.
   */
  async convertWatchToQueue(request: ConvertWatchToQueueRequest): Promise<ConvertWatchToQueueResponse> {
    const response = await this.client.post<ConvertWatchToQueueResponse>(
      '/trading/watch-list/convert',
      request
    );
    return response.data;
  }

  // -------------------------------------------
  // Background Scanner API
  // -------------------------------------------

  async startScan(request?: StartScanRequest): Promise<{ status: string; message: string; total_stocks: number }> {
    const response = await this.client.post<{ status: string; message: string; total_stocks: number }>(
      '/scanner/start',
      request || {}
    );
    return response.data;
  }

  async pauseScan(): Promise<{ status: string; message: string }> {
    const response = await this.client.post<{ status: string; message: string }>('/scanner/pause');
    return response.data;
  }

  async resumeScan(): Promise<{ status: string; message: string }> {
    const response = await this.client.post<{ status: string; message: string }>('/scanner/resume');
    return response.data;
  }

  async stopScan(): Promise<{ status: string; message: string }> {
    const response = await this.client.post<{ status: string; message: string }>('/scanner/stop');
    return response.data;
  }

  async getScanProgress(): Promise<ScanProgressResponse> {
    const response = await this.client.get<ScanProgressResponse>('/scanner/progress');
    return response.data;
  }

  async getScanResults(action?: string): Promise<ScanResultsResponse> {
    const params = action ? { action } : {};
    const response = await this.client.get<ScanResultsResponse>('/scanner/results', { params });
    return response.data;
  }

  /**
   * Get scan results from database with pagination
   */
  async getScanResultsFromDb(params: {
    action?: string;
    session_id?: string;
    limit?: number;
    offset?: number;
  } = {}): Promise<ScanResultsResponse> {
    const response = await this.client.get<ScanResultsResponse>('/scanner/db/results', { params });
    return response.data;
  }

  /**
   * Get action counts from database
   */
  async getScanCounts(session_id?: string): Promise<{
    buy_count: number;
    sell_count: number;
    hold_count: number;
    watch_count: number;
    avoid_count: number;
    total: number;
  }> {
    const params = session_id ? { session_id } : {};
    const response = await this.client.get('/scanner/db/counts', { params });
    return response.data;
  }

  /**
   * Get recent scan sessions
   */
  async getScanSessions(limit: number = 10): Promise<{
    sessions: Array<{
      id: string;
      started_at: string | null;
      completed_at: string | null;
      total_stocks: number;
      completed: number;
      failed: number;
      buy_count: number;
      sell_count: number;
      hold_count: number;
      watch_count: number;
      avoid_count: number;
      status: string;
    }>;
    count: number;
  }> {
    const response = await this.client.get('/scanner/db/sessions', { params: { limit } });
    return response.data;
  }
}

// -------------------------------------------
// Singleton Export
// -------------------------------------------

export const apiClient = new ApiClient();

// -------------------------------------------
// Convenience Functions
// -------------------------------------------

export const startAnalysis = (request: AnalysisRequest) =>
  apiClient.startAnalysis(request);

export const getSessionStatus = (sessionId: string) =>
  apiClient.getSessionStatus(sessionId);

export const getSessionState = (sessionId: string) =>
  apiClient.getSessionState(sessionId);

export const cancelSession = (sessionId: string) =>
  apiClient.cancelSession(sessionId);

export const listSessions = () => apiClient.listSessions();

export const getPendingProposal = (sessionId: string) =>
  apiClient.getPendingProposal(sessionId);

export const submitApproval = (request: ApprovalRequest) =>
  apiClient.submitApproval(request);

export const healthCheck = () => apiClient.healthCheck();

// Coin API
export const getCoinMarkets = (quoteCurrency?: string) =>
  apiClient.getCoinMarkets(quoteCurrency);

export const searchCoinMarkets = (query: string, limit?: number) =>
  apiClient.searchCoinMarkets(query, limit);

export const startCoinAnalysis = (request: CoinAnalysisRequest) =>
  apiClient.startCoinAnalysis(request);

export const getCoinSessionStatus = (sessionId: string) =>
  apiClient.getCoinSessionStatus(sessionId);

export const cancelCoinSession = (sessionId: string) =>
  apiClient.cancelCoinSession(sessionId);

// Coin Market Data API
export const getCoinCandles = (market: string, interval?: string, count?: number) =>
  apiClient.getCoinCandles(market, interval, count);

export const getCoinTicker = (market: string) => apiClient.getCoinTicker(market);

export const getCoinTickers = (markets: string[]) => apiClient.getCoinTickers(markets);

export const getCoinOrderbook = (market: string) => apiClient.getCoinOrderbook(market);

// Settings API
export const getSettings = () => apiClient.getSettings();

export const getUpbitApiStatus = () => apiClient.getUpbitApiStatus();

export const updateUpbitApiKeys = (request: UpbitApiKeyRequest) =>
  apiClient.updateUpbitApiKeys(request);

export const validateUpbitApiKeys = () => apiClient.validateUpbitApiKeys();

export const clearUpbitApiKeys = () => apiClient.clearUpbitApiKeys();

// Coin Trading API
export const getCoinAccounts = () => apiClient.getCoinAccounts();

export const getCoinPositions = () => apiClient.getCoinPositions();

export const getCoinPosition = (market: string) => apiClient.getCoinPosition(market);

export const closeCoinPosition = (market: string) => apiClient.closeCoinPosition(market);

export const getCoinOrders = (params?: { market?: string; state?: string; limit?: number }) =>
  apiClient.getCoinOrders(params);

export const getCoinOrder = (orderId: string) => apiClient.getCoinOrder(orderId);

export const createCoinOrder = (request: CoinOrderRequest) =>
  apiClient.createCoinOrder(request);

export const cancelCoinOrder = (orderId: string) => apiClient.cancelCoinOrder(orderId);

export const getCoinTrades = (params?: { market?: string; page?: number; limit?: number }) =>
  apiClient.getCoinTrades(params);

export const getCoinTrade = (tradeId: string) => apiClient.getCoinTrade(tradeId);

// Korean Stock (Kiwoom) API
export const getKRStocks = (limit?: number) => apiClient.getKRStocks(limit);

export const searchKRStocks = (query: string, limit?: number) =>
  apiClient.searchKRStocks(query, limit);

export const getKRStockTicker = (stk_cd: string) => apiClient.getKRStockTicker(stk_cd);

export const getKRStockCandles = (stk_cd: string, period?: string, count?: number) =>
  apiClient.getKRStockCandles(stk_cd, period, count);

export const getKRStockOrderbook = (stk_cd: string) => apiClient.getKRStockOrderbook(stk_cd);

export const startKRStockAnalysis = (request: KRStockAnalysisRequest) =>
  apiClient.startKRStockAnalysis(request);

export const getKRStockSessionStatus = (sessionId: string) =>
  apiClient.getKRStockSessionStatus(sessionId);

export const cancelKRStockSession = (sessionId: string) =>
  apiClient.cancelKRStockSession(sessionId);

export const getKRStockAccount = () => apiClient.getKRStockAccount();

export const getKRStockPositions = () => apiClient.getKRStockPositions();

export const getKRStockPosition = (stk_cd: string) => apiClient.getKRStockPosition(stk_cd);

export const closeKRStockPosition = (stk_cd: string) => apiClient.closeKRStockPosition(stk_cd);

export const getKRStockOrders = (params?: { stk_cd?: string; status?: string; limit?: number }) =>
  apiClient.getKRStockOrders(params);

export const getKRStockOrder = (orderId: string) => apiClient.getKRStockOrder(orderId);

export const createKRStockOrder = (request: KRStockOrderRequest) =>
  apiClient.createKRStockOrder(request);

export const cancelKRStockOrder = (orderId: string) => apiClient.cancelKRStockOrder(orderId);

export const getKRStockTrades = (params?: { stk_cd?: string; page?: number; limit?: number }) =>
  apiClient.getKRStockTrades(params);

export const getKRStockTrade = (tradeId: string) => apiClient.getKRStockTrade(tradeId);

// Kiwoom Settings API
export const getKiwoomApiStatus = () => apiClient.getKiwoomApiStatus();

export const updateKiwoomApiKeys = (request: KiwoomApiKeyRequest) =>
  apiClient.updateKiwoomApiKeys(request);

export const validateKiwoomApiKeys = () => apiClient.validateKiwoomApiKeys();

export const clearKiwoomApiKeys = () => apiClient.clearKiwoomApiKeys();

// Translation API
export const translateText = (text: string, targetLanguage: 'en' | 'ko' = 'en') =>
  apiClient.translateText(text, targetLanguage);

// Chat API
export const sendChatMessage = (
  message: string,
  options?: Parameters<typeof apiClient.sendChatMessage>[1]
) => apiClient.sendChatMessage(message, options);

// Auto-Trading API
export const startTrading = (riskParams?: Record<string, unknown>) =>
  apiClient.startTrading(riskParams);

export const stopTrading = () => apiClient.stopTrading();

export const pauseTrading = (reason?: string) => apiClient.pauseTrading(reason);

export const resumeTrading = () => apiClient.resumeTrading();

export const getTradingStatus = () => apiClient.getTradingStatus();

export const getTradingPortfolio = () => apiClient.getTradingPortfolio();

export const getTradingState = () => apiClient.getTradingState();

export const getTradingAlerts = () => apiClient.getTradingAlerts();

export const handleTradingAlertAction = (
  alertId: string,
  action: string,
  data?: Record<string, unknown>
) => apiClient.handleTradingAlertAction(alertId, action, data);

export const getTradingRiskParams = () => apiClient.getTradingRiskParams();

export const updateTradingRiskParams = (params: Record<string, unknown>) =>
  apiClient.updateTradingRiskParams(params);

export const getTradingPositions = () => apiClient.getTradingPositions();

export const closeTradingPosition = (ticker: string) =>
  apiClient.closeTradingPosition(ticker);

export const updatePositionStopLoss = (ticker: string, stopLoss: number) =>
  apiClient.updatePositionStopLoss(ticker, stopLoss);

export const updatePositionTakeProfit = (ticker: string, takeProfit: number) =>
  apiClient.updatePositionTakeProfit(ticker, takeProfit);

export const getTradingActivity = (limit = 50) =>
  apiClient.getTradingActivity(limit);

export const getMarketHours = () => apiClient.getMarketHours();

// Strategy API
export const getStrategyPresets = () => apiClient.getStrategyPresets();

export const getPresetDetails = (presetName: string) =>
  apiClient.getPresetDetails(presetName);

export const getCurrentStrategy = () => apiClient.getCurrentStrategy();

export const setStrategy = (request: TradingStrategyRequest) =>
  apiClient.setStrategy(request);

export const updateStrategy = (request: Partial<TradingStrategyRequest>) =>
  apiClient.updateStrategy(request);

export const clearStrategy = () => apiClient.clearStrategy();

export const applyStrategyPreset = (presetName: string) =>
  apiClient.applyStrategyPreset(presetName);

// Trade Queue API
export const getTradeQueue = (includeAll: boolean = false) =>
  apiClient.getTradeQueue(includeAll);

export const cancelQueuedTrade = (queueId: string) =>
  apiClient.cancelQueuedTrade(queueId);

export const dismissTrade = (queueId: string) =>
  apiClient.dismissTrade(queueId);

export const processTradeQueue = () => apiClient.processTradeQueue();

export const addToTradeQueue = (params: {
  ticker: string;
  stock_name?: string;
  action: string;
  entry_price: number;
  stop_loss?: number;
  take_profit?: number;
  risk_score?: number;
  session_id?: string;
  reason?: string;
}) => apiClient.addToTradeQueue(params);

// Agent Status API
export const getAgentStates = () => apiClient.getAgentStates();

// Watch List API
export const getWatchList = () => apiClient.getWatchList();

export const getWatchedStock = (ticker: string) => apiClient.getWatchedStock(ticker);

export const addToWatchList = (request: AddToWatchListRequest) =>
  apiClient.addToWatchList(request);

export const removeFromWatchList = (watchId: string) =>
  apiClient.removeFromWatchList(watchId);

export const convertWatchToQueue = (request: ConvertWatchToQueueRequest) =>
  apiClient.convertWatchToQueue(request);

// Background Scanner API
export const startScan = (request?: StartScanRequest) =>
  apiClient.startScan(request);

export const pauseScan = () => apiClient.pauseScan();

export const resumeScan = () => apiClient.resumeScan();

export const stopScan = () => apiClient.stopScan();

export const getScanProgress = () => apiClient.getScanProgress();

export const getScanResults = (action?: string) =>
  apiClient.getScanResults(action);
