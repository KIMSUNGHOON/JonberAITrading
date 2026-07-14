import { describe, it, expect, vi } from 'vitest';
import { buildCommands, filterCommands, parseOrderArgs } from './commands';

const ctx = {
  goTo: vi.fn(), setActiveMarket: vi.fn(), setChartSymbol: vi.fn(),
  setShowSettingsModal: vi.fn(), startAnalysis: vi.fn(), startScan: vi.fn(), startDebate: vi.fn(),
  placeOrder: vi.fn(), reportError: vi.fn(),
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

describe('parseOrderArgs', () => {
  it('parses SYM QTY into sym+qty with no price', () => {
    const r = parseOrderArgs('005930 10');
    expect(r).toEqual({ ok: true, sym: '005930', qty: 10, px: undefined });
  });
  it('parses SYM QTY PX into sym+qty+px', () => {
    const r = parseOrderArgs('krw-btc 0.5 50000000');
    expect(r).toEqual({ ok: true, sym: 'KRW-BTC', qty: 0.5, px: 50000000 });
  });
  it('rejects missing args entirely', () => {
    const r = parseOrderArgs(undefined);
    expect(r.ok).toBe(false);
  });
  it('rejects a missing quantity', () => {
    const r = parseOrderArgs('005930');
    expect(r).toEqual({ ok: false, error: expect.stringContaining('수량') });
  });
  it('rejects a non-numeric quantity', () => {
    const r = parseOrderArgs('005930 abc');
    expect(r).toEqual({ ok: false, error: expect.stringContaining('수량이 올바르지 않습니다') });
  });
  it('rejects a zero/negative quantity', () => {
    expect(parseOrderArgs('005930 0').ok).toBe(false);
    expect(parseOrderArgs('005930 -5').ok).toBe(false);
  });
  it('rejects a non-numeric price', () => {
    const r = parseOrderArgs('005930 10 abc');
    expect(r).toEqual({ ok: false, error: expect.stringContaining('가격이 올바르지 않습니다') });
  });
});

describe(':buy/:sell commands', () => {
  it(':buy parses SYM+qty and calls placeOrder with correct args', () => {
    const cmds = buildCommands(ctx as any);
    const { command, arg } = filterCommands(cmds, ':buy 005930 10')[0];
    command.run(ctx as any, arg);
    expect(ctx.placeOrder).toHaveBeenCalledWith('buy', '005930', 10, undefined);
  });
  it(':sell parses SYM+qty+px and calls placeOrder with correct args', () => {
    const cmds = buildCommands(ctx as any);
    const { command, arg } = filterCommands(cmds, ':sell KRW-BTC 0.5 50000000')[0];
    command.run(ctx as any, arg);
    expect(ctx.placeOrder).toHaveBeenCalledWith('sell', 'KRW-BTC', 0.5, 50000000);
  });
  it(':buy with a missing quantity reports a visible error and does NOT place an order', () => {
    const cmds = buildCommands(ctx as any);
    ctx.placeOrder.mockClear();
    const { command, arg } = filterCommands(cmds, ':buy 005930')[0];
    command.run(ctx as any, arg);
    expect(ctx.placeOrder).not.toHaveBeenCalled();
    expect(ctx.reportError).toHaveBeenCalledWith(expect.stringContaining('수량'));
  });
  it(':sell with a non-numeric quantity reports a visible error and does NOT place an order', () => {
    const cmds = buildCommands(ctx as any);
    ctx.placeOrder.mockClear();
    const { command, arg } = filterCommands(cmds, ':sell 005930 abc')[0];
    command.run(ctx as any, arg);
    expect(ctx.placeOrder).not.toHaveBeenCalled();
    expect(ctx.reportError).toHaveBeenCalledWith(expect.stringContaining('수량이 올바르지 않습니다'));
  });
});
