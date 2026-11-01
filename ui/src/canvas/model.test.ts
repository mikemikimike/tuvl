import { describe, expect, it } from 'vitest'
import { accessSummary, addAgent, isVectorStep, apiOn, fileInputs, setApiEnabled, setSchedule, addEnd, changeEngine, determinism, parseWorkflow, PRESETS, removeAgent, renameAgent, setField, setRoute, setWorkflowField, toGraph } from './model'

const WF = `# the refund flow
kind: Workflow
version: tuvl/v2
metadata: { name: refund, description: Refunds }
spec:
  trigger:
    http: { path: /refunds, method: POST }
    input: { order_id: uuid, note: { type: "str?", description: free text } }
  agents:
    - id: load
      description: Load the order
      engine: tool
      tool: { use: db, model: Order, op: read, where: { id: "{{ order_id }}" } }
      inputs: { order_id: uuid }
      outputs: { order: Order }
      compensate: undo
      routes: { default: dig, not_found: END.missing, error: END.failed }   # keep me
    - id: dig
      description: Investigate
      engine: loop
      loop: { model: default, steering: Find it, tools: [{ agent: lookup }] }
      routes: { done: END, error: END.failed }
    - id: lookup
      description: Look something up
      engine: code
      effect: read
      code: { run: lookup }
      routes: { default: END }
    - id: undo
      description: Undo the load
      engine: pending
      routes: { default: END }
  outputs:
    missing: { status: 404 }
    failed: { status: 500 }
`

describe('parseWorkflow', () => {
  it('reads agents, roles, ends and long-form types', () => {
    const p = parseWorkflow(WF)
    if (!p.ok) throw new Error(p.error)
    const v = p.view
    expect(v.name).toBe('refund')
    expect(v.trigger.input).toEqual({ order_id: 'uuid', note: 'str?' })
    expect(v.agents.map((a) => [a.id, a.role])).toEqual([['load', 'spine'], ['dig', 'spine'], ['lookup', 'tool'], ['undo', 'compensator']])
    expect(v.entry).toBe('load')
    expect(Object.keys(v.ends)).toEqual(['default', 'missing', 'failed'])
    expect(determinism(v.agents[0])).toBe('deterministic')
    expect(determinism(v.agents[1])).toBe('bounded')
  })

  it('reports YAML errors and wrong kinds', () => {
    expect(parseWorkflow('a: [').ok).toBe(false)
    expect(parseWorkflow('kind: Test\n').ok).toBe(false)
  })
})

describe('toGraph', () => {
  it('draws entry, routes per signal, tool and compensate edges', () => {
    const p = parseWorkflow(WF)
    if (!p.ok) throw new Error(p.error)
    const { nodes, edges } = toGraph(p.view)
    expect(nodes).toContain('END.default')
    expect(edges.map((e) => `${e.source}-${e.sourceHandle}->${e.target}:${e.kind}`)).toEqual([
      '__start-out->load:entry',
      'load-default->dig:route',
      'load-not_found->END.missing:route',
      'load-error->END.failed:route',
      'load-__tools->undo:compensate',
      'dig-done->END.default:route',
      'dig-error->END.failed:route',
      'dig-__tools->lookup:tool',
      'lookup-default->END.default:route',
      'undo-default->END.default:route',
    ])
  })
})

