import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { MarkdownRenderer } from './MarkdownRenderer';

function html(content: string, compact = false): string {
  const { container } = render(<MarkdownRenderer content={content} compact={compact} />);
  return (container.firstElementChild as HTMLElement).innerHTML;
}

describe('MarkdownRenderer re-skin', () => {
  it('bold uses text-ink, not text-white', () => {
    const out = html('**strong**');
    expect(out).toContain('text-ink');
    expect(out).not.toContain('text-white');
  });

  it('directional highlights: BUY→up, SELL→down (not raw green/red)', () => {
    const out = html('signal BUY then SELL');
    expect(out).toContain('text-up');
    expect(out).toContain('text-down');
    expect(out).not.toContain('text-green-400');
    expect(out).not.toContain('text-red-400');
  });

  it('no raw green/red/blue/surface debt tokens survive anywhere', () => {
    const out = html('# H\n**b** `code` - item\nBUY SELL HOLD 45% $100 bullish bearish neutral');
    expect(out).not.toMatch(/text-(green|red)-400|bg-(green|red)-500|bg-surface|text-white|text-gray-|border-gray-|text-blue-400|text-purple-400|text-yellow-400/);
  });

  it('still renders markdown structure (headers, code, lists)', () => {
    const out = html('## Head\n`inline`\n- one');
    expect(out).toContain('<h3');       // ## → h3
    expect(out).toContain('<code');     // inline code
    expect(out).toContain('<li');       // list item
  });
});
