export function ProgressBar({
  value,
  label,
  active = true,
}: {
  value: number
  label?: string
  active?: boolean
}) {
  const clamped = Math.max(0, Math.min(100, value))

  return (
    <div
      className={`progress-wrap${active ? ' is-active' : ''}`}
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? 'Progress'}
    >
      {label ? <p className="progress-label">{label}</p> : null}
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${clamped}%` }} />
        {active && clamped < 100 ? <div className="progress-shimmer" aria-hidden /> : null}
      </div>
    </div>
  )
}