import type { Draft, RunEvent } from '../runsApi'

/** Events grouped under the agent step they belong to, in order. */
export interface Step {
  agent: string | null
  engine: string | null
  events: RunEvent[]
  completed?: RunEvent
}

/** The live draft of each agent's answer: the whole draft on a replay, the next piece otherwise, nothing after a reset. */
export function applyDraft(drafts: Record<string, string>, d: Draft): Record<string, string> {
  if (d.kind === 'reset') return without(drafts, d.agent_id)
  return { ...drafts, [d.agent_id]: d.replay ? d.delta : (drafts[d.agent_id] ?? '') + d.delta }
}

/** A finished agent no longer shows a draft: its result is in the journal. */
export function dropFinished(drafts: Record<string, string>, e: RunEvent): Record<string, string> {
  if (e.type !== 'agent_completed' || !e.agent_id || !(e.agent_id in drafts)) return drafts
  return without(drafts, e.agent_id)
}

const without = (drafts: Record<string, string>, agent: string) =>
  Object.fromEntries(Object.entries(drafts).filter(([id]) => id !== agent))

export function groupSteps(events: RunEvent[]): Step[] {
  const steps: Step[] = []
  for (const e of events) {
    const last = steps[steps.length - 1]
    const afterStep = !!last?.completed && (e.agent_id == null || e.agent_id !== last.agent)
    if (e.type === 'agent_started' || !last || afterStep) {
      steps.push({ agent: e.agent_id, engine: e.engine, events: [e] })
    } else {
      last.events.push(e)
    }
    if (e.type === 'agent_completed') steps[steps.length - 1].completed = e
  }
  return steps
}
