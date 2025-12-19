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
  SettingsStatus,
  UpbitApiKeyRequest,
  UpbitApiKeyResponse,
  UpbitApiKeyStatus,
  UpbitValidateResponse,
} from '@/types';

// -------------------------------------------
// Configuration
// -------------------------------------------

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

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

export const getCoinOrderbook = (market: string) => apiClient.getCoinOrderbook(market);

// Settings API
export const getSettings = () => apiClient.getSettings();

export const getUpbitApiStatus = () => apiClient.getUpbitApiStatus();

export const updateUpbitApiKeys = (request: UpbitApiKeyRequest) =>
  apiClient.updateUpbitApiKeys(request);

export const validateUpbitApiKeys = () => apiClient.validateUpbitApiKeys();

export const clearUpbitApiKeys = () => apiClient.clearUpbitApiKeys();
