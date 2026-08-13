/**
 * B3 (page-ux audit §B-4, optional polish left cosmetic by B2) — the
 * session list didn't visually reflect which session was currently open in
 * the detail pane. This pins the highlight on the selected row.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import { ChatSessionList } from './ChatSessionList';
import type { AgentChatSessionSummary } from '@/types';

const SESSIONS: AgentChatSessionSummary[] = [
  {
    id: 's1',
    ticker: '005930',
    stock_name: '삼성전자',
    status: 'decided',
    started_at: null,
    ended_at: null,
    total_messages: 3,
    total_rounds: 1,
    consensus_level: 0.8,
    decision_action: 'BUY',
    decision_confidence: 0.7,
  },
  {
    id: 's2',
    ticker: '000660',
    stock_name: 'SK하이닉스',
    status: 'voting',
    started_at: null,
    ended_at: null,
    total_messages: 1,
    total_rounds: 1,
    consensus_level: 0.5,
    decision_action: null,
    decision_confidence: null,
  },
];

describe('선택된 세션 하이라이트 (B3)', () => {
  it('selectedSessionId와 일치하는 행에 시각적 강조 클래스를 준다', () => {
    render(
      <ChatSessionList sessions={SESSIONS} onSelectSession={() => {}} selectedSessionId="s2" />,
    );

    const selectedRow = screen.getByText('SK하이닉스').closest('div.cursor-pointer');
    const unselectedRow = screen.getByText('삼성전자').closest('div.cursor-pointer');

    expect(selectedRow?.className).toMatch(/ring-accent/);
    expect(unselectedRow?.className).not.toMatch(/ring-accent/);
  });

  it('selectedSessionId가 없으면 어떤 행도 강조되지 않는다', () => {
    render(<ChatSessionList sessions={SESSIONS} onSelectSession={() => {}} />);

    const rows = screen.getAllByText(/005930|000660/).map((el) => el.closest('div.cursor-pointer'));
    for (const row of rows) {
      expect(row?.className).not.toMatch(/ring-accent/);
    }
  });
});
