/**
 * Unit Tests for Settings Validators
 */

import { describe, it, expect } from 'vitest';
import {
  validateUpbitApiInputs,
  validateKiwoomApiInputs,
  isValidApiKeyFormat,
  maskApiKey,
} from './validators';

describe('validateUpbitApiInputs', () => {
  it('should return valid when both keys are provided', () => {
    const result = validateUpbitApiInputs(
      'abcdefghij1234567890',
      'secretkey1234567890'
    );
    expect(result.isValid).toBe(true);
    expect(Object.keys(result.errors)).toHaveLength(0);
  });

  it('should fail when access key is empty', () => {
    const result = validateUpbitApiInputs('', 'secretkey1234567890');
    expect(result.isValid).toBe(false);
    expect(result.errors.upbitAccessKey).toBe('Access Key is required');
  });

  it('should fail when secret key is empty', () => {
    const result = validateUpbitApiInputs('abcdefghij1234567890', '');
    expect(result.isValid).toBe(false);
    expect(result.errors.upbitSecretKey).toBe('Secret Key is required');
  });

  it('should fail when access key is too short', () => {
    const result = validateUpbitApiInputs('short', 'secretkey1234567890');
    expect(result.isValid).toBe(false);
    expect(result.errors.upbitAccessKey).toBe('Access Key seems too short');
  });

  it('should fail when secret key is too short', () => {
    const result = validateUpbitApiInputs('abcdefghij1234567890', 'short');
    expect(result.isValid).toBe(false);
    expect(result.errors.upbitSecretKey).toBe('Secret Key seems too short');
  });

  it('should fail for both empty keys', () => {
    const result = validateUpbitApiInputs('', '');
    expect(result.isValid).toBe(false);
    expect(result.errors.upbitAccessKey).toBeDefined();
    expect(result.errors.upbitSecretKey).toBeDefined();
  });

  it('should trim whitespace', () => {
    const result = validateUpbitApiInputs('   ', '   ');
    expect(result.isValid).toBe(false);
    expect(result.errors.upbitAccessKey).toBe('Access Key is required');
    expect(result.errors.upbitSecretKey).toBe('Secret Key is required');
  });
});

describe('validateKiwoomApiInputs', () => {
  it('should return valid when all fields are correct', () => {
    const result = validateKiwoomApiInputs(
      'appkey123',
      'appsecret456',
      '12345678-01'
    );
    expect(result.isValid).toBe(true);
    expect(Object.keys(result.errors)).toHaveLength(0);
  });

  it('should fail when app key is empty', () => {
    const result = validateKiwoomApiInputs('', 'appsecret456', '12345678-01');
    expect(result.isValid).toBe(false);
    expect(result.errors.kiwoomAppKey).toBe('App Key is required');
  });

  it('should fail when app secret is empty', () => {
    const result = validateKiwoomApiInputs('appkey123', '', '12345678-01');
    expect(result.isValid).toBe(false);
    expect(result.errors.kiwoomAppSecret).toBe('App Secret is required');
  });

  it('should fail when account is empty', () => {
    const result = validateKiwoomApiInputs('appkey123', 'appsecret456', '');
    expect(result.isValid).toBe(false);
    expect(result.errors.kiwoomAccount).toBe('Account number is required');
  });

  it('should fail when account format is invalid', () => {
    const result = validateKiwoomApiInputs('appkey123', 'appsecret456', '12345678');
    expect(result.isValid).toBe(false);
    expect(result.errors.kiwoomAccount).toBe('Format: 12345678-01');
  });

  it('should fail for wrong account format variations', () => {
    const invalidFormats = [
      '1234567-01',     // 7 digits
      '123456789-01',   // 9 digits
      '12345678-1',     // 1 digit suffix
      '12345678-001',   // 3 digit suffix
      '12345678_01',    // wrong separator
      'ABCDEFGH-01',    // letters
    ];

    for (const format of invalidFormats) {
      const result = validateKiwoomApiInputs('appkey', 'appsecret', format);
      expect(result.errors.kiwoomAccount).toBe('Format: 12345678-01');
    }
  });

  it('should accept valid account formats', () => {
    const validFormats = [
      '12345678-01',
      '00000000-00',
      '99999999-99',
    ];

    for (const format of validFormats) {
      const result = validateKiwoomApiInputs('appkey', 'appsecret', format);
      expect(result.errors.kiwoomAccount).toBeUndefined();
    }
  });
});

describe('isValidApiKeyFormat', () => {
  it('should return true for valid key', () => {
    expect(isValidApiKeyFormat('abcdefghij1234567890')).toBe(true);
  });

  it('should return false for short key', () => {
    expect(isValidApiKeyFormat('short')).toBe(false);
  });

  it('should return false for empty key', () => {
    expect(isValidApiKeyFormat('')).toBe(false);
  });

  it('should return false for key with spaces', () => {
    expect(isValidApiKeyFormat('key with spaces')).toBe(false);
  });

  it('should return true for key with special chars', () => {
    expect(isValidApiKeyFormat('key-with_special+chars=')).toBe(true);
  });
});

describe('maskApiKey', () => {
  it('should mask middle of key', () => {
    const result = maskApiKey('abcdefghij1234567890');
    expect(result).toBe('abcd********7890');
  });

  it('should handle short keys', () => {
    const result = maskApiKey('short');
    expect(result).toBe('****');
  });

  it('should handle empty key', () => {
    const result = maskApiKey('');
    expect(result).toBe('****');
  });

  it('should respect visibleChars parameter', () => {
    const result = maskApiKey('abcdefghij1234567890', 2);
    expect(result).toBe('ab********90');
  });

  it('should handle edge case where key equals visible chars * 2', () => {
    const result = maskApiKey('12345678', 4);
    expect(result).toBe('****');
  });
});
