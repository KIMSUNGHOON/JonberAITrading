import { describe, it, expect, vi } from 'vitest';
import { buildCommands, filterCommands } from './commands';

const ctx = {
  goTo: vi.fn(), setActiveMarket: vi.fn(), setChartSymbol: vi.fn(),
  setShowSettingsModal: vi.fn(), startAnalysis: vi.fn(), startScan: vi.fn(), startDebate: vi.fn(),
};

describe('commands', () => {
  it('fuzzy-filters nav commands by title', () => {
    const cmds = buildCommands(ctx as any);
    const hits = filterCommands(cmds, 'posi');
    expect(hits.some((h) => h.command.id === 'go:positions')).toBe(true);
  });
  it('parses :analyze <ticker> into an arg', () => {
    const cmds = buildCommands(ctx as any);
    const hits = filterCommands(cmds, ':analyze 005930');
    expect(hits[0].command.id).toBe('analyze');
    expect(hits[0].arg).toBe('005930');
  });
  it('runs :chart with the arg', () => {
    const cmds = buildCommands(ctx as any);
    const { command, arg } = filterCommands(cmds, ':chart KRW-BTC')[0];
    command.run(ctx as any, arg);
    expect(ctx.setChartSymbol).toHaveBeenCalledWith('KRW-BTC');
  });
  it('progressively surfaces :analyze for a partial colon query', () => {
    const cmds = buildCommands(ctx as any);
    const hits = filterCommands(cmds, ':anal');
    const hit = hits.find((h) => h.command.id === 'analyze');
    expect(hit).toBeDefined();
    expect(hit?.arg).toBeUndefined();
  });
});
