import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { VoteBlotter } from './ChatSessionViewer';
import type { AgentChatVote } from '@/types';

const vote = (over: Partial<AgentChatVote>): AgentChatVote => ({
  agent_type: 'technical',
  vote: 'BUY',
  confidence: 0.72,
  weight: 0.3,
  weighted_score: 0.85,
  reasoning: 'RSI oversold',
  ...over,
});

describe('VoteBlotter', () => {
  it('renders WGT and SCORE columns and a directional up color for BUY', () => {
    const { getByText, container } = render(<VoteBlotter votes={[vote({})]} />);
    expect(getByText('BUY').className).toContain('text-up');
    expect(container.textContent).toContain('0.30'); // weight 2dp
    expect(container.textContent).toContain('0.85'); // weighted_score 2dp
    expect(container.textContent).toContain('72%');  // confidence
  });

  it('renders a directional down color for SELL and compact labels', () => {
    const { getByText } = render(
      <VoteBlotter votes={[vote({ vote: 'STRONG_SELL', weighted_score: -0.6 })]} />,
    );
    expect(getByText('S.SELL').className).toContain('text-down');
  });

  it('does NOT render the per-vote reasoning prose', () => {
    const { container } = render(<VoteBlotter votes={[vote({ reasoning: 'SECRET_PROSE' })]} />);
    expect(container.textContent).not.toContain('SECRET_PROSE');
  });
});
