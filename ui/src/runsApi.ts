// Runs, events and approvals (`/api/*`, the dev key is a superuser token in dev
// mode) plus the dev-only pin and replay helpers.
import { apiFetch, request, toApiError } from './api'

export type RunStatus =
  | 'queued' | 'running' | 'waiting_human' | 'waiting_approval' | 'paused'
  | 'completed' | 'failed' | 'aborted' | 'compensated'

export interface Approval {
  approval_id: string
  run_id: string
  agent_id: string
  kind: 'human' | 'tool' | 'pause'
  status: string
  required_group: string | null
  expires_at: string | null
  created_at: string | null
  title?: string
  instruction?: string | null
  show?: Record<string, unknown>
  form?: Record<string, { type: string; required: boolean; label?: string; widget?: string; help?: string }>
  tool?: string
  args?: Record<string, unknown>
  reason?: string
}

export interface Run {
  run_id: string
  workflow: string
  status: RunStatus
  trigger: string
  current_agent: string | null
  end: string | null
  output: { status?: number; body?: unknown } | null
  error: string | null
  tokens_used: number
  created_at: string | null
  updated_at: string | null
  approval?: Approval
}

export interface RunEvent {
  run_id: string
  seq: number
  ts: string
  type: string
  agent_id: string | null
  engine: string | null
  tokens: number | null
  latency_ms: number | null
  payload: Record<string, unknown>
}

export const TERMINAL: RunStatus[] = ['completed', 'failed', 'aborted', 'compensated']

export function listRuns(filters: { workflow?: string; status?: string; limit?: number } = {}): Promise<Run[]> {
  const q = new URLSearchParams()
  if (filters.workflow) q.set('workflow', filters.workflow)
  if (filters.status) q.set('status', filters.status)
  q.set('limit', String(filters.limit ?? 50))
  return request<Run[]>(`/api/runs?${q}`)
}

export const getRun = (id: string) => request<Run>(`/api/runs/${id}`)

export function startRun(workflow: string, input: Record<string, unknown>): Promise<{ run_id: string }> {
  return request(`/api/workflows/${encodeURIComponent(workflow)}/runs?wait=false`, {
    method: 'POST',
    body: JSON.stringify({ input }),
  })
}

export function controlRun(id: string, action: 'pause' | 'resume' | 'abort' | 'steer', message?: string) {
  return request(`/api/runs/${id}/${action}`, {
    method: 'POST',
    body: JSON.stringify(message ? { message } : {}),
  })
}

export const listApprovals = () => request<Approval[]>('/api/approvals')

export function decideApproval(
  id: string,
  body: { values?: Record<string, unknown>; decision?: 'approve' | 'reject' | 'edit'; edited_args?: unknown; message?: string },
) {
  return request(`/api/approvals/${id}`, { method: 'POST', body: JSON.stringify(body) })
}

export const pinRun = (id: string, name?: string) =>
  request<{ pinned: string }>(`/dev/runs/${id}/pin`, { method: 'POST', body: JSON.stringify({ name }) })

export const replayFixtures = (fixtures: string[]) =>
  request<{ passed: boolean; replays: { name: string; passed: boolean; failures: string[]; end: string | null }[] }>(
    '/dev/runs/replay',
    { method: 'POST', body: JSON.stringify({ fixtures }) },
  )

/** A piece of an answer being written (`delta`, or the whole draft so far when `replay`) or the order to drop it. */
export interface Draft {
  kind: 'delta' | 'reset'
  agent_id: string
  delta: string
  replay: boolean
}

/** Parse a `text/event-stream` body into its frames: the event name and the `data:` JSON. */
export function parseSseFrames(chunk: string): { frames: { event: string; data: unknown }[]; rest: string } {
  const frames: { event: string; data: unknown }[] = []
  const blocks = chunk.split('\n\n')
  const rest = blocks.pop() ?? ''
  for (const block of blocks) {
    const lines = block.split('\n')
    const data = lines.filter((l) => l.startsWith('data: ')).map((l) => l.slice(6)).join('\n')
    const event = lines.find((l) => l.startsWith('event: '))?.slice(7) ?? ''
    if (data) frames.push({ event, data: JSON.parse(data) })
  }
  return { frames, rest }
}

/** Parse a `text/event-stream` body into its journal events (live drafts are not journal events). */
export function parseSse(chunk: string): { events: RunEvent[]; rest: string } {
  const { frames, rest } = parseSseFrames(chunk)
  const events = frames.filter((f) => f.event !== 'token_delta' && f.event !== 'token_reset').map((f) => f.data as RunEvent)
  return { events, rest }
}

/**
 * Follow a run's events (replay, then live) until it ends or `signal` aborts. With `onDraft`, the live draft of an
 * answer being written is delivered too.
 */
export async function followEvents(
  id: string,
  onEvent: (e: RunEvent) => void,
  signal: AbortSignal,
  onDraft?: (d: Draft) => void,
): Promise<void> {
  const res = await apiFetch(`/api/runs/${id}/events${onDraft ? '?drafts=true' : ''}`, { signal })
  if (!res.ok || !res.body) throw await toApiError(res)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    const { frames, rest } = parseSseFrames(buffer + decoder.decode(value, { stream: true }))
    buffer = rest
    for (const { event, data } of frames) {
      if (event === 'token_delta' || event === 'token_reset') {
        const d = data as { agent_id: string; delta?: string; replay?: boolean }
        onDraft?.({ kind: event === 'token_reset' ? 'reset' : 'delta', agent_id: d.agent_id, delta: d.delta ?? '', replay: !!d.replay })
      } else onEvent(data as RunEvent)
    }
  }
}
