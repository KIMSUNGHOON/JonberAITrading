import { describe, it, expect } from 'vitest';
import {
  getRiskLevel, actionTextColor, isTicketActive, buildApprovalRequest,
  getProposalSymbol, formatCurrency,
} from './orderTicket';

describe('getRiskLevel', () => {
  it('low risk (<=3) → up tokens', () => {
    expect(getRiskLevel(2)).toEqual({ label: 'Low Risk', textColor: 'text-up', barColor: 'bg-up' });
  });
  it('medium risk (4-6) → warn tokens', () => {
    expect(getRiskLevel(5)).toEqual({ label: 'Medium Risk', textColor: 'text-warn', barColor: 'bg-warn' });
  });
  it('high risk (>6) → down tokens', () => {
    expect(getRiskLevel(9)).toEqual({ label: 'High Risk', textColor: 'text-down', barColor: 'bg-down' });
  });
});

describe('actionTextColor', () => {
  it('BUY/ADD → up (green)', () => {
    expect(actionTextColor('BUY')).toBe('text-up');
    expect(actionTextColor('ADD')).toBe('text-up');
  });
  it('SELL/REDUCE → down (red)', () => {
    expect(actionTextColor('SELL')).toBe('text-down');
    expect(actionTextColor('REDUCE')).toBe('text-down');
  });
  it('HOLD/other → muted', () => {
    expect(actionTextColor('HOLD')).toBe('text-muted');
  });
});

describe('isTicketActive', () => {
  it('false when no proposal', () => {
    expect(isTicketActive(null, 'sess-1')).toBe(false);
  });
  it('false when no session', () => {
    expect(isTicketActive({ ticker: 'AAPL' } as any, null)).toBe(false);
  });
  it('false when symbol resolves to UNKNOWN', () => {
    expect(isTicketActive({} as any, 'sess-1')).toBe(false);
  });
  it('true when proposal + session + resolvable symbol', () => {
    expect(isTicketActive({ ticker: 'AAPL' } as any, 'sess-1')).toBe(true);
  });
});

describe('buildApprovalRequest', () => {
  it('includes trimmed feedback', () => {
    expect(buildApprovalRequest('s1', 'approved', '  looks good  ')).toEqual({
      session_id: 's1', decision: 'approved', feedback: 'looks good',
    });
  });
  it('omits empty feedback', () => {
    expect(buildApprovalRequest('s1', 'rejected', '   ')).toEqual({
      session_id: 's1', decision: 'rejected', feedback: undefined,
    });
  });
});

describe('helpers ported from ApprovalDialog', () => {
  it('getProposalSymbol resolves ticker', () => {
    expect(getProposalSymbol({ ticker: 'TSLA' } as any)).toBe('TSLA');
  });
  it('formatCurrency: US dollars vs KR won', () => {
    expect(formatCurrency(1234.5, 'stock')).toBe('$1234.50');
    expect(formatCurrency(1000, 'coin')).toBe('₩1,000');
    expect(formatCurrency(null, 'stock')).toBe('N/A');
  });
});
