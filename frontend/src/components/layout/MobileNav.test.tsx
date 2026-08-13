import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MobileNav } from './MobileNav';

// Cleanup C (2026-07-14 dashboard-widget-cull audit, §C-6): the bottom bar
// used to render Analysis/Charts/Position buttons whose onClick was
// () => setActiveView('none') — a no-op with no corresponding view, and
// 'Charts' was a phantom label (Charts view removed in R5-P2). Only the
// Chat button ever did anything real (it toggles the chat bottom sheet).
describe('MobileNav', () => {
  it('renders without the dead Analysis/Charts/Position buttons', () => {
    render(<MobileNav />);
    expect(screen.queryByText('Analysis')).not.toBeInTheDocument();
    expect(screen.queryByText('Charts')).not.toBeInTheDocument();
    expect(screen.queryByText('Position')).not.toBeInTheDocument();
  });

  it('keeps the working Chat button, which toggles the chat bottom sheet', () => {
    render(<MobileNav />);
    const chatButton = screen.getByRole('button', { name: /chat/i });
    expect(chatButton).toBeInTheDocument();

    fireEvent.click(chatButton);
    expect(screen.getByRole('textbox')).toBeInTheDocument();

    fireEvent.click(chatButton);
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });
});
