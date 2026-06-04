import { createContext } from 'react'
import type { AuthConfig, User } from '../types'

export type AuthContextValue = {
  user: User | null
  loading: boolean
  config: AuthConfig | null
  loginWithGoogle: () => void
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)
