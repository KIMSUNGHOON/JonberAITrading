/**
 * useDraggable Hook
 *
 * Provides drag functionality for floating elements.
 * Used by ChatPopup component for desktop drag behavior.
 */

import { useState, useCallback, useEffect, useRef } from 'react';

export interface DraggablePosition {
  x: number;
  y: number;
}

interface UseDraggableOptions {
  initialPosition: DraggablePosition;
  onDragEnd?: (position: DraggablePosition) => void;
}

interface UseDraggableReturn {
  position: DraggablePosition;
  isDragging: boolean;
  handleMouseDown: (e: React.MouseEvent) => void;
  setPosition: (position: DraggablePosition) => void;
}

export function useDraggable({
  initialPosition,
  onDragEnd,
}: UseDraggableOptions): UseDraggableReturn {
  const [position, setPosition] = useState<DraggablePosition>(initialPosition);
  const [isDragging, setIsDragging] = useState(false);
  const dragOffset = useRef<DraggablePosition>({ x: 0, y: 0 });
  const initializedRef = useRef(false);

  // Update position only once on mount if valid
  useEffect(() => {
    if (!initializedRef.current && initialPosition.x !== -1 && initialPosition.y !== -1) {
      setPosition(initialPosition);
      initializedRef.current = true;
    }
  }, [initialPosition.x, initialPosition.y]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    // Only start drag on left mouse button
    if (e.button !== 0) return;

    // Prevent text selection during drag
    e.preventDefault();

    setIsDragging(true);
    dragOffset.current = {
      x: e.clientX - position.x,
      y: e.clientY - position.y,
    };
  }, [position]);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const newX = e.clientX - dragOffset.current.x;
      const newY = e.clientY - dragOffset.current.y;

      // Keep popup within viewport bounds
      const maxX = window.innerWidth - 100; // minimum 100px visible
      const maxY = window.innerHeight - 50; // minimum 50px visible

      setPosition({
        x: Math.max(0, Math.min(newX, maxX)),
        y: Math.max(0, Math.min(newY, maxY)),
      });
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      onDragEnd?.(position);
    };

    // Use passive: false for better drag performance
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    // Add cursor style during drag
    document.body.style.cursor = 'grabbing';
    document.body.style.userSelect = 'none';

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [isDragging, onDragEnd, position]);

  return {
    position,
    isDragging,
    handleMouseDown,
    setPosition,
  };
}
