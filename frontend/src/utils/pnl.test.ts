import { describe, it, expect } from 'vitest';
import { pnlColor, changeColor } from './pnl';

describe('pnlColor', () => {
  it('western (default): gain green, loss red', () => {
    expect(pnlColor(100)).toBe('text-up');
    expect(pnlColor(-100)).toBe('text-down');
  });
  it('korean: gain red, loss green', () => {
    expect(pnlColor(100, 'korean')).toBe('text-down');
    expect(pnlColor(-100, 'korean')).toBe('text-up');
  });
  it('zero is neutral', () => {
    expect(pnlColor(0)).toBe('text-muted');
    expect(pnlColor(0, 'korean')).toBe('text-muted');
  });
});

describe('changeColor', () => {
  it('western RISE=up, FALL=down', () => {
    expect(changeColor('RISE')).toBe('text-up');
    expect(changeColor('FALL')).toBe('text-down');
  });
  it('korean RISE=down, FALL=up', () => {
    expect(changeColor('RISE', 'korean')).toBe('text-down');
    expect(changeColor('FALL', 'korean')).toBe('text-up');
  });
  it('unknown direction is neutral', () => {
    expect(changeColor('FLAT')).toBe('text-muted');
  });
});
