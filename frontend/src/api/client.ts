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
