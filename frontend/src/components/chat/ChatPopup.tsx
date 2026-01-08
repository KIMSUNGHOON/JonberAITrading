/**
 * ChatPopup Component
 *
 * Floating popup container for the Trading Assistant chat.
 * Desktop only with drag support and size options.
 */

import { useEffect, useCallback, useRef } from 'react';
import { Bot, X, Minus, Square, Maximize2 } from 'lucide-react';
import { useDraggable, type DraggablePosition } from '@/hooks/useDraggable';
import { ChatPanel } from './ChatPanel';
import type { ChatPopupSize } from '@/store';

// Size configurations
const SIZES: Record<ChatPopupSize, { width: string; height: string; label: string }> = {
  small: { width: 'w-80', height: 'h-96', label: 'S' },
  medium: { width: 'w-96', height: 'h-[32rem]', label: 'M' },
  large: { width: 'w-[28rem]', height: 'h-[40rem]', label: 'L' },
};

// localStorage keys
const STORAGE_KEY_POSITION = 'chatPopup:position';
const STORAGE_KEY_SIZE = 'chatPopup:size';

interface ChatPopupProps {
  isOpen: boolean;
  onClose: () => void;
  size: ChatPopupSize;
  onSizeChange: (size: ChatPopupSize) => void;
  position: DraggablePosition;
  onPositionChange: (position: DraggablePosition) => void;
}

export function ChatPopup({
  isOpen,
  onClose,
  size,
  onSizeChange,
  position,
  onPositionChange,
}: ChatPopupProps) {
  const popupRef = useRef<HTMLDivElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);
  const loadedFromStorageRef = useRef(false);

  // Calculate default position (bottom-right, above toggle button)
  const getDefaultPosition = useCallback((currentSize: ChatPopupSize): DraggablePosition => {
    const padding = 24; // 6 * 4 (tailwind spacing)
    const buttonSize = 56; // w-14 = 3.5rem = 56px
    const buttonMargin = 16; // gap between button and popup
    const sizeConfig = SIZES[currentSize];

    // Parse width from tailwind class
    let popupWidth = 384; // default medium w-96
    if (sizeConfig.width === 'w-80') popupWidth = 320;
    else if (sizeConfig.width === 'w-[28rem]') popupWidth = 448;

    // Parse height from tailwind class
    let popupHeight = 512; // default medium h-[32rem]
    if (sizeConfig.height === 'h-96') popupHeight = 384;
    else if (sizeConfig.height === 'h-[40rem]') popupHeight = 640;

    return {
      x: window.innerWidth - popupWidth - padding,
      y: window.innerHeight - popupHeight - padding - buttonSize - buttonMargin,
    };
  }, []);

  // Load saved position/size from localStorage (only once)
  useEffect(() => {
    if (loadedFromStorageRef.current) return;
    loadedFromStorageRef.current = true;

    const savedSize = localStorage.getItem(STORAGE_KEY_SIZE) as ChatPopupSize | null;
    const savedPosition = localStorage.getItem(STORAGE_KEY_POSITION);

    if (savedSize && ['small', 'medium', 'large'].includes(savedSize)) {
      onSizeChange(savedSize);
    }

    if (savedPosition) {
      try {
        const parsed = JSON.parse(savedPosition);
        if (typeof parsed.x === 'number' && typeof parsed.y === 'number') {
          onPositionChange(parsed);
        }
      } catch {
        // Invalid JSON, use default
      }
    }
  }, [onSizeChange, onPositionChange]);

  // Calculate initial position once
  const initialPosition = useRef<DraggablePosition>(
    position.x === -1 && position.y === -1
      ? getDefaultPosition(size)
      : position
  ).current;

  const { position: dragPosition, isDragging, handleMouseDown, setPosition } = useDraggable({
    initialPosition,
    onDragEnd: (pos) => {
      onPositionChange(pos);
      localStorage.setItem(STORAGE_KEY_POSITION, JSON.stringify(pos));
    },
  });

  // Update position when loaded from parent state (not on every render)
  useEffect(() => {
    if (position.x !== -1 && position.y !== -1) {
      setPosition(position);
    }
  }, [position.x, position.y, setPosition]);

  // Handle ESC key to close
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Handle click outside to close
  const handleBackdropClick = useCallback((e: React.MouseEvent) => {
    if (e.target === backdropRef.current) {
      onClose();
    }
  }, [onClose]);

  // Handle size change
  const handleSizeChange = useCallback((newSize: ChatPopupSize) => {
    onSizeChange(newSize);
    localStorage.setItem(STORAGE_KEY_SIZE, newSize);
  }, [onSizeChange]);

  if (!isOpen) return null;

  const sizeConfig = SIZES[size];

  return (
    <>
      {/* Invisible backdrop for click-outside detection */}
      <div
        ref={backdropRef}
        className="hidden md:block fixed inset-0 z-35"
        onClick={handleBackdropClick}
        aria-hidden="true"
        style={{ zIndex: 35 }}
      />

      {/* Popup */}
      <div
        ref={popupRef}
        className={`
          hidden md:flex flex-col
          fixed z-40
          ${sizeConfig.width} ${sizeConfig.height}
          bg-surface-dark border border-border
          rounded-xl shadow-2xl
          overflow-hidden
          ${isDragging ? 'cursor-grabbing' : ''}
        `}
        style={{
          left: `${dragPosition.x}px`,
          top: `${dragPosition.y}px`,
          transition: isDragging ? 'none' : 'box-shadow 0.2s',
        }}
      >
        {/* Header - Drag Handle */}
        <div
          className="flex items-center justify-between px-3 py-2 bg-surface border-b border-border cursor-grab active:cursor-grabbing select-none"
          onMouseDown={handleMouseDown}
        >
          {/* Title */}
          <div className="flex items-center gap-2">
            <Bot size={18} className="text-blue-400" />
            <span className="font-medium text-sm">Trading Assistant</span>
          </div>

          {/* Controls */}
          <div className="flex items-center gap-1">
            {/* Size buttons */}
            {(['small', 'medium', 'large'] as const).map((s) => (
              <button
                key={s}
                onClick={(e) => {
                  e.stopPropagation();
                  handleSizeChange(s);
                }}
                className={`
                  w-6 h-6 flex items-center justify-center rounded text-xs font-medium
                  transition-colors
                  ${size === s
                    ? 'bg-blue-600 text-white'
                    : 'bg-surface-light text-gray-400 hover:text-white hover:bg-surface'}
                `}
                title={`${s.charAt(0).toUpperCase() + s.slice(1)} size`}
              >
                {s === 'small' ? <Minus size={12} /> : s === 'medium' ? <Square size={10} /> : <Maximize2 size={12} />}
              </button>
            ))}

            {/* Close button */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                onClose();
              }}
              className="w-6 h-6 flex items-center justify-center rounded text-gray-400 hover:text-white hover:bg-red-500/20 transition-colors ml-1"
              title="Close (ESC)"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* Content - ChatPanel */}
        <div className="flex-1 overflow-hidden">
          <ChatPanel />
        </div>
      </div>
    </>
  );
}
