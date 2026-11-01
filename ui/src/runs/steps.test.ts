import { describe, expect, it } from 'vitest'
import { parseSse, parseSseFrames, type Draft, type RunEvent } from '../runsApi'
import { applyDraft, dropFinished, groupSteps } from './steps'

const ev = (seq: number, type: string, agent_id: string | null = null, payload: Record<string, unknown> = {}): RunEvent => ({
  run_id: 'r', seq, ts: '', type, agent_id, engine: agent_id ? 'loop' : null, tokens: null, latency_ms: null, payload,
})

describe('groupSteps', () => {
  it('nests each agent’s events under it and keeps run events apart', () => {
    const steps = groupSteps([
      ev(1, 'run_started'),
      ev(2, 'agent_started', 'dig'),
      ev(3, 'llm_turn', 'dig', { iteration: 1 }),
      ev(4, 'tool_call', 'dig', { tool: 'lookup' }),
      ev(5, 'agent_completed', 'dig', { signal: 'resolved' }),
      ev(6, 'agent_started', 'store'),
      ev(7, 'agent_completed', 'store', { signal: 'default' }),
      ev(8, 'run_completed', null, { end: 'default' }),
    ])
    expect(steps.map((s) => s.agent)).toEqual([null, 'dig', 'store', null])
    expect(steps[1].events.map((e) => e.type)).toEqual(['agent_started', 'llm_turn', 'tool_call', 'agent_completed'])
    expect(steps[1].completed?.payload.signal).toBe('resolved')
  })
})

describe('parseSse', () => {
  it('returns whole events and keeps the partial tail', () => {
    const a = JSON.stringify(ev(1, 'run_queued'))
    const b = JSON.stringify(ev(2, 'run_started'))
    const { events, rest } = parseSse(`id: 1\nevent: run_queued\ndata: ${a}\n\n: keep-alive\n\nid: 2\ndata: ${b.slice(0, 10)}`)
    expect(events.map((e) => e.seq)).toEqual([1])
    expect(rest).toBe(`id: 2\ndata: ${b.slice(0, 10)}`)
  })
})

describe('live drafts', () => {
  const delta = (agent_id: string, text: string, replay = false): Draft => ({ kind: 'delta', agent_id, delta: text, replay })
  const reset = (agent_id: string): Draft => ({ kind: 'reset', agent_id, delta: '', replay: false })

  it('appends pieces, replaces on a replay, and drops on a reset', () => {
    let d: Record<string, string> = {}
    d = applyDraft(d, delta('write', 'Hel'))
    d = applyDraft(d, delta('write', 'lo'))
    expect(d).toEqual({ write: 'Hello' })
    d = applyDraft(d, delta('write', 'Hello wor', true)) // a reconnect: the draft so far, not a continuation
    expect(d.write).toBe('Hello wor')
    d = applyDraft(d, delta('other', 'x'))
    expect(applyDraft(d, reset('write'))).toEqual({ other: 'x' })
  })

  it('does not change the object it is given', () => {
    const before = { a: 'x' }
    applyDraft(before, delta('a', 'y'))
    applyDraft(before, reset('a'))
    expect(before).toEqual({ a: 'x' })
  })

  it('a finished agent no longer shows a draft', () => {
    const drafts = { write: 'text', other: 'more' }
    expect(dropFinished(drafts, ev(5, 'agent_completed', 'write'))).toEqual({ other: 'more' })
    expect(dropFinished(drafts, ev(6, 'agent_started', 'write'))).toBe(drafts)
    expect(dropFinished(drafts, ev(7, 'agent_completed', 'nobody'))).toBe(drafts)
  })

  it('parseSse leaves drafts out of the journal, parseSseFrames keeps them with their names', () => {
    const a = JSON.stringify(ev(1, 'agent_started', 'write'))
    const d = JSON.stringify({ run_id: 'r', agent_id: 'write', delta: 'Hi', replay: false })
    const text = `id: 1\nevent: agent_started\ndata: ${a}\n\nevent: token_delta\ndata: ${d}\n\nevent: token_reset\ndata: {"agent_id":"write"}\n\n`
    expect(parseSse(text).events.map((e) => e.type)).toEqual(['agent_started'])
    expect(parseSseFrames(text).frames.map((f) => f.event)).toEqual(['agent_started', 'token_delta', 'token_reset'])
  })
})
