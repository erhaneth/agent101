import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/useAuth'

export function UserMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)

  if (!user) return null

  const initials = user.name
    .split(' ')
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  async function onLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <div className="user-menu">
      <button
        type="button"
        className="user-menu-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        {user.picture ? (
          <img src={user.picture} alt="" className="user-avatar" />
        ) : (
          <span className="user-avatar user-avatar-fallback">{initials}</span>
        )}
      </button>
      {open ? (
        <>
          <button
            type="button"
            className="user-menu-backdrop"
            aria-label="Close menu"
            onClick={() => setOpen(false)}
          />
          <div className="user-menu-panel" role="menu">
            <p className="user-menu-name">{user.name}</p>
            <p className="user-menu-email">{user.email}</p>
            <button type="button" role="menuitem" onClick={onLogout}>
              Sign out
            </button>
          </div>
        </>
      ) : null}
    </div>
  )
}
