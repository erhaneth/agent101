import type { AuthConfig, AuthMeResponse, ResearchJob, RunDetail, RunSummary } from './types'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      ...(init?.headers ?? {}),
    },
  })
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const data = await response.json()
      message = data.detail ?? data.message ?? message
    } catch {
      message = (await response.text()) || message
    }
    throw new ApiError(response.status, message)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return response.json() as Promise<T>
}

export function getAuthConfig() {
  return request<AuthConfig>('/api/auth/config')
}

export function getMe() {
  return request<AuthMeResponse>('/api/auth/me')
}

export function logout() {
  return request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' })
}

export function googleAuthUrl() {
  return `${API_BASE}/api/auth/google`
}

export function listRuns(limit = 50) {
  return request<{ runs: RunSummary[] }>(`/api/runs?limit=${limit}`)
}

export function getRun(runId: string) {
  return request<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`)
}

export function listJobs() {
  return request<{ jobs: ResearchJob[] }>('/api/jobs')
}

export function getJob(jobId: string, includeState = false) {
  const query = includeState ? '?include_state=true' : ''
  return request<ResearchJob>(`/api/jobs/${encodeURIComponent(jobId)}${query}`)
}

export function createJob(goal: string) {
  return request<ResearchJob>('/api/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ goal }),
  })
}

export function submitReview(jobId: string, approved: boolean) {
  return request<{ ok: boolean; approved: boolean }>(
    `/api/jobs/${encodeURIComponent(jobId)}/review`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved }),
    },
  )
}

export function cancelJob(jobId: string) {
  return request<ResearchJob>(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
  })
}

export function subscribeJobEvents(
  jobId: string,
  onEvent: (payload: Record<string, unknown>) => void,
  onDone: () => void,
) {
  const source = new EventSource(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/events`, {
    withCredentials: true,
  })
  source.onmessage = (event) => {
    const payload = JSON.parse(event.data) as Record<string, unknown>
    if (payload.type === 'done') {
      source.close()
      onDone()
      return
    }
    onEvent(payload)
  }
  source.onerror = () => {
    source.close()
    onDone()
  }
  return () => source.close()
}
