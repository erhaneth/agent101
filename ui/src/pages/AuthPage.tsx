import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/useAuth'
import { Spinner } from '../components/Spinner'
import { ThemeToggle } from '../components/ThemeToggle'

const ERROR_MESSAGES: Record<string, string> = {
  access_denied: 'Google sign-in was cancelled.',
  invalid_state: 'Session expired. Please try again.',
  token_exchange_failed: 'Could not complete sign-in. Try again.',
  profile_failed: 'Could not load your Google profile.',
  profile_incomplete: 'Google did not return required profile info.',
}

type Mode = 'login' | 'signup'

export function AuthPage({ mode }: { mode: Mode }) {
  const { user, loading, config, loginWithGoogle } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [submitting, setSubmitting] = useState(false)

  const errorCode = params.get('error')
  const errorMessage = errorCode
    ? ERROR_MESSAGES[errorCode] ?? 'Sign-in failed. Please try again.'
    : null

  useEffect(() => {
    if (!loading && user) {
      navigate('/', { replace: true })
    }
  }, [loading, user, navigate])

  function onGoogle() {
    if (!config?.google_enabled) return
    setSubmitting(true)
    loginWithGoogle()
  }

  const isLogin = mode === 'login'

  if (loading) {
    return (
      <main className="auth-page">
        <div className="center-state">
          <Spinner size={32} />
        </div>
      </main>
    )
  }

  return (
    <main className="auth-page">
      <header className="auth-top">
        <Link to="/" className="logo">
          <span className="logo-mark" aria-hidden />
          FactCrafter
        </Link>
        <ThemeToggle />
      </header>

      <section className="auth-card animate-hero">
        <h1>{isLogin ? 'Welcome back' : 'Create your account'}</h1>
        <p className="auth-lead">
          {isLogin
            ? 'Sign in to run research and access your personal report library.'
            : 'One click with Google. Your reports stay private to your account.'}
        </p>

        {errorMessage ? (
          <p className="banner banner-error" role="alert">
            {errorMessage}
          </p>
        ) : null}

        {!config?.google_enabled ? (
          <p className="banner banner-error" role="alert">
            Google sign-in is not configured yet. Add GOOGLE_OAUTH_CLIENT_ID and
            GOOGLE_OAUTH_CLIENT_SECRET to your server .env file.
          </p>
        ) : null}

        <button
          type="button"
          className="btn btn-google"
          onClick={onGoogle}
          disabled={!config?.google_enabled || submitting}
        >
          <GoogleIcon />
          {submitting ? 'Redirecting…' : 'Continue with Google'}
        </button>

        <p className="auth-switch">
          {isLogin ? (
            <>
              New here? <Link to="/signup">Create account</Link>
            </>
          ) : (
            <>
              Already have an account? <Link to="/login">Sign in</Link>
            </>
          )}
        </p>

        <p className="auth-fineprint">
          By continuing, you agree that FactCrafter stores your account info to save reports.
          Email/password sign-up is coming later.
        </p>
      </section>
    </main>
  )
}

function GoogleIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden>
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
      />
    </svg>
  )
}
