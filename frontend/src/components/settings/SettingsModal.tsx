/**
 * Settings Modal Component
 *
 * Provides UI for configuring application settings including:
 * - Upbit API keys for cryptocurrency trading
 * - Other settings (LLM, etc.)
 */

import { useState, useEffect } from 'react';
import {
  X,
  Key,
  CheckCircle2,
  XCircle,
  Loader2,
  Eye,
  EyeOff,
  AlertCircle,
  Settings,
} from 'lucide-react';
import {
  getUpbitApiStatus,
  updateUpbitApiKeys,
  validateUpbitApiKeys,
  clearUpbitApiKeys,
  getSettings,
} from '@/api/client';
import type { UpbitApiKeyStatus, SettingsStatus } from '@/types';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<'upbit' | 'general'>('upbit');
  const [upbitStatus, setUpbitStatus] = useState<UpbitApiKeyStatus | null>(null);
  const [settings, setSettings] = useState<SettingsStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Upbit API form state
  const [accessKey, setAccessKey] = useState('');
  const [secretKey, setSecretKey] = useState('');
  const [showAccessKey, setShowAccessKey] = useState(false);
  const [showSecretKey, setShowSecretKey] = useState(false);
  const [validating, setValidating] = useState(false);

  // Load settings on open
  useEffect(() => {
    if (isOpen) {
      loadSettings();
    }
  }, [isOpen]);

  const loadSettings = async () => {
    try {
      setLoading(true);
      setError(null);
      const [upbit, fullSettings] = await Promise.all([
        getUpbitApiStatus(),
        getSettings(),
      ]);
      setUpbitStatus(upbit);
      setSettings(fullSettings);
    } catch (err) {
      setError('Failed to load settings');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveUpbitKeys = async () => {
    if (!accessKey.trim() || !secretKey.trim()) {
      setError('Both Access Key and Secret Key are required');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setSuccess(null);

      const response = await updateUpbitApiKeys({
        access_key: accessKey.trim(),
        secret_key: secretKey.trim(),
      });

      if (response.success) {
        setUpbitStatus(response.status);
        setAccessKey('');
        setSecretKey('');
        setSuccess('API keys updated. Click "Validate" to test them.');
      } else {
        setError(response.message);
      }
    } catch (err) {
      setError('Failed to update API keys');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleValidateKeys = async () => {
    try {
      setValidating(true);
      setError(null);
      setSuccess(null);

      const response = await validateUpbitApiKeys();

      if (response.is_valid) {
        setSuccess(`Validation successful! Found ${response.account_count} account(s).`);
        // Reload status to get updated validation info
        const status = await getUpbitApiStatus();
        setUpbitStatus(status);
      } else {
        setError(`Validation failed: ${response.message}`);
      }
    } catch (err) {
      setError('Failed to validate API keys');
      console.error(err);
    } finally {
      setValidating(false);
    }
  };

  const handleClearKeys = async () => {
    if (!confirm('Are you sure you want to clear the API keys?')) {
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setSuccess(null);

      await clearUpbitApiKeys();
      const status = await getUpbitApiStatus();
      setUpbitStatus(status);
      setSuccess('API keys cleared');
    } catch (err) {
      setError('Failed to clear API keys');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-background border border-border rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-border">
          <div className="flex items-center gap-3">
            <Settings className="w-5 h-5 text-blue-400" />
            <h2 className="text-lg font-semibold text-white">Settings</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-surface text-gray-400 hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-border">
          <button
            onClick={() => setActiveTab('upbit')}
            className={`px-4 py-3 text-sm font-medium transition-colors ${
              activeTab === 'upbit'
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            Upbit API
          </button>
          <button
            onClick={() => setActiveTab('general')}
            className={`px-4 py-3 text-sm font-medium transition-colors ${
              activeTab === 'general'
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            General
          </button>
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto max-h-[calc(90vh-140px)]">
          {/* Error/Success Messages */}
          {error && (
            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg flex items-center gap-2 text-red-400">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span className="text-sm">{error}</span>
            </div>
          )}
          {success && (
            <div className="mb-4 p-3 bg-green-500/10 border border-green-500/30 rounded-lg flex items-center gap-2 text-green-400">
              <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
              <span className="text-sm">{success}</span>
            </div>
          )}

          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 text-blue-400 animate-spin" />
            </div>
          ) : activeTab === 'upbit' ? (
            <div className="space-y-6">
              {/* Current Status */}
              <div className="bg-surface rounded-lg p-4">
                <h3 className="text-sm font-medium text-gray-300 mb-3">
                  Current Status
                </h3>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-400">Configured</span>
                    <span className="flex items-center gap-1.5">
                      {upbitStatus?.is_configured ? (
                        <>
                          <CheckCircle2 className="w-4 h-4 text-green-400" />
                          <span className="text-sm text-green-400">Yes</span>
                        </>
                      ) : (
                        <>
                          <XCircle className="w-4 h-4 text-gray-500" />
                          <span className="text-sm text-gray-500">No</span>
                        </>
                      )}
                    </span>
                  </div>
                  {upbitStatus?.access_key_masked && (
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-gray-400">Access Key</span>
                      <span className="text-sm font-mono text-gray-300">
                        {upbitStatus.access_key_masked}
                      </span>
                    </div>
                  )}
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-400">Validated</span>
                    <span className="flex items-center gap-1.5">
                      {upbitStatus?.is_valid === true ? (
                        <>
                          <CheckCircle2 className="w-4 h-4 text-green-400" />
                          <span className="text-sm text-green-400">Valid</span>
                        </>
                      ) : upbitStatus?.is_valid === false ? (
                        <>
                          <XCircle className="w-4 h-4 text-red-400" />
                          <span className="text-sm text-red-400">Invalid</span>
                        </>
                      ) : (
                        <span className="text-sm text-gray-500">Not tested</span>
                      )}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-400">Trading Mode</span>
                    <span className={`text-sm font-medium ${
                      upbitStatus?.trading_mode === 'live'
                        ? 'text-orange-400'
                        : 'text-blue-400'
                    }`}>
                      {upbitStatus?.trading_mode?.toUpperCase() || 'PAPER'}
                    </span>
                  </div>
                </div>

                {/* Action Buttons */}
                {upbitStatus?.is_configured && (
                  <div className="flex gap-2 mt-4 pt-4 border-t border-border">
                    <button
                      onClick={handleValidateKeys}
                      disabled={validating}
                      className="flex items-center gap-2 px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:opacity-50 transition-colors"
                    >
                      {validating ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <CheckCircle2 className="w-3.5 h-3.5" />
                      )}
                      Validate
                    </button>
                    <button
                      onClick={handleClearKeys}
                      className="px-3 py-1.5 text-sm text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-colors"
                    >
                      Clear Keys
                    </button>
                  </div>
                )}
              </div>

              {/* API Key Form */}
              <div className="space-y-4">
                <h3 className="text-sm font-medium text-gray-300">
                  {upbitStatus?.is_configured ? 'Update API Keys' : 'Enter API Keys'}
                </h3>
                <p className="text-xs text-gray-500">
                  Get your API keys from{' '}
                  <a
                    href="https://upbit.com/mypage/open_api_management"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:underline"
                  >
                    Upbit Open API Management
                  </a>
                </p>

                {/* Access Key */}
                <div className="space-y-1.5">
                  <label className="text-sm text-gray-400">Access Key</label>
                  <div className="relative">
                    <Key className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                    <input
                      type={showAccessKey ? 'text' : 'password'}
                      value={accessKey}
                      onChange={(e) => setAccessKey(e.target.value)}
                      placeholder="Enter your Upbit Access Key"
                      className="w-full pl-10 pr-10 py-2.5 bg-surface border border-border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                    />
                    <button
                      type="button"
                      onClick={() => setShowAccessKey(!showAccessKey)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                    >
                      {showAccessKey ? (
                        <EyeOff className="w-4 h-4" />
                      ) : (
                        <Eye className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                </div>

                {/* Secret Key */}
                <div className="space-y-1.5">
                  <label className="text-sm text-gray-400">Secret Key</label>
                  <div className="relative">
                    <Key className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                    <input
                      type={showSecretKey ? 'text' : 'password'}
                      value={secretKey}
                      onChange={(e) => setSecretKey(e.target.value)}
                      placeholder="Enter your Upbit Secret Key"
                      className="w-full pl-10 pr-10 py-2.5 bg-surface border border-border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                    />
                    <button
                      type="button"
                      onClick={() => setShowSecretKey(!showSecretKey)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                    >
                      {showSecretKey ? (
                        <EyeOff className="w-4 h-4" />
                      ) : (
                        <Eye className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                </div>

                {/* Save Button */}
                <button
                  onClick={handleSaveUpbitKeys}
                  disabled={loading || !accessKey.trim() || !secretKey.trim()}
                  className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {loading ? (
                    <Loader2 className="w-4 h-4 animate-spin mx-auto" />
                  ) : (
                    'Save API Keys'
                  )}
                </button>
              </div>

              {/* Note */}
              <div className="text-xs text-gray-500 bg-surface/50 rounded-lg p-3">
                <p className="font-medium text-gray-400 mb-1">Note:</p>
                <ul className="list-disc list-inside space-y-0.5">
                  <li>API keys are stored in runtime memory only</li>
                  <li>Keys will be cleared when the server restarts</li>
                  <li>For persistence, set UPBIT_ACCESS_KEY and UPBIT_SECRET_KEY in .env</li>
                  <li>Trading mode is controlled by UPBIT_TRADING_MODE in .env</li>
                </ul>
              </div>
            </div>
          ) : (
            /* General Settings Tab */
            <div className="space-y-4">
              <div className="bg-surface rounded-lg p-4">
                <h3 className="text-sm font-medium text-gray-300 mb-3">
                  System Information
                </h3>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-400">LLM Provider</span>
                    <span className="text-sm text-gray-300">
                      {settings?.llm_provider || 'N/A'}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-400">LLM Model</span>
                    <span className="text-sm text-gray-300 font-mono">
                      {settings?.llm_model || 'N/A'}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-400">Market Data Mode</span>
                    <span className={`text-sm font-medium ${
                      settings?.market_data_mode === 'live'
                        ? 'text-green-400'
                        : 'text-yellow-400'
                    }`}>
                      {settings?.market_data_mode?.toUpperCase() || 'N/A'}
                    </span>
                  </div>
                </div>
              </div>

              <div className="text-xs text-gray-500 bg-surface/50 rounded-lg p-3">
                <p>
                  These settings are configured via environment variables and cannot be
                  changed at runtime. Edit your <code className="text-gray-400">.env</code>{' '}
                  file and restart the server to change them.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
