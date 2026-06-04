import { Link, useLocation } from 'react-router-dom'

export function MobileNav() {
  const { pathname } = useLocation()
  const onAsk = pathname === '/' || pathname.startsWith('/jobs')
  const onLibrary = pathname.startsWith('/runs')

  return (
    <nav className="mobile-nav" aria-label="Mobile">
      <Link to="/" className={onAsk ? 'is-active' : ''}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden>
          <path
            d="M12 3c4.97 0 9 3.13 9 7s-4.03 7-9 7c-.86 0-1.69-.1-2.47-.28L5 20l1.35-3.38C4.52 15.2 3 13.28 3 10c0-3.87 4.03-7 9-7z"
            strokeLinejoin="round"
          />
        </svg>
        <span>Ask</span>
      </Link>
      <Link to="/runs" className={onLibrary ? 'is-active' : ''}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden>
          <path d="M4 7h16M4 12h16M4 17h10" strokeLinecap="round" />
        </svg>
        <span>Library</span>
      </Link>
    </nav>
  )
}