describe('edits keep the YAML (comments included)', () => {
  it('sets routes and fields, adds agents and their ends', () => {
    let t = setRoute(WF, 'load', 'not_found', 'END.failed')
    expect(t).toContain('# keep me')
    expect(t).toContain('# the refund flow')
    t = setField(t, 'dig', ['budget', 'max_iterations'], 5)
    const preset = PRESETS.find((x) => x.key === 'human')!
    t = addAgent(t, preset.make('review'))
    const p = parseWorkflow(t)
    if (!p.ok) throw new Error(p.error)
    expect(p.view.agents.find((a) => a.id === 'load')!.routes.not_found).toBe('END.failed')
    expect((p.view.agents.find((a) => a.id === 'dig')!.raw.budget as Record<string, number>).max_iterations).toBe(5)
    expect(p.view.ends.rejected).toEqual({ status: undefined })
    expect(() => addAgent(t, preset.make('review'))).toThrow(/already exists/)
    expect(setField(t, 'dig', ['budget'], undefined)).not.toContain('max_iterations')
  })

  it('offers a map step that parses as a map agent', () => {
    const preset = PRESETS.find((x) => x.key === 'map')!
    const p = parseWorkflow(addAgent(WF, preset.make('each')))
    if (!p.ok) throw new Error(p.error)
    const agent = p.view.agents.find((a) => a.id === 'each')!
    expect(agent.engine).toBe('map')
    expect(determinism(agent)).toBe('deterministic')
    expect((agent.raw.map as Record<string, unknown>).concurrency).toBe(4)
    expect(parseWorkflow(changeEngine(addAgent(WF, preset.make('each')), 'each', 'code')).ok).toBe(true)
  })

  it('adds retrieve-and-answer as a search step routed into an answering step', () => {
    const preset = PRESETS.find((x) => x.key === 'rag')!
    let t = addAgent(WF, preset.make('ask'))
    for (const more of preset.also!('ask')) t = addAgent(t, more)
    const p = parseWorkflow(t)
    if (!p.ok) throw new Error(p.error)
    const search = p.view.agents.find((a) => a.id === 'ask')!
    const answer = p.view.agents.find((a) => a.id === 'ask_answer')!
    expect(isVectorStep(search)).toBe(true)
    expect(search.routes.default).toBe('ask_answer')
    expect(answer.engine).toBe('llm')
    expect(Object.keys(answer.raw.inputs as object)).toEqual(['question', 'passages'])
    expect(isVectorStep(answer)).toBe(false)
  })

  it('gives the search and ingest steps a collection to fill in', () => {
    for (const key of ['search', 'ingest']) {
      const step = PRESETS.find((x) => x.key === key)!.make('s')
      expect(isVectorStep({ engine: 'code', raw: step })).toBe(true)
      expect((step.code as { with: Record<string, unknown> }).with.collection).toBeTruthy()
    }
  })

  it('offers a parallel step that parses, takes the strongest branch\'s class, and survives an engine change', () => {
    const preset = PRESETS.find((x) => x.key === 'parallel')!
    const p = parseWorkflow(addAgent(WF, preset.make('gather')))
    if (!p.ok) throw new Error(p.error)
    const agent = p.view.agents.find((a) => a.id === 'gather')!
    expect(agent.engine).toBe('parallel')
    expect(determinism(agent)).toBe('external') // http branches reach outside
    const llm = { ...agent, raw: { ...agent.raw, parallel: { branches: [{ engine: 'code' }, { engine: 'llm' }] } } }
    expect(determinism(llm)).toBe('bounded')
    expect(parseWorkflow(changeEngine(addAgent(WF, preset.make('gather')), 'gather', 'code')).ok).toBe(true)
  })

  it('removes an agent with the routes into it, and renames everywhere', () => {
    const removed = parseWorkflow(removeAgent(WF, 'dig'))
    if (!removed.ok) throw new Error(removed.error)
    expect(removed.view.agents.find((a) => a.id === 'load')!.routes).toEqual({ not_found: 'END.missing', error: 'END.failed' })
    const renamed = parseWorkflow(renameAgent(WF, 'lookup', 'find'))
    if (!renamed.ok) throw new Error(renamed.error)
    expect((renamed.view.agents[1].raw.loop as { tools: { agent: string }[] }).tools[0].agent).toBe('find')
    expect(renamed.view.agents.map((a) => a.id)).toContain('find')
    expect(() => renameAgent(WF, 'lookup', 'Bad Name')).toThrow()
    const ended = parseWorkflow(addEnd(WF, 'queued', 202))
    expect(ended.ok && ended.view.ends.queued).toEqual({ status: 202 })
  })

  it('changes the engine, keeping the contract and dropping keys the new engine rejects', () => {
    const swapped = parseWorkflow(changeEngine(WF, 'lookup', 'decide'))
    if (!swapped.ok) throw new Error(swapped.error)
    const raw = swapped.view.agents.find((a) => a.id === 'lookup')!.raw
    expect(raw.engine).toBe('decide')
    expect(raw.code).toBeUndefined()
    expect(raw.effect).toBeUndefined()
    expect(raw.description).toBe('Look something up')
    const lanes = changeEngine(WF.replace('routes: { default: dig, not_found', 'routes: { fast: dig, slow: END, not_found'), 'load', 'decide')
    const laned = parseWorkflow(lanes)
    if (!laned.ok) throw new Error(laned.error)
    const load = laned.view.agents.find((a) => a.id === 'load')!
    expect(load.raw.outputs).toEqual({ order: 'Order' })  // an existing contract is kept
    const bare = parseWorkflow(changeEngine(WF.replace('      outputs: { order: Order }\n', '').replace('routes: { default: dig, not_found', 'routes: { fast: dig, slow: END, not_found'), 'load', 'decide'))
    if (!bare.ok) throw new Error(bare.error)
    const lane = bare.view.agents.find((a) => a.id === 'load')!
    expect(lane.raw.outputs).toEqual({ lane: 'enum[fast, slow, not_found]' })
    expect(Object.keys(lane.routes)).toEqual(['fast', 'slow', 'not_found', 'error'])

    // a pending agent: the preset's lanes, and its default target moves to the first lane
    const decided = parseWorkflow(changeEngine(WF, 'undo', 'decide'))
    if (!decided.ok) throw new Error(decided.error)
    const undo = decided.view.agents.find((a) => a.id === 'undo')!
    expect(undo.raw.outputs).toEqual({ lane: 'enum[a, b]' })
    expect(undo.routes).toEqual({ a: 'END', b: 'END', error: 'END.failed' })
  })
})

