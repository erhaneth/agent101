import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/useAuth'
import { Spinner } from './Spinner'

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading, config } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <main className="center-state page-content">
        <Spinner size={32} />
        <p>Loading…</p>
      </main>
    )
  }

  const needsAuth = config?.auth_required !== false
  if (needsAuth && !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return children
}
