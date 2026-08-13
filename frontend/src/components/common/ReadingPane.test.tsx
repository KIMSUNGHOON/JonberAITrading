import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ReadingPane } from './ReadingPane';

describe('ReadingPane', () => {
  it('renders children inside the editorial container', () => {
    render(<ReadingPane><p>안녕하세요 reading body</p></ReadingPane>);
    expect(screen.getByText('안녕하세요 reading body')).toBeInTheDocument();
  });

  it('applies the editorial typography classes (font-sans, a max-w measure, relaxed leading)', () => {
    const { container } = render(<ReadingPane>x</ReadingPane>);
    const el = container.firstElementChild as HTMLElement;
    expect(el.className).toContain('font-sans');
    expect(el.className).toContain('leading-relaxed');
    expect(el.className).toMatch(/max-w-\[65ch\]/);
  });

  it('passes through className', () => {
    const { container } = render(<ReadingPane className="mt-2">x</ReadingPane>);
    expect((container.firstElementChild as HTMLElement).className).toContain('mt-2');
  });
});
