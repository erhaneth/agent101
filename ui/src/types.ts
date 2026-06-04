export type User = {
  id: string
  email: string
  name: string
  picture?: string | null
  created_at: string
}

export type AuthConfig = {
  auth_required: boolean
  google_enabled: boolean
}

export type AuthMeResponse = {
  authenticated: boolean
  user: User | null
}

export type RunSummary = {
  run_id: string
  goal: string
  created_at?: string
  brief_type?: string
  grounding_gate_passed?: boolean
  grounding_score?: number
  verified_finding_count?: number
  claim_count?: number
}

export type PipelineStep = {
  id: string
  label: string
  status: 'pending' | 'active' | 'done' | 'waiting' | 'failed'
}

export type ResearchJob = {
  id: string
  goal: string
  status: string
  current_step?: string
  completed_steps: string[]
  run_id?: string
  artifact_dir?: string
  error?: string
  cancel_requested?: boolean
  pipeline: PipelineStep[]
  summary?: Record<string, unknown>
  pending_review?: {
    job_id: string
    goal: string
    reasons: string[]
    claims: Array<{
      claim: string
      support_urls?: string[]
      confidence?: string
      caveat?: string
    }>
  } | null
  events: Array<{
    type: string
    message: string
    step?: string
    payload?: Record<string, unknown>
    created_at: string
  }>
}

export type RunDetail = {
  run_id: string
  artifact_dir: string
  report_md?: string
  summary_md?: string
  summary?: Record<string, unknown>
  brief?: Record<string, unknown>
  claims?: Array<Record<string, unknown>>
  verified_findings?: Array<Record<string, unknown>>
  evaluation?: Record<string, unknown>
}
