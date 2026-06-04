import { Link, Outlet, useLocation } from 'react-router-dom'
import { PageTransition } from './PageTransition'
import { MobileNav } from './MobileNav'
import { ThemeToggle } from './ThemeToggle'
import { UserMenu } from './UserMenu'

export function Layout() {
  const { pathname } = useLocation()
  const onHome = pathname === '/'
  const onLibrary = pathname.startsWith('/runs')

  return (
    <div className="shell">
      <header className="header">
        <Link to="/" className="logo">
          <span className="logo-mark" aria-hidden />
          FactCrafter
        </Link>
        <div className="header-end">
          <nav className="header-nav desktop-only" aria-label="Main">
            <Link to="/" className={onHome ? 'is-active' : ''}>
              Ask
            </Link>
            <Link to="/runs" className={onLibrary ? 'is-active' : ''}>
              Library
            </Link>
          </nav>
          <ThemeToggle />
          <UserMenu />
        </div>
      </header>

      <PageTransition>
        <Outlet />
      </PageTransition>

      <MobileNav />
    </div>
  )
}