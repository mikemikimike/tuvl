import { describe, expect, it } from 'vitest'
import { issuesByAgent } from '../overlays/issues'
import type { AgentView } from './model'
import { outletsOf, requiredSignals } from './outlets'

const agent = (over: Partial<AgentView>): AgentView => ({
  id: 'a', index: 0, engine: 'code', description: '', inputs: {}, outputs: {}, signalOutputs: null, routes: {}, raw: {}, role: 'spine', ...over,
})

describe('outlets', () => {
  it('lists required signals per engine, unrouted ones last', () => {
    expect(requiredSignals(agent({ engine: 'llm' }))).toEqual(['parse_error', 'timeout', 'budget_exceeded'])
    const decide = agent({ engine: 'decide', outputs: { lane: 'enum[fast, slow]' }, raw: { decide: { rules: [], model: { ref: 'm' } } } })
    expect(requiredSignals(decide)).toEqual(['fast', 'slow', 'low_confidence'])
    const shadow = agent({ engine: 'decide', outputs: { lane: 'enum[x]' }, raw: { decide: { model: { ref: 'm' }, shadow: true } } })
    expect(requiredSignals(shadow)).toEqual(['x'])
    const human = agent({ engine: 'human', outputs: { ok: 'bool' }, raw: { human: { route_on: 'ok', expires: '4h' } } })
    expect(requiredSignals(human)).toEqual(['true', 'false', 'expired'])
    const read = agent({ engine: 'tool', raw: { tool: { use: 'db', op: 'read' }, guardrails: { output: ['artifact://g@1'] } }, routes: { default: 'END' } })
    expect(outletsOf(read)).toEqual(['default', 'not_found', 'guardrail_violation'])
  })

  it('asks for the signals a storage op can emit', () => {
    const op = (tool: Record<string, unknown>) => agent({ engine: 'tool', raw: { tool: { use: 'storage', ...tool } } })
    expect(requiredSignals(op({ op: 'get' }))).toEqual(['not_found'])
    expect(requiredSignals(op({ op: 'put' }))).toEqual(['conflict'])
    expect(requiredSignals(op({ op: 'put', if_exists: 'overwrite' }))).toEqual([])
    expect(requiredSignals(op({ op: 'copy' }))).toEqual(['not_found', 'conflict'])
    expect(requiredSignals(op({ op: 'delete' }))).toEqual([])
  })
})

describe('issuesByAgent', () => {
  it('files issues under their agent and reads missing inputs from V006', () => {
    const { agents, workflow } = issuesByAgent({
      valid: false,
      profiles: {},
      errors: [
        { severity: 'error', file: 'workflows/w.yaml:12', line: 12, code: 'V006', message: "[V006] spec.agents[b].inputs.order: input 'order' is not produced" },
        { severity: 'error', file: 'workflows/other.yaml', line: null, code: 'V003', message: '[V003] spec.agents[b].routes.x: nope' },
      ],
      warnings: [{ severity: 'warning', file: 'workflows/w.yaml', line: null, code: 'V020', message: '[V020] spec.policy: too many tokens' }],
    }, 'w.yaml')
    expect(agents.b.errors).toBe(1)
    expect(agents.b.missingInputs).toEqual(['order'])
    expect(workflow.map((w) => w.code)).toEqual(['V020'])
  })
})
