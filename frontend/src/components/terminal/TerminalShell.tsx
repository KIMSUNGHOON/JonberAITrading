/**
 * TerminalShell — the "Dense Terminal Shell" chrome that replaces the old
 * marketing Header + Sidebar. Command bar (top) + compact nav rail (left) +
 * children (main) + status line (bottom). Wired to the existing store.
 */
import { useEffect, useState } from 'react';
import {
  LayoutDashboard, Activity, BarChart3, Wallet, ShoppingBasket, Receipt,
  Bot, Scan, MessageSquare, Settings, Bell,
} from 'lucide-react';
import { useStore } from '@/store';

type View =
  | 'dashboard' | 'analysis' | 'charts' | 'positions' | 'basket'
  | 'trades' | 'trading' | 'scanner' | 'agent-chat';

const NAV: { view: View; icon: React.ReactNode; label: string }[] = [
  { view: 'dashboard', icon: <LayoutDashboard size={17} />, label: 'Dashboard' },
  { view: 'analysis', icon: <Activity size={17} />, label: 'Analysis' },
  { view: 'charts', icon: <BarChart3 size={17} />, label: 'Chart' },
  { view: 'positions', icon: <Wallet size={17} />, label: 'Positions' },
  { view: 'basket', icon: <ShoppingBasket size={17} />, label: 'Watchlist' },
  { view: 'agent-chat', icon: <MessageSquare size={17} />, label: 'Agent Chat' },
  { view: 'scanner', icon: <Scan size={17} />, label: 'Scanner' },
  { view: 'trading', icon: <Bot size={17} />, label: 'Auto-trade' },
  { view: 'trades', icon: <Receipt size={17} />, label: 'Trades' },
];

const MARKETS: { id: 'kiwoom' | 'stock' | 'coin'; label: string; sim?: boolean }[] = [
  { id: 'kiwoom', label: 'KR · KRX' },
  { id: 'stock', label: 'US', sim: true },
  { id: 'coin', label: 'COIN' },
];

function useClock() {
  const [t, setT] = useState('');
  useEffect(() => {
    const tick = () => setT(new Date().toTimeString().slice(0, 8));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return t;
}

export function TerminalShell({ children }: { children: React.ReactNode }) {
  const currentView = useStore((s) => s.currentView);
  const setCurrentView = useStore((s) => s.setCurrentView);
  const activeMarket = useStore((s) => s.activeMarket);
  const setActiveMarket = useStore((s) => s.setActiveMarket);
  const setShowSettingsModal = useStore((s) => s.setShowSettingsModal);
  const kiwoomIsMock = useStore((s) => s.kiwoomApiConfigured);
  const clock = useClock();

  return (
    <div className="h-screen flex flex-col bg-canvas text-ink font-mono text-[13px] overflow-hidden">
      {/* ── command bar ── */}
      <div className="flex items-center gap-3 h-9 px-3 bg-card border-b border-hairline flex-none">
        <div className="flex items-center gap-2 font-bold tracking-[0.14em] text-accent">
          JONBER
          <span className="text-[11px] font-normal tracking-normal text-muted">// agentic terminal</span>
        </div>
        <div className="flex items-center gap-2 flex-1 max-w-[520px] bg-canvas border border-hairline rounded px-2.5 py-1">
          <span className="text-accent font-bold">❯</span>
          <span className="text-dim">:analyze 005930 · :go positions · /filter</span>
          <span className="ml-auto text-[10px] text-dim border border-hairline rounded px-1.5">⌘K</span>
        </div>
        <div className="flex gap-0.5 ml-auto">
          {MARKETS.map((m) => (
            <button
              key={m.id}
              onClick={() => setActiveMarket(m.id)}
              className={`px-2.5 py-1 rounded text-[11px] tracking-wide ${
                activeMarket === m.id
                  ? 'text-ink bg-elevated shadow-[inset_0_-2px_0_var(--accent)]'
                  : 'text-muted hover:text-ink'
              }`}
            >
              {m.label}
              {m.sim && <span className="ml-1 text-[9px] text-warn border border-hairline rounded px-1">SIM</span>}
            </button>
          ))}
        </div>
        <button className="text-muted hover:text-ink p-1" title="Notifications"><Bell size={15} /></button>
        <button onClick={() => setShowSettingsModal(true)} className="text-muted hover:text-ink p-1" title="Settings"><Settings size={15} /></button>
      </div>

      {/* ── body: nav rail + main ── */}
      <div className="flex-1 flex min-h-0">
        <nav className="w-12 flex flex-col items-center gap-1 py-2 bg-card border-r border-hairline flex-none">
          {NAV.map((n) => {
            const active = currentView === n.view;
            return (
              <button
                key={n.view}
                onClick={() => setCurrentView(n.view)}
                title={n.label}
                aria-current={active ? 'page' : undefined}
                className={`relative w-9 h-9 flex items-center justify-center rounded ${
                  active ? 'text-accent bg-elevated' : 'text-dim hover:text-ink'
                }`}
              >
                {active && <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 bg-accent rounded" />}
                {n.icon}
              </button>
            );
          })}
          <button
            onClick={() => setShowSettingsModal(true)}
            title="Settings"
            className="mt-auto w-9 h-9 flex items-center justify-center rounded text-dim hover:text-ink"
          >
            <Settings size={17} />
          </button>
        </nav>

        <div className="flex-1 min-w-0 overflow-auto bg-canvas">{children}</div>
      </div>

      {/* ── status line ── */}
      <div className="flex items-center gap-4 h-6 px-3 bg-card border-t border-hairline text-[11px] text-muted whitespace-nowrap overflow-x-auto flex-none font-mono tabular-nums">
        <span className="uppercase">{activeMarket === 'kiwoom' ? 'KRX' : activeMarket === 'coin' ? 'UPBIT' : 'US'}</span>
        <span className="text-up">● live</span>
        <span className="text-ink">{clock} KST</span>
        <span className="text-warn">{kiwoomIsMock ? 'MOCK' : 'LIVE'}</span>
        <span className="text-accent">P&amp;L GRN-UP</span>
        <span>WS 1/1</span>
        <span className="ml-auto text-dim">⌘K command · j/k rows · :help</span>
      </div>
    </div>
  );
}
