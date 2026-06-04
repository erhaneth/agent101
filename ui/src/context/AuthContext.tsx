import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { ApiError, getAuthConfig, getMe, googleAuthUrl, logout as apiLogout } from '../api'
import { AuthContext } from './auth-context'
import type { AuthConfig, User } from '../types'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    const [cfg, me] = await Promise.all([getAuthConfig(), getMe()])
    setConfig(cfg)
    setUser(me.authenticated ? me.user : null)
  }, [])

  useEffect(() => {
    let cancelled = false

    queueMicrotask(() => {
      refresh()
        .catch(() => {
          if (cancelled) return
          setConfig({ auth_required: true, google_enabled: false })
          setUser(null)
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    })

    return () => {
      cancelled = true
    }
  }, [refresh])

  const loginWithGoogle = useCallback(() => {
    window.location.href = googleAuthUrl()
  }, [])

  const logout = useCallback(async () => {
    try {
      await apiLogout()
    } catch (err) {
      if (!(err instanceof ApiError)) throw err
    }
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, loading, config, loginWithGoogle, logout, refresh }),
    [user, loading, config, loginWithGoogle, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