describe('workflow access', () => {
  it('reads who may start a workflow, and edits keep the rest', () => {
    const open = parseWorkflow(WF)
    if (!open.ok) throw new Error(open.error)
    expect(open.view.access).toEqual({ requiredGroup: null, requiredScope: null, public: false })
    const gated = setWorkflowField(WF, ['metadata', 'required_group'], 'cop_manager')
    const parsed = parseWorkflow(gated)
    if (!parsed.ok) throw new Error(parsed.error)
    expect(parsed.view.access.requiredGroup).toBe('cop_manager')
    expect(parsed.view.agents.map((a) => a.id)).toEqual(open.view.agents.map((a) => a.id))
    const cleared = parseWorkflow(setWorkflowField(gated, ['metadata', 'required_group'], undefined))
    if (!cleared.ok) throw new Error(cleared.error)
    expect(cleared.view.access.requiredGroup).toBeNull()
  })
})

describe('workflow group and access summary', () => {
  it('reads and edits metadata.group', () => {
    const none = parseWorkflow(WF)
    if (!none.ok) throw new Error(none.error)
    expect(none.view.group).toBeNull()
    const grouped = parseWorkflow(setWorkflowField(WF, ['metadata', 'group'], 'payments'))
    if (!grouped.ok) throw new Error(grouped.error)
    expect(grouped.view.group).toBe('payments')
    const cleared = parseWorkflow(setWorkflowField(setWorkflowField(WF, ['metadata', 'group'], 'payments'), ['metadata', 'group'], undefined))
    if (!cleared.ok) throw new Error(cleared.error)
    expect(cleared.view.group).toBeNull()
  })

  it('summarises who may start it', () => {
    expect(accessSummary({ requiredGroup: null, requiredScope: null, public: false })).toEqual({ kind: 'signed-in', label: 'any signed-in user' })
    expect(accessSummary({ requiredGroup: 'moderators', requiredScope: null, public: false })).toEqual({ kind: 'role', label: 'role: moderators' })
    expect(accessSummary({ requiredGroup: null, requiredScope: 'flags:write', public: false })).toEqual({ kind: 'scope', label: 'scope: flags:write' })
    expect(accessSummary({ requiredGroup: null, requiredScope: null, public: true })).toEqual({ kind: 'public', label: 'public' })
  })
})

describe('triggers', () => {
  const view = (text: string) => {
    const r = parseWorkflow(text)
    if (!r.ok) throw new Error('parse')
    return r.view
  }

  it('reads the cron shorthand and the object form', () => {
    expect(view(WF.replace('input: { order_id', 'schedule: "0 9 * * *"\n    input: { order_id')).trigger.schedule).toEqual({ cron: '0 9 * * *', enabled: true, input: {} })
    const full = WF.replace('input: { order_id', 'schedule: { cron: "5 4 * * *", enabled: false, input: { note: hi } }\n    input: { order_id')
    expect(view(full).trigger.schedule).toEqual({ cron: '5 4 * * *', enabled: false, input: { note: 'hi' } })
  })

  it('switches the API off and on without losing its settings', () => {
    const off = setApiEnabled(WF, false, '/x')
    expect(off).toContain('enabled: false')
    expect(apiOn(view(off).trigger)).toBe(false)
    expect(view(off).trigger.http?.path).toBe('/refunds')
    const on = setApiEnabled(off, true, '/x')
    expect(on).not.toContain('enabled')
    expect(apiOn(view(on).trigger)).toBe(true)
  })

  it('creates an API trigger when there is none', () => {
    const none = WF.replace('    http: { path: /refunds, method: POST }\n', '')
    expect(view(setApiEnabled(none, true, '/refund-flow')).trigger.http).toEqual({ path: '/refund-flow', method: 'POST' })
  })

  it('turns a cron string into the object form when its input is edited, keeping comments', () => {
    const text = WF.replace('input: { order_id', 'schedule: "0 9 * * *"\n    input: { order_id')
    const out = setSchedule(text, { input: { note: 'daily' } })
    expect(view(out).trigger.schedule).toEqual({ cron: '0 9 * * *', enabled: true, input: { note: 'daily' } })
    expect(out).toContain('# the refund flow')
  })

  it('pauses a schedule and clears its input', () => {
    const text = setSchedule(WF, { cron: '0 9 * * *', enabled: true, input: { note: 'x' } })
    const paused = setSchedule(text, { enabled: false })
    expect(view(paused).trigger.schedule?.enabled).toBe(false)
    expect(view(paused).trigger.schedule?.input).toEqual({ note: 'x' })
    expect(view(setSchedule(paused, { input: {} })).trigger.schedule?.input).toEqual({})
  })
})

describe('file inputs', () => {
  it('finds file and list[file] inputs, optional or not', () => {
    expect(fileInputs({ a: 'file', b: 'list[file]?', c: 'str', d: 'file?', e: 'list[str]' })).toEqual([['a', false], ['b', true], ['d', false]])
  })
})
