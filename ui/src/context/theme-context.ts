import { createContext } from 'react'

export type ThemePreference = 'light' | 'dark' | 'system'

export type ThemeContextValue = {
  preference: ThemePreference
  resolved: 'light' | 'dark'
  setPreference: (next: ThemePreference) => void
  toggle: () => void
}

export const ThemeContext = createContext<ThemeContextValue | null>(null)
