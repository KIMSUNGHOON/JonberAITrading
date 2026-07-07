import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ReasoningWire } from './ReasoningWire';

describe('ReasoningWire', () => {
  it('renders each entry body with a numbered gutter', () => {
    const { getByText, container } = render(
      <ReasoningWire entries={['[Technical] RSI oversold', 'plain line']} running={false} />,
    );
    expect(getByText('RSI oversold')).toBeTruthy();
    expect(getByText('plain line')).toBeTruthy();
    expect(container.textContent).toContain('01');
    expect(container.textContent).toContain('02');
  });

  it('colorizes the [Agent] prefix with a directional/identity token class', () => {
    const { getByText } = render(<ReasoningWire entries={['[Risk] high volatility']} running={false} />);
    expect(getByText('[Risk]').className).toContain('text-down');
  });

  it('shows a pulsing running head with the current stage', () => {
    const { getByText } = render(<ReasoningWire entries={[]} running currentStage="Voting" />);
    expect(getByText(/Voting/)).toBeTruthy();
  });
});
