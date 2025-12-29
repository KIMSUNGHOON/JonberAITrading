/**
 * Spinner Component
 *
 * Loading spinner with customizable size and color.
 */

import { Loader2 } from 'lucide-react';

type SpinnerSize = 'sm' | 'md' | 'lg' | 'xl';

interface SpinnerProps {
  size?: SpinnerSize;
  className?: string;
  label?: string;
}

const sizeMap: Record<SpinnerSize, string> = {
  sm: 'w-4 h-4',
  md: 'w-6 h-6',
  lg: 'w-8 h-8',
  xl: 'w-12 h-12',
};

export function Spinner({ size = 'md', className = '', label }: SpinnerProps) {
  return (
    <div
      role="status"
      aria-label={label || 'Loading'}
      className={`inline-flex items-center justify-center ${className}`}
    >
      <Loader2 className={`${sizeMap[size]} animate-spin text-blue-500`} />
      {label && <span className="sr-only">{label}</span>}
    </div>
  );
}

// Full-page loading overlay
interface LoadingOverlayProps {
  message?: string;
}

export function LoadingOverlay({ message = 'Loading...' }: LoadingOverlayProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-surface/80 backdrop-blur-sm"
      role="progressbar"
      aria-label={message}
    >
      <div className="flex flex-col items-center gap-3">
        <Spinner size="xl" />
        <span className="text-sm text-gray-400">{message}</span>
      </div>
    </div>
  );
}

// Inline loading state
interface InlineLoadingProps {
  message?: string;
  className?: string;
}

export function InlineLoading({ message = 'Loading...', className = '' }: InlineLoadingProps) {
  return (
    <div className={`flex items-center gap-2 text-gray-400 ${className}`}>
      <Spinner size="sm" />
      <span className="text-sm">{message}</span>
    </div>
  );
}