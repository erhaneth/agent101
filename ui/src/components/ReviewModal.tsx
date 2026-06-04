import { useEffect } from 'react'
import type { ResearchJob } from '../types'

type Props = {
  review: NonNullable<ResearchJob['pending_review']>
  onApprove: () => void
  onReject: () => void
  busy?: boolean
}

export function ReviewModal({ review, onApprove, onReject, busy }: Props) {
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [])

  return (
    <div className="modal-backdrop is-open" role="dialog" aria-modal="true" aria-labelledby="review-title">
      <div className="modal">
        <h2 id="review-title">Quick check before we write</h2>
        <p className="modal-lead">
          Skim these facts — we only write from what you approve.
        </p>
        <ul className="review-claims stagger">
          {review.claims.map((claim, index) => (
            <li key={`${claim.claim}-${index}`} style={{ animationDelay: `${index * 50}ms` }}>
              <p>{claim.claim}</p>
              {claim.confidence ? <span className="chip">{claim.confidence} confidence</span> : null}
            </li>
          ))}
        </ul>
        <div className="modal-actions">
          <button type="button" className="btn btn-primary" disabled={busy} onClick={onApprove}>
            {busy ? 'Saving…' : 'Looks good — write report'}
          </button>
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={onReject}>
            Not yet
          </button>
        </div>
      </div>
    </div>
  )
}