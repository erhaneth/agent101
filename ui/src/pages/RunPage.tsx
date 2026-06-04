import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getRun } from '../api'
import { ReportView } from '../components/ReportView'
import { Skeleton } from '../components/Skeleton'
import { formatRunDate } from '../lib/labels'
import type { RunDetail } from '../types'

type Panel = 'report' | 'sources' | 'facts'

export function RunPage() {
  const { runId = '' } = useParams()
  const navigate = useNavigate()
  const [run, setRun] = useState<RunDetail | null>(null)
  const [panel, setPanel] = useState<Panel>('report')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    queueMicrotask(() => {
      setLoading(true)
      setError(null)
      getRun(runId)
        .then((nextRun) => {
          if (!cancelled) setRun(nextRun)
        })
        .catch((err) => {
          if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load report')
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    })

    return () => {
      cancelled = true
    }
  }, [runId])

  if (loading) {
    return (
      <main className="report-page page-content">
        <div className="report-header">
          <Skeleton className="skeleton-back" />
          <Skeleton lines={3} />
          <div className="report-header-meta">
            <Skeleton className="skeleton-meta" />
            <Skeleton className="skeleton-meta" />
          </div>
        </div>
        <div className="segmented skeleton-segmented">
          <Skeleton className="skeleton-tab" />
          <Skeleton className="skeleton-tab" />
          <Skeleton className="skeleton-tab" />
        </div>
        <div className="report-body">
          <Skeleton lines={8} />
        </div>
      </main>
    )
  }

  if (error || !run) {
    return (
      <main className="center-state page-content">
        <p className="banner banner-error" role="alert">
          {error ?? 'Report not found'}
        </p>
        <button type="button" className="btn btn-primary" onClick={() => navigate('/runs')}>
          Back to library
        </button>
      </main>
    )
  }

  const goal = String(run.summary?.goal ?? '')
  const claims = (run.claims as Array<Record<string, unknown>> | undefined) ?? []
  const sources = (run.verified_findings as Array<Record<string, unknown>> | undefined) ?? []
  const score = run.summary?.grounding_score

  return (
    <main className="report-page page-content">
      <header className="report-header animate-hero">
        <button type="button" className="back-btn" onClick={() => navigate('/runs')}>
          ← Library
        </button>
        <h1>{goal}</h1>
        <div className="report-header-meta">
          <time>{formatRunDate(run.run_id)}</time>
          {score != null ? <span>{Math.round(Number(score))}% source-backed</span> : null}
          <span>{sources.length} sources</span>
        </div>
      </header>

      <div className="segmented-sticky">
        <div className="segmented" role="tablist">
          {(
            [
              ['report', 'Report'],
              ['facts', `Facts (${claims.length})`],
              ['sources', `Sources (${sources.length})`],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={panel === id}
              className={panel === id ? 'is-active' : ''}
              onClick={() => setPanel(id)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className={`report-body panel-${panel} animate-fade`} key={panel}>
        {panel === 'report' && run.report_md ? <ReportView markdown={run.report_md} /> : null}
        {panel === 'report' && !run.report_md ? (
          <p className="empty-note">No report was saved for this run.</p>
        ) : null}

        {panel === 'facts' ? (
          <ul className="fact-cards stagger">
            {claims.length === 0 ? <li className="empty-note">No extracted facts.</li> : null}
            {claims.map((claim, i) => (
              <li key={i} className="fact-card" style={{ animationDelay: `${i * 45}ms` }}>
                <p>{String(claim.claim ?? '')}</p>
                <div className="fact-card-foot">
                  {claim.confidence ? <span className="chip">{String(claim.confidence)}</span> : null}
                  {Array.isArray(claim.support_urls)
                    ? claim.support_urls.slice(0, 2).map((url) => (
                        <a key={String(url)} href={String(url)} target="_blank" rel="noreferrer">
                          Source
                        </a>
                      ))
                    : null}
                </div>
              </li>
            ))}
          </ul>
        ) : null}

        {panel === 'sources' ? (
          <ul className="source-cards stagger">
            {sources.length === 0 ? <li className="empty-note">No verified sources.</li> : null}
            {sources.map((source, i) => (
              <li key={i} className="source-card" style={{ animationDelay: `${i * 45}ms` }}>
                <a href={String(source.url ?? '#')} target="_blank" rel="noreferrer">
                  {String(source.title || source.url || 'Source')}
                </a>
                <p>{String(source.reason || source.snippet || '').slice(0, 220)}</p>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </main>
  )
}
