import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { cancelJob, getJob, submitReview, subscribeJobEvents } from '../api'
import { PipelineCompact } from '../components/Pipeline'
import { ProgressBar } from '../components/ProgressBar'
import { ReportView } from '../components/ReportView'
import { ReviewModal } from '../components/ReviewModal'
import { Skeleton } from '../components/Skeleton'
import { Spinner } from '../components/Spinner'
import { friendlyStatus, friendlyStep, progressPercent } from '../lib/labels'
import type { ResearchJob } from '../types'

export function JobPage() {
  const { jobId = '' } = useParams()
  const navigate = useNavigate()
  const [job, setJob] = useState<ResearchJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reviewBusy, setReviewBusy] = useState(false)
  const [cancelBusy, setCancelBusy] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function refresh() {
      try {
        const next = await getJob(jobId, true)
        if (!cancelled) setJob(next)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not load status')
        }
      }
    }

    refresh()
    const unsubscribe = subscribeJobEvents(jobId, refresh, refresh)
    const interval = window.setInterval(refresh, 3000)
    return () => {
      cancelled = true
      unsubscribe()
      window.clearInterval(interval)
    }
  }, [jobId])

  async function handleReview(approved: boolean) {
    setReviewBusy(true)
    try {
      await submitReview(jobId, approved)
      const next = await getJob(jobId, true)
      setJob(next)
    } finally {
      setReviewBusy(false)
    }
  }

  async function handleCancel() {
    setCancelBusy(true)
    setError(null)
    try {
      const next = await cancelJob(jobId)
      setJob(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not cancel job')
    } finally {
      setCancelBusy(false)
    }
  }

  if (error && !job) {
    return (
      <main className="center-state page-content">
        <p className="banner banner-error" role="alert">
          {error}
        </p>
      </main>
    )
  }

  if (!job) {
    return (
      <main className="job-page page-content">
        <div className="job-header">
          <Skeleton className="skeleton-back" />
          <Skeleton lines={2} />
        </div>
        <div className="job-progress-card">
          <Skeleton className="skeleton-progress" />
        </div>
        <div className="job-waiting">
          <Spinner size={36} />
        </div>
      </main>
    )
  }

  const state = (job as ResearchJob & { state?: { report?: string } }).state
  const report = state?.report
  const done = ['completed', 'failed', 'blocked', 'canceled'].includes(job.status)
  const progress = progressPercent(job.completed_steps)
  const showReview = job.status === 'awaiting_review' && job.pending_review
  const running = !done
  const canCancel = running && ['queued', 'running', 'awaiting_review'].includes(job.status)

  return (
    <main className="job-page page-content">
      {showReview && job.pending_review ? (
        <ReviewModal
          review={job.pending_review}
          busy={reviewBusy}
          onApprove={() => handleReview(true)}
          onReject={() => handleReview(false)}
        />
      ) : null}

      <header className="job-header animate-hero">
        <button type="button" className="back-btn" onClick={() => navigate('/')}>
          ← Back
        </button>
        <h1>{job.goal}</h1>
        <span className={`live-badge status-${job.status}${running ? ' is-pulse' : ''}`}>
          {friendlyStatus(job.status)}
        </span>
      </header>

      {running ? (
        <section className="job-progress-card animate-fade">
          <ProgressBar
            value={progress}
            label={friendlyStep(job.current_step)}
            active={job.status === 'running' || job.status === 'awaiting_review'}
          />
          <PipelineCompact steps={job.pipeline} currentStep={job.current_step} />
          <div className="job-progress-actions">
            <p className="job-hint">Usually takes a few minutes. Keep this tab open.</p>
            {canCancel ? (
              <button
                type="button"
                className="btn btn-secondary"
                disabled={cancelBusy || job.cancel_requested}
                onClick={handleCancel}
              >
                {job.cancel_requested
                  ? 'Cancel requested'
                  : cancelBusy
                    ? 'Canceling…'
                    : job.status === 'queued'
                      ? 'Cancel queued job'
                      : 'Request cancellation'}
              </button>
            ) : null}
          </div>
        </section>
      ) : null}

      {done && report ? (
        <section className="job-result animate-fade">
          {job.run_id ? (
            <button
              type="button"
              className="text-link"
              onClick={() => navigate(`/runs/${job.run_id}`)}
            >
              Open in library →
            </button>
          ) : null}
          <ReportView markdown={report} />
        </section>
      ) : null}

      {done && !report ? (
        <section className="job-blocked animate-fade">
          <div className="blocked-icon" aria-hidden>
            !
          </div>
          <h2>We couldn&apos;t finish this report</h2>
          <p>
            {job.status === 'canceled'
              ? 'This job was canceled before it started.'
              : job.status === 'blocked'
              ? 'Safety checks or source quality blocked the final answer.'
              : job.error ?? 'Something went wrong during research.'}
          </p>
          <button type="button" className="btn btn-primary" onClick={() => navigate('/')}>
            Try another question
          </button>
        </section>
      ) : null}

      {running && !report ? (
        <section className="job-waiting animate-fade">
          <div className="pulse-ring">
            <Spinner size={36} />
          </div>
          <p>Building your sourced report…</p>
        </section>
      ) : null}
    </main>
  )
}
