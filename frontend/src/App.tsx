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
import { ApprovalDialog } from '@/components/approval/ApprovalDialog';
import { MobileNav } from '@/components/layout/MobileNav';
import { SettingsModal } from '@/components/settings/SettingsModal';
import { ChatToggleButton } from '@/components/chat/ChatToggleButton';
import { ChatPopup } from '@/components/chat/ChatPopup';
import { Toast } from '@/components/ui/Toast';
import { getUpbitApiStatus, getKiwoomApiStatus } from '@/api/client';

function App() {
  const showApprovalDialog = useStore((state) => state.showApprovalDialog);
  const showSettingsModal = useStore((state) => state.showSettingsModal);
  const setShowSettingsModal = useStore((state) => state.setShowSettingsModal);
  const setUpbitApiConfigured = useStore((state) => state.setUpbitApiConfigured);
  const setKiwoomApiConfigured = useStore((state) => state.setKiwoomApiConfigured);
  const sidebarCollapsed = useStore((state) => state.sidebarCollapsed);
  const error = useStore(selectError);
  const setError = useStore((state) => state.setError);

  // Chat Popup state - select individual values to avoid re-renders
  const chatPopupOpen = useStore((state) => state.chatPopupOpen);
  const chatPopupSize = useStore((state) => state.chatPopupSize);
  const chatPopupPosition = useStore((state) => state.chatPopupPosition);
  const toggleChatPopup = useStore((state) => state.toggleChatPopup);
  const setChatPopupOpen = useStore((state) => state.setChatPopupOpen);
  const setChatPopupSize = useStore((state) => state.setChatPopupSize);
  const setChatPopupPosition = useStore((state) => state.setChatPopupPosition);

  // Check if there's a notification (awaiting approval or new messages)
  const awaitingApproval = useStore((state) => {
    switch (state.activeMarket) {
      case 'stock': return state.stock.awaitingApproval;
      case 'coin': return state.coin.awaitingApproval;
      case 'kiwoom': return state.kiwoom.awaitingApproval;
    }
  });
  const hasMessages = useStore((state) => state.messages.length > 0);
  const hasNotification = !chatPopupOpen && (awaitingApproval || hasMessages);

  // Check API status on mount
  useEffect(() => {
    async function checkApiStatus() {
      // Check Upbit API
      try {
        const upbitStatus = await getUpbitApiStatus();
        setUpbitApiConfigured(upbitStatus.is_configured);
      } catch (err) {
        console.error('Failed to check Upbit API status:', err);
      }

      // Check Kiwoom API
      try {
        const kiwoomStatus = await getKiwoomApiStatus();
        setKiwoomApiConfigured(kiwoomStatus.is_configured);
      } catch (err) {
        console.error('Failed to check Kiwoom API status:', err);
      }
    }
    checkApiStatus();
  }, [setUpbitApiConfigured, setKiwoomApiConfigured]);

  return (
    <div className="h-screen bg-surface flex flex-col overflow-hidden">
      {/* Header - Fixed height */}
      <Header />

      {/* Error Toast - Persistent with dismiss button */}
      {error && (
        <Toast
          message={error}
          type="error"
          duration={0}
          onClose={() => setError(null)}
        />
      )}

      {/* Main Layout - Takes remaining height */}
      <div className="flex-1 flex min-h-0">
        {/* Sidebar - Hidden on mobile, collapsible */}
        <aside
          className={`hidden lg:flex lg:flex-col h-full border-r border-border bg-surface-dark flex-shrink-0 transition-all duration-300 overflow-hidden ${
            sidebarCollapsed ? 'w-16' : 'w-60'
          }`}
        >
          <Sidebar collapsed={sidebarCollapsed} />
        </aside>

        {/* Main Content Area */}
        <main className="flex-1 flex flex-col lg:flex-row min-h-0 min-w-0 bg-surface">
          {/* Dashboard Panel - Scrollable */}
          <div className="flex-1 overflow-y-auto min-h-0 bg-surface">
            <MainContent />
          </div>
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

      {/* Chat Toggle Button - Desktop only */}
      <ChatToggleButton
        isOpen={chatPopupOpen}
        onClick={toggleChatPopup}
        hasNotification={hasNotification}
      />

      {/* Chat Popup - Desktop only */}
      <ChatPopup
        isOpen={chatPopupOpen}
        onClose={() => setChatPopupOpen(false)}
        size={chatPopupSize}
        onSizeChange={setChatPopupSize}
        position={chatPopupPosition}
        onPositionChange={setChatPopupPosition}
      />
    </div>
  );
}

export default App;
