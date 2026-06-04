const STEP_LABELS: Record<string, string> = {
  brief: 'Understanding your question',
  anchors: 'Mapping key topics',
  plan: 'Planning what to look up',
  search: 'Searching the web',
  source_fetch: 'Reading sources',
  fact_check: 'Rating source quality',
  claim_build: 'Extracting key facts',
  claim_verify: 'Double-checking facts',
  human_review: 'Waiting for your approval',
  budget_check: 'Organizing findings',
  build_evidence_map: 'Summarizing evidence',
  write: 'Writing your report',
  report_verify: 'Checking citations',
  report_repair: 'Fixing citations',
  evaluate: 'Final quality check',
}

const STATUS_LABELS: Record<string, string> = {
  queued: 'Starting…',
  running: 'In progress',
  awaiting_review: 'Needs your OK',
  completed: 'Done',
  failed: 'Something went wrong',
  blocked: 'Could not finish',
  canceled: 'Canceled',
}

export function friendlyStep(step?: string | null): string {
  if (!step) return 'Getting ready'
  return STEP_LABELS[step] ?? 'Working…'
}

export function friendlyStatus(status: string): string {
  return STATUS_LABELS[status] ?? status
}

export function formatRunDate(runId: string): string {
  const match = runId.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})/)
  if (!match) return ''
  const [, y, m, d, hh, mm] = match
  const date = new Date(Date.UTC(Number(y), Number(m) - 1, Number(d), Number(hh), Number(mm)))
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function truncate(text: string, max = 140): string {
  if (text.length <= max) return text
  return `${text.slice(0, max).trim()}…`
}

export function progressPercent(completed: string[], total = 15): number {
  return Math.min(100, Math.round((completed.length / total) * 100))
}
