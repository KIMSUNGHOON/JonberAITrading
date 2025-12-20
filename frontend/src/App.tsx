/**
 * Main Application Component
 *
 * Hybrid Layout: Dashboard + Chat Interface
 */

import { useEffect } from 'react';
import { useStore, selectError } from '@/store';
import { Header } from '@/components/layout/Header';
import { Sidebar } from '@/components/layout/Sidebar';
import { MainContent } from '@/components/layout/MainContent';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { ApprovalDialog } from '@/components/approval/ApprovalDialog';
import { MobileNav } from '@/components/layout/MobileNav';
import { SettingsModal } from '@/components/settings/SettingsModal';
import { getUpbitApiStatus } from '@/api/client';

function App() {
  const showApprovalDialog = useStore((state) => state.showApprovalDialog);
  const showSettingsModal = useStore((state) => state.showSettingsModal);
  const setShowSettingsModal = useStore((state) => state.setShowSettingsModal);
  const setUpbitApiConfigured = useStore((state) => state.setUpbitApiConfigured);
  const sidebarCollapsed = useStore((state) => state.sidebarCollapsed);
  const error = useStore(selectError);
  const setError = useStore((state) => state.setError);

  // Get status for conditional ChatPanel display
  const status = useStore((state) =>
    state.activeMarket === 'stock' ? state.stock.status : state.coin.status
  );
  const awaitingApproval = useStore((state) =>
    state.activeMarket === 'stock' ? state.stock.awaitingApproval : state.coin.awaitingApproval
  );

  // Show ChatPanel when: idle, awaiting approval, completed, or cancelled
  const showChatPanel = status === 'idle' || status === 'awaiting_approval' ||
    status === 'completed' || status === 'cancelled' || awaitingApproval;

  // Check Upbit API status on mount
  useEffect(() => {
    async function checkUpbitStatus() {
      try {
        const status = await getUpbitApiStatus();
        setUpbitApiConfigured(status.is_configured);
      } catch (err) {
        console.error('Failed to check Upbit API status:', err);
      }
    }
    checkUpbitStatus();
  }, [setUpbitApiConfigured]);

  // Clear error after 5 seconds
  useEffect(() => {
    if (error) {
      const timer = setTimeout(() => setError(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [error, setError]);

  return (
    <div className="h-screen bg-surface flex flex-col overflow-hidden">
      {/* Header - Fixed height */}
      <Header />

      {/* Error Toast */}
      {error && (
        <div className="fixed top-20 left-1/2 -translate-x-1/2 z-50 bg-bear/90 text-white px-6 py-3 rounded-lg shadow-lg">
          {error}
        </div>
      )}

      {/* Main Layout - Takes remaining height */}
      <div className="flex-1 flex min-h-0">
        {/* Sidebar - Hidden on mobile, collapsible */}
        <aside
          className={`hidden lg:flex lg:flex-col border-r border-border flex-shrink-0 transition-all duration-300 ${
            sidebarCollapsed ? 'w-16' : 'w-56'
          }`}
        >
          <Sidebar collapsed={sidebarCollapsed} />
        </aside>

        {/* Main Content Area */}
        <main className="flex-1 flex flex-col lg:flex-row min-h-0 min-w-0">
          {/* Dashboard Panel - Scrollable */}
          <div className="flex-1 overflow-y-auto min-h-0">
            <MainContent />
          </div>

          {/* Chat Panel - Conditionally shown after workflow completes or for approval */}
          {showChatPanel && (
            <div className="hidden md:flex md:flex-col w-80 border-l border-border flex-shrink-0">
              <ChatPanel />
            </div>
          )}
        </main>
      </div>

      {/* Mobile Navigation */}
      <MobileNav />

      {/* Approval Dialog */}
      {showApprovalDialog && <ApprovalDialog />}

      {/* Settings Modal */}
      <SettingsModal
        isOpen={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
      />
    </div>
  );
}

export default App;
