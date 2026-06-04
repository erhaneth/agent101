import { friendlyStep } from '../lib/labels'
import type { PipelineStep } from '../types'

/** Compact progress — only shows current + recent, hides engineer jargon by default */
export function PipelineCompact({
  steps,
  currentStep,
}: {
  steps: PipelineStep[]
  currentStep?: string | null
}) {
  const active = steps.find((s) => s.status === 'active' || s.status === 'waiting')
  const doneCount = steps.filter((s) => s.status === 'done').length

  return (
    <div className="pipeline-compact">
      <p className="pipeline-compact-label">
        {friendlyStep(active?.id ?? currentStep)}
      </p>
      <p className="pipeline-compact-meta">{doneCount} of {steps.length} steps complete</p>
    </div>
  )
}