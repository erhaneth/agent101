import { useLocation } from 'react-router-dom'

export function PageTransition({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation()

  return (
    <div className="page-transition" key={pathname}>
      {children}
    </div>
  )
}
