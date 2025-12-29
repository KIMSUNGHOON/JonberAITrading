/**
 * Settings Modal Component
 *
 * Provides UI for configuring application settings including:
 * - Upbit API keys for cryptocurrency trading
 * - Other settings (LLM, etc.)
 */

import { useState, useEffect, useRef, useCallback } from 'react';
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
  Zap,
} from 'lucide-react';
import {
  getUpbitApiStatus,
  updateUpbitApiKeys,
  validateUpbitApiKeys,
  clearUpbitApiKeys,
  getKiwoomApiStatus,
  updateKiwoomApiKeys,
  validateKiwoomApiKeys,
  clearKiwoomApiKeys,
  getSettings,
} from '@/api/client';
import { useStore } from '@/store';
import type { UpbitApiKeyStatus, KiwoomApiKeyStatus, SettingsStatus } from '@/types';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<'upbit' | 'kiwoom' | 'general'>('upbit');
  const [upbitStatus, setUpbitStatus] = useState<UpbitApiKeyStatus | null>(null);
  const [kiwoomStatus, setKiwoomStatus] = useState<KiwoomApiKeyStatus | null>(null);
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

  // Kiwoom API form state
  const [kiwoomAppKey, setKiwoomAppKey] = useState('');
  const [kiwoomAppSecret, setKiwoomAppSecret] = useState('');
  const [kiwoomAccount, setKiwoomAccount] = useState('');
  const [kiwoomIsMock, setKiwoomIsMock] = useState(false);
  const [showKiwoomAppKey, setShowKiwoomAppKey] = useState(false);
  const [showKiwoomAppSecret, setShowKiwoomAppSecret] = useState(false);
  const [kiwoomValidating, setKiwoomValidating] = useState(false);

  // Input validation state
  const [inputErrors, setInputErrors] = useState<Record<string, string>>({});

  // Refs for auto-focus
  const upbitAccessKeyRef = useRef<HTMLInputElement>(null);
  const kiwoomAppKeyRef = useRef<HTMLInputElement>(null);

  // Store actions for updating global API status
  const setUpbitApiConfigured = useStore((state) => state.setUpbitApiConfigured);
  const setKiwoomApiConfigured = useStore((state) => state.setKiwoomApiConfigured);

  // Load settings on open
  useEffect(() => {
    if (isOpen) {
      loadSettings();
    }
  }, [isOpen]);

  // Auto-focus on tab change
  useEffect(() => {
    if (!isOpen) return;

    // Delay focus to ensure DOM is ready
    const timer = setTimeout(() => {
      if (activeTab === 'upbit' && upbitAccessKeyRef.current) {
        upbitAccessKeyRef.current.focus();
      } else if (activeTab === 'kiwoom' && kiwoomAppKeyRef.current) {
        kiwoomAppKeyRef.current.focus();
      }
    }, 100);

    return () => clearTimeout(timer);
  }, [activeTab, isOpen]);

  // Clear input errors when tab changes
  useEffect(() => {
    setInputErrors({});
    setError(null);
    setSuccess(null);
  }, [activeTab]);

  const loadSettings = async () => {
    try {
      setLoading(true);
      setError(null);
      const [upbit, kiwoom, fullSettings] = await Promise.all([
        getUpbitApiStatus(),
        getKiwoomApiStatus().catch(() => null), // Kiwoom might not be configured
        getSettings(),
      ]);
      setUpbitStatus(upbit);
      setKiwoomStatus(kiwoom);
      setSettings(fullSettings);
    } catch (err) {
      setError('Failed to load settings');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // Validate input fields
  const validateUpbitInputs = useCallback((): boolean => {
    const errors: Record<string, string> = {};

    if (!accessKey.trim()) {
      errors.upbitAccessKey = 'Access Key is required';
    } else if (accessKey.trim().length < 10) {
      errors.upbitAccessKey = 'Access Key seems too short';
    }

    if (!secretKey.trim()) {
      errors.upbitSecretKey = 'Secret Key is required';
    } else if (secretKey.trim().length < 10) {
      errors.upbitSecretKey = 'Secret Key seems too short';
    }

    setInputErrors(errors);
    return Object.keys(errors).length === 0;
  }, [accessKey, secretKey]);

  const validateKiwoomInputs = useCallback((): boolean => {
    const errors: Record<string, string> = {};

    if (!kiwoomAppKey.trim()) {
      errors.kiwoomAppKey = 'App Key is required';
    }

    if (!kiwoomAppSecret.trim()) {
      errors.kiwoomAppSecret = 'App Secret is required';
    }

    if (!kiwoomAccount.trim()) {
      errors.kiwoomAccount = 'Account number is required';
    } else if (!/^\d{8}-\d{2}$/.test(kiwoomAccount.trim())) {
      errors.kiwoomAccount = 'Format: 12345678-01';
    }

    setInputErrors(errors);
    return Object.keys(errors).length === 0;
  }, [kiwoomAppKey, kiwoomAppSecret, kiwoomAccount]);

  // Combined Save & Validate for Upbit
  const handleSaveAndValidateUpbit = async () => {
    if (!validateUpbitInputs()) {
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setSuccess(null);

      // Step 1: Save keys
      const saveResponse = await updateUpbitApiKeys({
        access_key: accessKey.trim(),
        secret_key: secretKey.trim(),
      });

      if (!saveResponse.success) {
        setError(saveResponse.message);
        return;
      }

      setUpbitStatus(saveResponse.status);
      setUpbitApiConfigured(saveResponse.status.is_configured);

      // Step 2: Validate keys
      setValidating(true);
      const validateResponse = await validateUpbitApiKeys();

      if (validateResponse.is_valid) {
        setSuccess(`Setup complete! Found ${validateResponse.account_count} account(s).`);
        setAccessKey('');
        setSecretKey('');
        // Refresh status
        const status = await getUpbitApiStatus();
        setUpbitStatus(status);
      } else {
        setError(`Keys saved but validation failed: ${validateResponse.message}`);
      }
    } catch (err) {
      setError('Failed to setup API keys');
      console.error(err);
    } finally {
      setLoading(false);
      setValidating(false);
    }
  };

  // Combined Save & Validate for Kiwoom
  const handleSaveAndValidateKiwoom = async () => {
    if (!validateKiwoomInputs()) {
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setSuccess(null);

      // Step 1: Save keys
      const saveResponse = await updateKiwoomApiKeys({
        app_key: kiwoomAppKey.trim(),
        app_secret: kiwoomAppSecret.trim(),
        account_number: kiwoomAccount.trim(),
        is_mock: kiwoomIsMock,
      });

      if (!saveResponse.success) {
        setError(saveResponse.message);
        return;
      }

      setKiwoomStatus(saveResponse.status);
      setKiwoomApiConfigured(saveResponse.status.is_configured);

      // Step 2: Validate keys
      setKiwoomValidating(true);
      const validateResponse = await validateKiwoomApiKeys();

      if (validateResponse.is_valid) {
        setSuccess('Kiwoom API setup complete!');
        setKiwoomAppKey('');
        setKiwoomAppSecret('');
        setKiwoomAccount('');
        // Refresh status
        const status = await getKiwoomApiStatus();
        setKiwoomStatus(status);
      } else {
        setError(`Keys saved but validation failed: ${validateResponse.message}`);
      }
    } catch (err) {
      setError('Failed to setup Kiwoom API keys');
      console.error(err);
    } finally {
      setLoading(false);
      setKiwoomValidating(false);
    }
  };

  // Keyboard handler for Enter key
  const handleUpbitKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSaveAndValidateUpbit();
    }
  };

  const handleKiwoomKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSaveAndValidateKiwoom();
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
        setUpbitApiConfigured(response.status.is_configured);
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
      setUpbitApiConfigured(status.is_configured);
      setSuccess('API keys cleared');
    } catch (err) {
      setError('Failed to clear API keys');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // Kiwoom handlers
  const handleSaveKiwoomKeys = async () => {
    if (!kiwoomAppKey.trim() || !kiwoomAppSecret.trim() || !kiwoomAccount.trim()) {
      setError('App Key, App Secret, and Account Number are required');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setSuccess(null);

      const response = await updateKiwoomApiKeys({
        app_key: kiwoomAppKey.trim(),
        app_secret: kiwoomAppSecret.trim(),
        account_number: kiwoomAccount.trim(),
        is_mock: kiwoomIsMock,
      });

      if (response.success) {
        setKiwoomStatus(response.status);
        setKiwoomApiConfigured(response.status.is_configured);
        setKiwoomAppKey('');
        setKiwoomAppSecret('');
        setKiwoomAccount('');
        setSuccess('Kiwoom API keys updated. Click "Validate" to test them.');
      } else {
        setError(response.message);
      }
    } catch (err) {
      setError('Failed to update Kiwoom API keys');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleValidateKiwoomKeys = async () => {
    try {
      setKiwoomValidating(true);
      setError(null);
      setSuccess(null);

      const response = await validateKiwoomApiKeys();

      if (response.is_valid) {
        setSuccess('Kiwoom API validation successful!');
        const status = await getKiwoomApiStatus();
        setKiwoomStatus(status);
        // Update global store so MarketTabs updates immediately
        setKiwoomApiConfigured(status.is_configured);
      } else {
        setError(`Validation failed: ${response.message}`);
      }
    } catch (err) {
      setError('Failed to validate Kiwoom API keys');
      console.error(err);
    } finally {
      setKiwoomValidating(false);
    }
  };

  const handleClearKiwoomKeys = async () => {
    if (!confirm('Are you sure you want to clear the Kiwoom API keys?')) {
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setSuccess(null);

      await clearKiwoomApiKeys();
      const status = await getKiwoomApiStatus().catch(() => null);
      setKiwoomStatus(status);
      setKiwoomApiConfigured(status?.is_configured ?? false);
      setSuccess('Kiwoom API keys cleared');
    } catch (err) {
      setError('Failed to clear Kiwoom API keys');
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
            onClick={() => setActiveTab('kiwoom')}
            className={`px-4 py-3 text-sm font-medium transition-colors ${
              activeTab === 'kiwoom'
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            Kiwoom API
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
                      ref={upbitAccessKeyRef}
                      type={showAccessKey ? 'text' : 'password'}
                      value={accessKey}
                      onChange={(e) => {
                        setAccessKey(e.target.value);
                        if (inputErrors.upbitAccessKey) {
                          setInputErrors((prev) => ({ ...prev, upbitAccessKey: '' }));
                        }
                      }}
                      onKeyDown={handleUpbitKeyDown}
                      placeholder="Enter your Upbit Access Key"
                      className={`w-full pl-10 pr-10 py-2.5 bg-surface border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 ${
                        inputErrors.upbitAccessKey ? 'border-red-500' : 'border-border'
                      }`}
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
                  {inputErrors.upbitAccessKey && (
                    <p className="text-xs text-red-400 flex items-center gap-1">
                      <AlertCircle className="w-3 h-3" />
                      {inputErrors.upbitAccessKey}
                    </p>
                  )}
                </div>

                {/* Secret Key */}
                <div className="space-y-1.5">
                  <label className="text-sm text-gray-400">Secret Key</label>
                  <div className="relative">
                    <Key className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                    <input
                      type={showSecretKey ? 'text' : 'password'}
                      value={secretKey}
                      onChange={(e) => {
                        setSecretKey(e.target.value);
                        if (inputErrors.upbitSecretKey) {
                          setInputErrors((prev) => ({ ...prev, upbitSecretKey: '' }));
                        }
                      }}
                      onKeyDown={handleUpbitKeyDown}
                      placeholder="Enter your Upbit Secret Key"
                      className={`w-full pl-10 pr-10 py-2.5 bg-surface border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 ${
                        inputErrors.upbitSecretKey ? 'border-red-500' : 'border-border'
                      }`}
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
                  {inputErrors.upbitSecretKey && (
                    <p className="text-xs text-red-400 flex items-center gap-1">
                      <AlertCircle className="w-3 h-3" />
                      {inputErrors.upbitSecretKey}
                    </p>
                  )}
                </div>

                {/* Action Buttons */}
                <div className="flex gap-2">
                  <button
                    onClick={handleSaveAndValidateUpbit}
                    disabled={loading || validating || !accessKey.trim() || !secretKey.trim()}
                    className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
                  >
                    {loading || validating ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Zap className="w-4 h-4" />
                    )}
                    {validating ? 'Validating...' : 'Save & Validate'}
                  </button>
                  <button
                    onClick={handleSaveUpbitKeys}
                    disabled={loading || !accessKey.trim() || !secretKey.trim()}
                    className="px-4 py-2.5 text-gray-400 hover:text-white hover:bg-surface rounded-lg transition-colors text-sm"
                    title="Save without validation"
                  >
                    Save Only
                  </button>
                </div>
                <p className="text-xs text-gray-500 text-center">
                  Press Enter to Save & Validate
                </p>
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
          ) : activeTab === 'kiwoom' ? (
            /* Kiwoom Settings Tab */
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
                      {kiwoomStatus?.is_configured ? (
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
                  {kiwoomStatus?.account_masked && (
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-gray-400">Account</span>
                      <span className="text-sm font-mono text-gray-300">
                        {kiwoomStatus.account_masked}
                      </span>
                    </div>
                  )}
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-400">Validated</span>
                    <span className="flex items-center gap-1.5">
                      {kiwoomStatus?.is_valid === true ? (
                        <>
                          <CheckCircle2 className="w-4 h-4 text-green-400" />
                          <span className="text-sm text-green-400">Valid</span>
                        </>
                      ) : kiwoomStatus?.is_valid === false ? (
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
                      kiwoomStatus?.trading_mode === 'live'
                        ? 'text-orange-400'
                        : 'text-blue-400'
                    }`}>
                      {kiwoomStatus?.trading_mode?.toUpperCase() || 'PAPER'}
                    </span>
                  </div>
                </div>

                {/* Action Buttons */}
                {kiwoomStatus?.is_configured && (
                  <div className="flex gap-2 mt-4 pt-4 border-t border-border">
                    <button
                      onClick={handleValidateKiwoomKeys}
                      disabled={kiwoomValidating}
                      className="flex items-center gap-2 px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:opacity-50 transition-colors"
                    >
                      {kiwoomValidating ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <CheckCircle2 className="w-3.5 h-3.5" />
                      )}
                      Validate
                    </button>
                    <button
                      onClick={handleClearKiwoomKeys}
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
                  {kiwoomStatus?.is_configured ? 'Update API Keys' : 'Enter API Keys'}
                </h3>
                <p className="text-xs text-gray-500">
                  Get your API keys from{' '}
                  <a
                    href="https://apiportal.koreainvestment.com/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:underline"
                  >
                    Korea Investment API Portal
                  </a>
                </p>

                {/* App Key */}
                <div className="space-y-1.5">
                  <label className="text-sm text-gray-400">App Key</label>
                  <div className="relative">
                    <Key className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                    <input
                      ref={kiwoomAppKeyRef}
                      type={showKiwoomAppKey ? 'text' : 'password'}
                      value={kiwoomAppKey}
                      onChange={(e) => {
                        setKiwoomAppKey(e.target.value);
                        if (inputErrors.kiwoomAppKey) {
                          setInputErrors((prev) => ({ ...prev, kiwoomAppKey: '' }));
                        }
                      }}
                      onKeyDown={handleKiwoomKeyDown}
                      placeholder="Enter your App Key"
                      className={`w-full pl-10 pr-10 py-2.5 bg-surface border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 ${
                        inputErrors.kiwoomAppKey ? 'border-red-500' : 'border-border'
                      }`}
                    />
                    <button
                      type="button"
                      onClick={() => setShowKiwoomAppKey(!showKiwoomAppKey)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                    >
                      {showKiwoomAppKey ? (
                        <EyeOff className="w-4 h-4" />
                      ) : (
                        <Eye className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                  {inputErrors.kiwoomAppKey && (
                    <p className="text-xs text-red-400 flex items-center gap-1">
                      <AlertCircle className="w-3 h-3" />
                      {inputErrors.kiwoomAppKey}
                    </p>
                  )}
                </div>

                {/* App Secret */}
                <div className="space-y-1.5">
                  <label className="text-sm text-gray-400">App Secret</label>
                  <div className="relative">
                    <Key className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                    <input
                      type={showKiwoomAppSecret ? 'text' : 'password'}
                      value={kiwoomAppSecret}
                      onChange={(e) => {
                        setKiwoomAppSecret(e.target.value);
                        if (inputErrors.kiwoomAppSecret) {
                          setInputErrors((prev) => ({ ...prev, kiwoomAppSecret: '' }));
                        }
                      }}
                      onKeyDown={handleKiwoomKeyDown}
                      placeholder="Enter your App Secret"
                      className={`w-full pl-10 pr-10 py-2.5 bg-surface border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 ${
                        inputErrors.kiwoomAppSecret ? 'border-red-500' : 'border-border'
                      }`}
                    />
                    <button
                      type="button"
                      onClick={() => setShowKiwoomAppSecret(!showKiwoomAppSecret)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                    >
                      {showKiwoomAppSecret ? (
                        <EyeOff className="w-4 h-4" />
                      ) : (
                        <Eye className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                  {inputErrors.kiwoomAppSecret && (
                    <p className="text-xs text-red-400 flex items-center gap-1">
                      <AlertCircle className="w-3 h-3" />
                      {inputErrors.kiwoomAppSecret}
                    </p>
                  )}
                </div>

                {/* Account Number */}
                <div className="space-y-1.5">
                  <label className="text-sm text-gray-400">Account Number (계좌번호)</label>
                  <input
                    type="text"
                    value={kiwoomAccount}
                    onChange={(e) => {
                      setKiwoomAccount(e.target.value);
                      if (inputErrors.kiwoomAccount) {
                        setInputErrors((prev) => ({ ...prev, kiwoomAccount: '' }));
                      }
                    }}
                    onKeyDown={handleKiwoomKeyDown}
                    placeholder="12345678-01"
                    className={`w-full px-3 py-2.5 bg-surface border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 ${
                      inputErrors.kiwoomAccount ? 'border-red-500' : 'border-border'
                    }`}
                  />
                  {inputErrors.kiwoomAccount && (
                    <p className="text-xs text-red-400 flex items-center gap-1">
                      <AlertCircle className="w-3 h-3" />
                      {inputErrors.kiwoomAccount}
                    </p>
                  )}
                </div>

                {/* Mock Trading Toggle */}
                <div className="flex items-center justify-between p-3 bg-surface rounded-lg">
                  <div>
                    <span className="text-sm text-gray-300">모의투자 (Paper Trading)</span>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Enable for testing without real money
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setKiwoomIsMock(!kiwoomIsMock)}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      kiwoomIsMock ? 'bg-blue-600' : 'bg-gray-600'
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        kiwoomIsMock ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>

                {/* Action Buttons */}
                <div className="flex gap-2">
                  <button
                    onClick={handleSaveAndValidateKiwoom}
                    disabled={loading || kiwoomValidating || !kiwoomAppKey.trim() || !kiwoomAppSecret.trim() || !kiwoomAccount.trim()}
                    className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
                  >
                    {loading || kiwoomValidating ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Zap className="w-4 h-4" />
                    )}
                    {kiwoomValidating ? 'Validating...' : 'Save & Validate'}
                  </button>
                  <button
                    onClick={handleSaveKiwoomKeys}
                    disabled={loading || !kiwoomAppKey.trim() || !kiwoomAppSecret.trim() || !kiwoomAccount.trim()}
                    className="px-4 py-2.5 text-gray-400 hover:text-white hover:bg-surface rounded-lg transition-colors text-sm"
                    title="Save without validation"
                  >
                    Save Only
                  </button>
                </div>
                <p className="text-xs text-gray-500 text-center">
                  Press Enter to Save & Validate
                </p>
              </div>

              {/* Note */}
              <div className="text-xs text-gray-500 bg-surface/50 rounded-lg p-3">
                <p className="font-medium text-gray-400 mb-1">Note:</p>
                <ul className="list-disc list-inside space-y-0.5">
                  <li>API keys are stored in runtime memory only</li>
                  <li>Keys will be cleared when the server restarts</li>
                  <li>모의투자(Paper Trading)는 실제 거래 없이 테스트할 수 있습니다</li>
                  <li>For live trading, ensure you have sufficient balance</li>
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
