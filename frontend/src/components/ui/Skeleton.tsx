/**
 * Skeleton Loader Components
 *
 * Placeholder components that display while content is loading.
 */

interface SkeletonProps {
  className?: string;
}

// Base skeleton element
export function Skeleton({ className = '' }: SkeletonProps) {
  return (
    <div
      className={`animate-pulse bg-surface-light rounded ${className}`}
      aria-hidden="true"
    />
  );
}

// Text line skeleton
interface SkeletonTextProps {
  lines?: number;
  className?: string;
}

export function SkeletonText({ lines = 1, className = '' }: SkeletonTextProps) {
  return (
    <div className={`space-y-2 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={`h-4 ${i === lines - 1 ? 'w-3/4' : 'w-full'}`}
        />
      ))}
    </div>
  );
}

// Card skeleton
export function SkeletonCard({ className = '' }: SkeletonProps) {
  return (
    <div className={`card ${className}`}>
      <div className="flex items-center gap-3 mb-4">
        <Skeleton className="w-10 h-10 rounded-lg" />
        <div className="flex-1">
          <Skeleton className="h-4 w-24 mb-2" />
          <Skeleton className="h-3 w-16" />
        </div>
      </div>
      <SkeletonText lines={3} />
    </div>
  );
}

// Avatar skeleton
interface SkeletonAvatarProps {
  size?: 'sm' | 'md' | 'lg';
}

export function SkeletonAvatar({ size = 'md' }: SkeletonAvatarProps) {
  const sizeClasses = {
    sm: 'w-8 h-8',
    md: 'w-10 h-10',
    lg: 'w-14 h-14',
  };

  return <Skeleton className={`${sizeClasses[size]} rounded-full`} />;
}

// Table row skeleton
interface SkeletonTableRowProps {
  columns?: number;
}

export function SkeletonTableRow({ columns = 4 }: SkeletonTableRowProps) {
  return (
    <div className="flex items-center gap-4 py-3 border-b border-border">
      {Array.from({ length: columns }).map((_, i) => (
        <Skeleton
          key={i}
          className={`h-4 ${i === 0 ? 'w-20' : 'flex-1'}`}
        />
      ))}
    </div>
  );
}

// Chart skeleton
export function SkeletonChart({ className = '' }: SkeletonProps) {
  return (
    <div className={`card ${className}`}>
      <div className="flex items-center justify-between mb-4">
        <Skeleton className="h-5 w-32" />
        <div className="flex gap-2">
          <Skeleton className="h-8 w-16 rounded-lg" />
          <Skeleton className="h-8 w-16 rounded-lg" />
        </div>
      </div>
      <div className="relative h-64">
        <Skeleton className="absolute inset-0 rounded-lg" />
        <div className="absolute bottom-0 left-0 right-0 flex justify-between px-4 pb-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="w-8 h-3" />
          ))}
        </div>
      </div>
    </div>
  );
}

// Position/Balance skeleton
export function SkeletonBalance({ className = '' }: SkeletonProps) {
  return (
    <div className={`card ${className}`}>
      <div className="flex items-center gap-3 mb-4">
        <Skeleton className="w-10 h-10 rounded-lg" />
        <Skeleton className="h-5 w-24" />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <Skeleton className="h-3 w-16 mb-2" />
          <Skeleton className="h-6 w-24" />
        </div>
        <div>
          <Skeleton className="h-3 w-16 mb-2" />
          <Skeleton className="h-6 w-20" />
        </div>
      </div>
    </div>
  );
}

// Analysis result skeleton
export function SkeletonAnalysis({ className = '' }: SkeletonProps) {
  return (
    <div className={`card ${className}`}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Skeleton className="w-8 h-8 rounded-lg" />
          <Skeleton className="h-5 w-28" />
        </div>
        <Skeleton className="h-6 w-16 rounded-full" />
      </div>
      <div className="space-y-3">
        <div className="flex justify-between">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-4 w-16" />
        </div>
        <Skeleton className="h-2 w-full rounded-full" />
        <SkeletonText lines={2} />
      </div>
    </div>
  );
}