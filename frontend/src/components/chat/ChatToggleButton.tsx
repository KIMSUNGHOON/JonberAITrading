/**
 * ChatToggleButton Component
 *
 * Floating action button to toggle the chat popup.
 * Desktop only (hidden on mobile where bottom sheet is used).
 */

import { MessageSquare, X } from 'lucide-react';

interface ChatToggleButtonProps {
  isOpen: boolean;
  onClick: () => void;
  hasNotification: boolean;
}

export function ChatToggleButton({ isOpen, onClick, hasNotification }: ChatToggleButtonProps) {
  return (
    <button
      onClick={onClick}
      className="
        hidden md:flex
        fixed bottom-6 right-6 z-30
        w-14 h-14 rounded-full
        bg-blue-600 hover:bg-blue-700
        text-white
        items-center justify-center
        shadow-lg hover:shadow-xl
        transition-all duration-200
        focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-900
      "
      aria-label={isOpen ? 'Close chat' : 'Open chat'}
      title={isOpen ? 'Close Trading Assistant' : 'Open Trading Assistant'}
    >
      {isOpen ? (
        <X size={24} />
      ) : (
        <>
          <MessageSquare size={24} />
          {/* Notification badge */}
          {hasNotification && (
            <span className="absolute top-0 right-0 w-4 h-4 bg-yellow-400 rounded-full animate-pulse border-2 border-gray-900" />
          )}
        </>
      )}
    </button>
  );
}
