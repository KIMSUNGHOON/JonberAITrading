// frontend/src/nav.test.ts
import { describe, it, expect } from 'vitest';
import { viewToPath, pathToView } from './nav';

describe('nav map', () => {
  it('maps views to paths', () => {
    expect(viewToPath('dashboard')).toBe('/');
    expect(viewToPath('positions')).toBe('/positions');
    expect(viewToPath('basket')).toBe('/watchlist');
    expect(viewToPath('workflow', 'abc')).toBe('/workflow/abc');
    expect(viewToPath('analysis-detail', 'xyz')).toBe('/analysis/xyz');
    expect(viewToPath('workflow')).toBe('/analysis'); // no id -> list
  });
  it('derives the top-level view from a pathname', () => {
    expect(pathToView('/')).toBe('dashboard');
    expect(pathToView('/positions')).toBe('positions');
    expect(pathToView('/watchlist')).toBe('basket');
    expect(pathToView('/analysis/abc')).toBe('analysis');
    expect(pathToView('/workflow/abc')).toBe('analysis');
    expect(pathToView('/unknown')).toBe('dashboard');
  });
});
