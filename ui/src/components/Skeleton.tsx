export function Skeleton({
  className = '',
  lines = 1,
}: {
  className?: string
  lines?: number
}) {
  if (lines <= 1) {
    return <span className={`skeleton ${className}`.trim()} aria-hidden />
  }
  return (
    <div className={`skeleton-stack ${className}`.trim()} aria-hidden>
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skeleton" style={{ width: i === lines - 1 ? '72%' : '100%' }} />
      ))}
    </div>
  )
}

export function LibraryCardSkeleton() {
  return (
    <div className="library-card skeleton-card">
      <div className="library-card-top">
        <Skeleton className="skeleton-pill" />
        <Skeleton className="skeleton-date" />
      </div>
      <Skeleton lines={2} />
      <Skeleton className="skeleton-meta" />
    </div>
  )
}