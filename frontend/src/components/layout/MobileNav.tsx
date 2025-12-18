/**
 * Mobile Navigation Component
 *
 * Bottom navigation bar for mobile devices.
 */

import { useState } from 'react';
import {
  BarChart3,
  MessageSquare,
  TrendingUp,
  Wallet,
  X,
} from 'lucide-react';
import { useStore } from '@/store';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { Sidebar } from './Sidebar';

type MobileView = 'none' | 'chat' | 'menu';

export function MobileNav() {
  const [activeView, setActiveView] = useState<MobileView>('none');
  const isMobileMenuOpen = useStore((state) => state.isMobileMenuOpen);
  const setMobileMenuOpen = useStore((state) => state.setMobileMenuOpen);
  const status = useStore((state) => state.status);
  const awaitingApproval = useStore((state) => state.awaitingApproval);

  const toggleView = (view: MobileView) => {
    setActiveView((current) => (current === view ? 'none' : view));
  };

  return (
    <>
      {/* Mobile Menu Overlay */}
      {isMobileMenuOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setMobileMenuOpen(false)}
          />
          <div className="absolute left-0 top-0 bottom-0 w-72 bg-surface-light border-r border-border">
            <div className="flex items-center justify-between p-4 border-b border-border">
              <span className="font-semibold">Menu</span>
              <button
                onClick={() => setMobileMenuOpen(false)}
                className="p-2 hover:bg-surface rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <Sidebar />
          </div>
        </div>
      )}

      {/* Chat Bottom Sheet */}
      {activeView === 'chat' && (
        <div className="fixed inset-x-0 bottom-16 top-20 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setActiveView('none')}
          />
          <div className="absolute inset-x-0 bottom-0 top-0 bg-surface-light rounded-t-2xl overflow-hidden">
            <ChatPanel />
          </div>
        </div>
      )}

      {/* Bottom Navigation Bar */}
      <nav className="md:hidden fixed bottom-0 inset-x-0 h-16 bg-surface-light border-t border-border safe-bottom">
        <div className="h-full flex items-center justify-around">
          <NavButton
            icon={<TrendingUp className="w-5 h-5" />}
            label="Analysis"
            active={status === 'running'}
            onClick={() => setActiveView('none')}
          />
          <NavButton
            icon={<BarChart3 className="w-5 h-5" />}
            label="Charts"
            onClick={() => setActiveView('none')}
          />
          <NavButton
            icon={<MessageSquare className="w-5 h-5" />}
            label="Chat"
            active={activeView === 'chat'}
            badge={awaitingApproval}
            onClick={() => toggleView('chat')}
          />
          <NavButton
            icon={<Wallet className="w-5 h-5" />}
            label="Position"
            onClick={() => setActiveView('none')}
          />
        </div>
      </nav>
    </>
  );
}

interface NavButtonProps {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  badge?: boolean;
  onClick?: () => void;
}

function NavButton({ icon, label, active, badge, onClick }: NavButtonProps) {
  return (
    <button
      onClick={onClick}
      className={`flex flex-col items-center gap-1 p-2 relative ${
        active ? 'text-blue-400' : 'text-gray-400'
      }`}
    >
      {icon}
      <span className="text-xs">{label}</span>
      {badge && (
        <span className="absolute top-1 right-1 w-2 h-2 bg-yellow-500 rounded-full" />
      )}
    </button>
  );
}
