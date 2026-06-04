import type { ThemePreference } from '../context/theme-context'
import { useTheme } from '../context/useTheme'

const LABELS: Record<ThemePreference, string> = {
  light: 'Light',
  dark: 'Dark',
  system: 'Auto',
}

export function ThemeToggle() {
  const { preference, resolved, toggle } = useTheme()

  const trackState =
    preference === 'system' ? 'system' : resolved

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={`Theme: ${LABELS[preference]}. Currently ${resolved}. Click to change.`}
      title={`${LABELS[preference]} mode`}
    >
      <span className="theme-toggle-track" data-mode={trackState}>
        <span className="theme-toggle-knob" aria-hidden />
        <span className="theme-toggle-icons" aria-hidden>
          <svg className="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
          </svg>
          <svg className="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 14.5A8.5 8.5 0 1 1 9.5 3 7 7 0 0 0 21 14.5z" />
          </svg>
        </span>
      </span>
      <span className="theme-toggle-label">{LABELS[preference]}</span>
    </button>
  )
}
