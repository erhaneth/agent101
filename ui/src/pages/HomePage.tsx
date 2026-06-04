import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { createJob, listRuns } from '../api'
import { Spinner } from '../components/Spinner'
import { truncate } from '../lib/labels'
import type { RunSummary } from '../types'

const SUGGESTIONS = [
  'Best electric cars under $40k in 2026',
  'Do conditional cash transfers improve school outcomes?',
  'What skills do agentic AI engineer jobs ask for?',
]

export function HomePage() {
  const navigate = useNavigate()
  const [goal, setGoal] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [recent, setRecent] = useState<RunSummary[]>([])
  const [recentLoading, setRecentLoading] = useState(true)

  useEffect(() => {
    listRuns(6)
      .then((data) => setRecent(data.runs))
      .catch(() => setRecent([]))
      .finally(() => setRecentLoading(false))
  }, [])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const trimmed = goal.trim()
    if (trimmed.length < 8) return
    setError(null)
    setLoading(true)
    try {
      const job = await createJob(trimmed)
      navigate(`/jobs/${job.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start. Try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="home page-content">
      <section className="home-hero animate-hero">
        <h1>
          Ask anything.
          <br />
          <span className="text-gradient">Get a sourced answer.</span>
        </h1>
        <p className="home-sub">
          We search, verify sources, and write a report you can trust — not a guess.
        </p>

        <form className={`ask-box${loading ? ' is-loading' : ''}`} onSubmit={onSubmit}>
          <textarea
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="e.g. Is Mediterranean diet evidence strong for heart health?"
            rows={3}
            aria-label="Your question"
            disabled={loading}
          />
          <div className="ask-box-footer">
            <div className="chips-scroll">
              <div className="chips" role="list">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="chip-btn"
                    onClick={() => setGoal(s)}
                    disabled={loading}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
            <button
              type="submit"
              className="btn btn-primary btn-large"
              disabled={loading || goal.trim().length < 8}
            >
              {loading ? (
                <>
                  <Spinner size={18} /> Starting…
                </>
              ) : (
                'Research'
              )}
            </button>
          </div>
        </form>

        {error ? (
          <p className="banner banner-error animate-fade" role="alert">
            {error}
          </p>
        ) : null}
      </section>

      {recentLoading ? (
        <section className="home-recent animate-fade">
          <h2>Recent reports</h2>
          <ul className="recent-list">
            {[0, 1, 2].map((i) => (
              <li key={i} className="recent-item-skeleton">
                <span className="skeleton skeleton-dot" />
                <span className="skeleton skeleton-line" />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {!recentLoading && recent.length > 0 ? (
        <section className="home-recent animate-fade">
          <h2>Recent reports</h2>
          <ul className="recent-list stagger">
            {recent.map((run, index) => (
              <li key={run.run_id} style={{ animationDelay: `${index * 60}ms` }}>
                <button
                  type="button"
                  className="recent-item"
                  onClick={() => navigate(`/runs/${run.run_id}`)}
                >
                  <span className={`dot ${run.grounding_gate_passed ? 'ok' : ''}`} />
                  <span className="recent-text">{truncate(run.goal, 100)}</span>
                  <span className="recent-chevron" aria-hidden>
                    ›
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className="text-link" onClick={() => navigate('/runs')}>
            See all reports →
          </button>
        </section>
      ) : null}
    </main>
  )
}