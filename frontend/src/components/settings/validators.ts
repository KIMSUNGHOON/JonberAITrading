/**
 * Validation functions for Settings forms
 */

export interface ValidationResult {
  isValid: boolean;
  errors: Record<string, string>;
}

/**
 * Validate Upbit API key inputs
 */
export function validateUpbitApiInputs(
  accessKey: string,
  secretKey: string
): ValidationResult {
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

  return {
    isValid: Object.keys(errors).length === 0,
    errors,
  };
}

/**
 * Validate Kiwoom API key inputs
 */
export function validateKiwoomApiInputs(
  appKey: string,
  appSecret: string,
  account: string
): ValidationResult {
  const errors: Record<string, string> = {};

  if (!appKey.trim()) {
    errors.kiwoomAppKey = 'App Key is required';
  }

  if (!appSecret.trim()) {
    errors.kiwoomAppSecret = 'App Secret is required';
  }

  if (!account.trim()) {
    errors.kiwoomAccount = 'Account number is required';
  } else if (!/^\d{8}-\d{2}$/.test(account.trim())) {
    errors.kiwoomAccount = 'Format: 12345678-01';
  }

  return {
    isValid: Object.keys(errors).length === 0,
    errors,
  };
}

/**
 * Check if an API key looks valid (basic format check)
 */
export function isValidApiKeyFormat(key: string): boolean {
  // Basic check: not empty, reasonable length, no spaces
  const trimmed = key.trim();
  return trimmed.length >= 10 && !/\s/.test(trimmed);
}

/**
 * Mask a sensitive key for display
 */
export function maskApiKey(key: string, visibleChars = 4): string {
  if (!key || key.length <= visibleChars * 2) {
    return '****';
  }
  const start = key.slice(0, visibleChars);
  const end = key.slice(-visibleChars);
  const middle = '*'.repeat(Math.min(key.length - visibleChars * 2, 8));
  return `${start}${middle}${end}`;
}
