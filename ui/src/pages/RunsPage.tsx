import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listRuns } from '../api'
import { LibraryCardSkeleton } from '../components/Skeleton'
import { formatRunDate, truncate } from '../lib/labels'
import type { RunSummary } from '../types'

export function RunsPage() {
  const navigate = useNavigate()
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  useEffect(() => {
    listRuns(80)
      .then((data) => setRuns(data.runs))
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load reports'))
      .finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return runs
    return runs.filter((r) => r.goal.toLowerCase().includes(q))
  }, [runs, query])

  return (
    <main className="library page-content">
      <header className="library-head animate-hero">
        <div>
          <h1>Your reports</h1>
          <p className="library-sub">{runs.length} saved {runs.length === 1 ? 'report' : 'reports'}</p>
        </div>
        <button type="button" className="btn btn-primary desktop-only" onClick={() => navigate('/')}>
          New question
        </button>
      </header>

      <div className="search-wrap animate-fade">
        <svg className="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3-3" strokeLinecap="round" />
        </svg>
        <input
          type="search"
          className="search-input"
          placeholder="Search your questions…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search reports"
        />
      </div>

      {loading ? (
        <ul className="library-grid">
          {[0, 1, 2, 4].map((i) => (
            <li key={i}>
              <LibraryCardSkeleton />
            </li>
          ))}
        </ul>
      ) : null}

      {error ? (
        <p className="banner banner-error animate-fade" role="alert">
          {error}
        </p>
      ) : null}

      {!loading && !error && filtered.length === 0 ? (
        <div className="center-state animate-fade">
          <p>{query ? 'No matches.' : 'No reports yet.'}</p>
          <button type="button" className="btn btn-primary" onClick={() => navigate('/')}>
            Ask your first question
          </button>
        </div>
      ) : null}

      {!loading && filtered.length > 0 ? (
        <ul className="library-grid stagger">
          {filtered.map((run, index) => (
            <li key={run.run_id} style={{ animationDelay: `${Math.min(index, 12) * 40}ms` }}>
              <button
                type="button"
                className="library-card"
                onClick={() => navigate(`/runs/${run.run_id}`)}
              >
                <div className="library-card-top">
                  <span className={`status-tag ${run.grounding_gate_passed ? 'ok' : 'warn'}`}>
                    {run.grounding_gate_passed ? 'Verified' : 'Review'}
                  </span>
                  <time>{formatRunDate(run.run_id)}</time>
                </div>
                <h2>{truncate(run.goal, 160)}</h2>
                <p className="library-card-meta">
                  {run.verified_finding_count ?? 0} sources · {run.claim_count ?? 0} facts
                  {run.grounding_score != null ? ` · ${Math.round(run.grounding_score)}% grounded` : ''}
                </p>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </main>
  )
}