// The workflow YAML is the single source: the canvas reads a view of it and
// edits it through `yaml` Documents, so comments and flow style survive.
import { isMap, isSeq, parseDocument, type Document } from 'yaml'

export type Engine = 'pending' | 'code' | 'tool' | 'decide' | 'llm' | 'loop' | 'human' | 'map' | 'parallel'
export type Determinism = 'deterministic' | 'bounded' | 'external' | 'pending'

export interface AgentView {
  id: string
  index: number
  engine: Engine
  description: string
  inputs: Record<string, string>
  outputs: Record<string, string>
  /** `outputs: { <signal>: { field: type } }` — the fields each signal carries (null: one map for all) */
  signalOutputs: Record<string, Record<string, string>> | null
  routes: Record<string, string>
  /** The agent as plain data (engine block, budget, guardrails, …). */
  raw: Record<string, unknown>
  /** Loop tools and compensators sit beside the flow, not on it. */
  role: 'spine' | 'tool' | 'compensator'
}

export interface UploadView { store?: string; prefix?: string; max_bytes?: number; max_files?: number; accept?: string[] }
export interface HttpTriggerView { path?: string; method?: string; public?: boolean; enabled?: boolean; upload?: UploadView }

/** Inputs typed `file` or `list[file]`, with whether they take several. */
export function fileInputs(input: Record<string, string>): [string, boolean][] {
  return Object.entries(input)
    .filter(([, t]) => /^(file|list\[file\])\??$/.test(t.trim()))
    .map(([k, t]) => [k, t.includes('list')])
}

/** `trigger.schedule`: a cron string, or `{cron, enabled, input}`. */
export interface ScheduleView { cron: string; enabled: boolean; input: Record<string, unknown> }

export const apiOn = (t: WorkflowView['trigger']) => !!t.http && t.http.enabled !== false

export interface WorkflowView {
  name: string
  description: string
  /** `metadata.group`: how the workflow picker groups it */
  group: string | null
  trigger: { http?: HttpTriggerView; schedule?: ScheduleView; tenants: string[]; input: Record<string, string> }
  /** who may start it: `metadata.required_group` (an IAM role) / `required_scope`, or `trigger.http.public` */
  access: { requiredGroup: string | null; requiredScope: string | null; public: boolean }
  agents: AgentView[]
  ends: Record<string, { status?: number }>
  entry: string | null
  models: string[]
}

/** One line for who may start a workflow: the badge on the START node and in the top bar. */
export function accessSummary(a: WorkflowView['access']): { kind: 'role' | 'scope' | 'public' | 'signed-in'; label: string } {
  if (a.requiredGroup) return { kind: 'role', label: `role: ${a.requiredGroup}` }
  if (a.requiredScope) return { kind: 'scope', label: `scope: ${a.requiredScope}` }
  if (a.public) return { kind: 'public', label: 'public' }
  return { kind: 'signed-in', label: 'any signed-in user' }
}

export type Parsed = { ok: true; doc: Document; view: WorkflowView } | { ok: false; error: string }

/** `str` or `{ type: str, description: … }` → `str`. */
function typeOf(spec: unknown): string {
  if (typeof spec === 'string') return spec
  if (spec && typeof spec === 'object' && 'type' in spec) return String((spec as { type: unknown }).type)
  return String(spec)
}

function fieldMap(value: unknown): Record<string, string> {
  if (!value || typeof value !== 'object') return {}
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, typeOf(v)]))
}

/** Per-signal outputs as the engine reads them: every value is a field map, not a long-form field. */
function signalOutputs(value: unknown): Record<string, Record<string, string>> | null {
  const entries = Object.entries(asRecord(value))
  const perSignal = entries.length > 0 && entries.every(([, v]) => v && typeof v === 'object' && !Array.isArray(v) && !('type' in (v as object)))
  return perSignal ? Object.fromEntries(entries.map(([signal, fields]) => [signal, fieldMap(fields)])) : null
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

export function determinism(agent: Pick<AgentView, 'engine' | 'raw'>): Determinism {
  switch (agent.engine) {
    case 'pending': return 'pending'
    case 'llm': case 'loop': return 'bounded'
    case 'tool': {
      const use = asRecord(agent.raw.tool).use
      return use === 'db' ? 'deterministic' : 'external'
    }
    case 'decide': return asRecord(agent.raw.decide).model ? 'bounded' : 'deterministic'
    case 'human': return 'external'
    case 'parallel': {
      const branches = asRecord(agent.raw.parallel).branches
      const list = Array.isArray(branches) ? branches.map(asRecord) : []
      const rank: Determinism[] = ['deterministic', 'bounded', 'external']
      return list.reduce<Determinism>((worst, b) => {
        const own = determinism({ engine: b.engine as Engine, raw: b })
        return rank.indexOf(own) > rank.indexOf(worst) ? own : worst
      }, 'deterministic')
    }
    default: return 'deterministic'
  }
}

export function parseWorkflow(text: string): Parsed {
  const doc = parseDocument(text)
  if (doc.errors.length) return { ok: false, error: doc.errors[0].message }
  const data = asRecord(doc.toJS())
  if (data.kind !== 'Workflow') return { ok: false, error: 'not a Workflow document' }
  const meta = asRecord(data.metadata)
  const spec = asRecord(data.spec)
  const rawAgents = Array.isArray(spec.agents) ? (spec.agents as Record<string, unknown>[]) : []
  const tools = new Set<string>()
  const compensators = new Set<string>()
  for (const a of rawAgents) {
    for (const t of (asRecord(a.loop).tools as Record<string, unknown>[] | undefined) ?? []) {
      if (typeof t?.agent === 'string') tools.add(t.agent)
    }
    if (typeof a.compensate === 'string') compensators.add(a.compensate)
  }
  const agents: AgentView[] = rawAgents.map((a, index) => {
    const id = String(a.id ?? `agent_${index}`)
    return {
      id,
      index,
      engine: String(a.engine ?? 'pending') as Engine,
      description: String(a.description ?? ''),
      inputs: fieldMap(a.inputs),
      outputs: signalOutputs(a.outputs) ? Object.assign({}, ...Object.values(signalOutputs(a.outputs)!)) : fieldMap(a.outputs),
      signalOutputs: signalOutputs(a.outputs),
      routes: Object.fromEntries(Object.entries(asRecord(a.routes)).map(([k, v]) => [String(k), String(v)])),
      raw: a,
      role: tools.has(id) ? 'tool' : compensators.has(id) ? 'compensator' : 'spine',
    }
  })
  const trigger = asRecord(spec.trigger)
  const outputs = asRecord(spec.outputs)
  const ends: WorkflowView['ends'] = { default: {} }
  for (const [name, end] of Object.entries(outputs)) ends[name] = { status: asRecord(end).status as number | undefined }
  const start = typeof spec.start === 'string' ? spec.start : null
  return {
    ok: true,
    doc,
    view: {
      name: String(meta.name ?? ''),
      description: String(meta.description ?? ''),
      group: typeof meta.group === 'string' && meta.group.trim() ? meta.group.trim() : null,
      trigger: {
        http: trigger.http ? (asRecord(trigger.http) as HttpTriggerView) : undefined,
        schedule: scheduleView(trigger.schedule),
        tenants: Array.isArray(trigger.tenants) ? trigger.tenants.map(String) : [],
        input: fieldMap(trigger.input),
      },
      access: {
        requiredGroup: typeof meta.required_group === 'string' ? meta.required_group : null,
        requiredScope: typeof meta.required_scope === 'string' ? meta.required_scope : null,
        public: asRecord(trigger.http).public === true,
      },
      agents,
      ends,
      entry: start ?? agents.find((a) => a.role === 'spine')?.id ?? null,
      models: Array.isArray(spec.models) ? (spec.models as unknown[]).map(String) : [],
    },
  }
}

// ── graph ────────────────────────────────────────────────────────────────────

export const START = '__start'
export const endNode = (target: string) => (target === 'END' ? 'END.default' : target)

export interface GraphEdge {
  id: string
  source: string
  sourceHandle: string
  target: string
  label: string
  kind: 'route' | 'entry' | 'tool' | 'compensate'
}

export function toGraph(view: WorkflowView): { nodes: string[]; edges: GraphEdge[] } {
  const ids = new Set(view.agents.map((a) => a.id))
  const nodes = [START, ...view.agents.map((a) => a.id), ...Object.keys(view.ends).map((e) => `END.${e}`)]
  const edges: GraphEdge[] = []
  if (view.entry) edges.push({ id: 'entry', source: START, sourceHandle: 'out', target: view.entry, label: '', kind: 'entry' })
  for (const a of view.agents) {
    for (const [signal, target] of Object.entries(a.routes)) {
      const to = target.startsWith('END') ? endNode(target) : target
      if (!ids.has(to) && !to.startsWith('END.')) continue
      edges.push({ id: `${a.id}:${signal}`, source: a.id, sourceHandle: signal, target: to, label: signal, kind: 'route' })
    }
    for (const t of (asRecord(a.raw.loop).tools as Record<string, unknown>[] | undefined) ?? []) {
      if (typeof t?.agent === 'string' && ids.has(t.agent)) {
        edges.push({ id: `${a.id}~tool~${t.agent}`, source: a.id, sourceHandle: '__tools', target: t.agent, label: 'tool', kind: 'tool' })
      }
    }
    if (typeof a.raw.compensate === 'string' && ids.has(a.raw.compensate)) {
      edges.push({ id: `${a.id}~comp`, source: a.id, sourceHandle: '__tools', target: a.raw.compensate, label: 'compensate', kind: 'compensate' })
    }
  }
  return { nodes, edges }
}

// ── edits (text in, text out) ───────────────────────────────────────────────

type Path = (string | number)[]

function withDoc(text: string, change: (doc: Document) => void): string {
  const doc = parseDocument(text)
  if (doc.errors.length) throw new Error(doc.errors[0].message)
  change(doc)
  return doc.toString({ lineWidth: 0 })
}

function agentIndex(doc: Document, id: string): number {
  const agents = doc.getIn(['spec', 'agents'])
  if (!isSeq(agents)) throw new Error('spec.agents is not a list')
  const index = agents.items.findIndex((item) => isMap(item) && item.get('id') === id)
  if (index < 0) throw new Error(`no agent '${id}'`)
  return index
}

export function setField(text: string, agentId: string, path: Path, value: unknown): string {
  return withDoc(text, (doc) => {
    const at = ['spec', 'agents', agentIndex(doc, agentId), ...path]
    if (value === undefined || value === null || value === '') doc.deleteIn(at)
    else doc.setIn(at, value)
  })
}

/** Throws when `value` cannot replace agent `agentId`: an agent is a mapping, and its id stays (routes point at it). */
export function checkAgent(agentId: string, value: unknown): void {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('An agent is a mapping: id, engine, inputs, outputs and so on.')
  if ((value as Record<string, unknown>).id !== agentId) throw new Error(`The id stays '${agentId}' here; routes and tests point at it.`)
}

/** Replace one agent with `value` (its whole mapping), keeping its place in the list. */
export function replaceAgent(text: string, agentId: string, value: unknown): string {
  checkAgent(agentId, value)
  return withDoc(text, (doc) => {
    doc.setIn(['spec', 'agents', agentIndex(doc, agentId)], doc.createNode(value))
  })
}

export function setWorkflowField(text: string, path: Path, value: unknown): string {
  return withDoc(text, (doc) => {
    if (value === undefined || value === null || value === '') doc.deleteIn(path)
    else doc.setIn(path, value)
  })
}

function scheduleView(raw: unknown): ScheduleView | undefined {
  if (typeof raw === 'string') return { cron: raw, enabled: true, input: {} }
  if (!raw || typeof raw !== 'object') return undefined
  const s = asRecord(raw)
  return { cron: typeof s.cron === 'string' ? s.cron : '', enabled: s.enabled !== false, input: asRecord(s.input) }
}

/** Switch the API trigger on or off without losing its path, method or access settings. */
export function setApiEnabled(text: string, enabled: boolean, defaultPath: string): string {
  return withDoc(text, (doc) => {
    const at = ['spec', 'trigger', 'http']
    if (!doc.hasIn(at)) {
      if (enabled) doc.setIn(at, { path: defaultPath, method: 'POST' })
      return
    }
    if (enabled) doc.deleteIn([...at, 'enabled'])
    else doc.setIn([...at, 'enabled'], false)
  })
}

/** Change parts of `trigger.schedule`, turning the cron-string shorthand into the object form. */
export function setSchedule(text: string, patch: Partial<ScheduleView>): string {
  return withDoc(text, (doc) => {
    const at = ['spec', 'trigger', 'schedule']
    if (!isMap(doc.getIn(at))) {
      const current = doc.getIn(at)
      doc.setIn(at, doc.createNode({ cron: typeof current === 'string' ? current : '' }))
    }
    if (patch.cron !== undefined) doc.setIn([...at, 'cron'], patch.cron)
    if (patch.enabled !== undefined) {
      if (patch.enabled) doc.deleteIn([...at, 'enabled'])
      else doc.setIn([...at, 'enabled'], false)
    }
    if (patch.input !== undefined) {
      if (Object.keys(patch.input).length) doc.setIn([...at, 'input'], patch.input)
      else doc.deleteIn([...at, 'input'])
    }
  })
}

export function setRoute(text: string, agentId: string, signal: string, target: string | null): string {
  return setField(text, agentId, ['routes', signal], target ?? undefined)
}

function ensureEnds(doc: Document, targets: string[]): void {
  for (const t of targets) {
    if (!t.startsWith('END.')) continue
    const name = t.slice(4)
    if (!doc.hasIn(['spec', 'outputs', name])) doc.setIn(['spec', 'outputs', name], name === 'failed' ? { status: 500 } : {})
  }
}

export function addAgent(text: string, agent: Record<string, unknown>): string {
  return withDoc(text, (doc) => {
    if (!doc.hasIn(['spec', 'agents'])) doc.setIn(['spec', 'agents'], [])
    const agents = doc.getIn(['spec', 'agents'])
    if (isSeq(agents) && agents.items.some((i) => isMap(i) && i.get('id') === agent.id)) throw new Error(`agent '${String(agent.id)}' already exists`)
    doc.addIn(['spec', 'agents'], doc.createNode(agent))
    ensureEnds(doc, Object.values(asRecord(agent.routes)).map(String))
  })
}

export function removeAgent(text: string, id: string): string {
  return withDoc(text, (doc) => {
    const index = agentIndex(doc, id)
    doc.deleteIn(['spec', 'agents', index])
    const agents = doc.getIn(['spec', 'agents'])
    if (!isSeq(agents)) return
    agents.items.forEach((item, i) => {
      if (!isMap(item)) return
      const routes = item.get('routes')
      if (isMap(routes)) {
        for (const pair of [...routes.items]) {
          if (String((pair.value as { value?: unknown } | null)?.value ?? pair.value) === id) {
            doc.deleteIn(['spec', 'agents', i, 'routes', String((pair.key as { value?: unknown }).value ?? pair.key)])
          }
        }
      }
    })
    if (doc.getIn(['spec', 'start']) === id) doc.deleteIn(['spec', 'start'])
  })
}

export function renameAgent(text: string, from: string, to: string): string {
  if (!/^[a-z][a-z0-9_]*$/.test(to)) throw new Error('agent ids are snake_case')
  return withDoc(text, (doc) => {
    const view = parseWorkflow(text)
    if (!view.ok) throw new Error(view.error)
    if (view.view.agents.some((a) => a.id === to)) throw new Error(`agent '${to}' already exists`)
    for (const a of view.view.agents) {
      const at = ['spec', 'agents', a.index]
      if (a.id === from) doc.setIn([...at, 'id'], to)
      for (const [signal, target] of Object.entries(a.routes)) if (target === from) doc.setIn([...at, 'routes', signal], to)
      if (a.raw.compensate === from) doc.setIn([...at, 'compensate'], to)
      const tools = (asRecord(a.raw.loop).tools as Record<string, unknown>[] | undefined) ?? []
      tools.forEach((t, k) => { if (t?.agent === from) doc.setIn([...at, 'loop', 'tools', k, 'agent'], to) })
    }
    if (doc.getIn(['spec', 'start']) === from) doc.setIn(['spec', 'start'], to)
  })
}

export function addEnd(text: string, name: string, status: number): string {
  if (!/^[a-z][a-z0-9_]*$/.test(name)) throw new Error('end names are snake_case')
  return setWorkflowField(text, ['spec', 'outputs', name], status === 200 ? {} : { status })
}

/** a code step on the built-in vector search or ingest */
export const isVectorStep = (agent: Pick<AgentView, 'engine' | 'raw'>) => {
  const run = asRecord(agent.raw.code).run
  return agent.engine === 'code' && (run === 'tuvl.data_search' || run === 'tuvl.data_ingest')
}

// ── palette presets ─────────────────────────────────────────────────────────

export interface Preset {
  key: string
  label: string
  group: 'Deterministic · 0 LLM' | 'AI · bounded' | 'Control' | 'Contract only'
  hint: string
  make: (id: string) => Record<string, unknown>
  /** more steps the preset adds after the first (a pattern, not a single step); `make` routes into them */
  also?: (id: string) => Record<string, unknown>[]
}

const BASE = (id: string, engine: Engine, description: string) => ({ id, description, engine })
const LLM_ROUTES = { default: 'END', parse_error: 'END.failed', timeout: 'END.failed', budget_exceeded: 'END.failed', error: 'END.failed' }

export const PRESETS: Preset[] = [
  { key: 'code', label: 'Code', group: 'Deterministic · 0 LLM', hint: 'A Python function (@agent)',
    make: (id) => ({ ...BASE(id, 'code', 'Describe what this step does'), code: { run: id }, routes: { default: 'END', error: 'END.failed' } }) },
  { key: 'db', label: 'Database op', group: 'Deterministic · 0 LLM', hint: 'read / list / create / update / delete a model',
    make: (id) => ({ ...BASE(id, 'tool', 'Read a record'), tool: { use: 'db', model: 'Model', op: 'read', where: { id: '{{ id }}' } },
      inputs: { id: 'uuid' }, routes: { default: 'END', not_found: 'END.failed', error: 'END.failed' } }) },
  { key: 'http', label: 'HTTP call', group: 'Deterministic · 0 LLM', hint: 'Call an external API',
    make: (id) => ({ ...BASE(id, 'tool', 'Call an API'), tool: { use: 'http', method: 'GET', url: 'https://example.com' }, routes: { default: 'END', error: 'END.failed' } }) },
  { key: 'storage', label: 'Storage op', group: 'Deterministic · 0 LLM', hint: 'put / get / list / copy / delete an object, or presign a URL',
    make: (id) => ({ ...BASE(id, 'tool', 'Read an object'), tool: { use: 'storage', store: 'files', op: 'get', key: '{{ key }}' },
      inputs: { key: 'str' }, routes: { default: 'END', not_found: 'END.failed', error: 'END.failed' } }) },
  { key: 'mcp', label: 'MCP tool', group: 'Deterministic · 0 LLM', hint: 'One tool of an MCP server',
    make: (id) => ({ ...BASE(id, 'tool', 'Call an MCP tool'), tool: { use: 'mcp', server: 'artifact://server@1', name: 'tool' }, routes: { default: 'END', error: 'END.failed' } }) },
  { key: 'search', label: 'Vector search', group: 'Deterministic · 0 LLM', hint: 'Search a collection: tuvl.data_search',
    make: (id) => ({ ...BASE(id, 'code', 'Search the knowledge base'), effect: 'read',
      code: { run: 'tuvl.data_search', with: { collection: 'kb', query: '{{ query }}', top_k: 5 } }, inputs: { query: 'str' },
      outputs: { hits: 'list[json]' }, routes: { default: 'END', error: 'END.failed' } }) },
  { key: 'ingest', label: 'Vector ingest', group: 'Deterministic · 0 LLM', hint: 'Store a document in a collection: tuvl.data_ingest',
    make: (id) => ({ ...BASE(id, 'code', 'Ingest a document'),
      code: { run: 'tuvl.data_ingest', with: { collection: 'kb', document: '{{ content }}', metadata: { title: '{{ title }}' } } },
      inputs: { title: 'str', content: 'str' }, outputs: { doc_id: 'uuid' }, routes: { default: 'END', error: 'END.failed' } }) },
  { key: 'rag', label: 'Retrieve and answer', group: 'AI · bounded', hint: 'Search a collection, then answer from the passages and cite them',
    make: (id) => ({ ...BASE(id, 'code', 'Find the passages most relevant to the question'), effect: 'read',
      code: { run: 'tuvl.data_search', with: { collection: 'kb', query: '{{ question }}', top_k: 5 } }, inputs: { question: 'str' },
      outputs: { passages: 'list[json]' }, routes: { default: `${id}_answer`, error: 'END.failed' } }),
    also: (id) => [{ ...BASE(`${id}_answer`, 'llm', 'Answer strictly from the retrieved passages'),
      inputs: { question: 'str', passages: 'list[json]' }, outputs: { answer: 'str', sources: 'list[str]', confident: 'bool' },
      budget: { timeout: '30s', max_tokens: 1000 },
      llm: { model: 'default', system: 'Answer only from the passages. Never use outside knowledge. In `sources`, list the title of every passage you used. If the passages do not contain the answer, say so and set confident to false.',
        prompt: 'Answer the question from the passages.' }, routes: LLM_ROUTES }] },
  { key: 'llm', label: 'LLM call', group: 'AI · bounded', hint: 'One model call with typed outputs',
    make: (id) => ({ ...BASE(id, 'llm', 'Classify or extract'), outputs: { label: 'str' }, budget: { timeout: '30s', max_tokens: 1000 },
      llm: { model: 'default', prompt: 'Describe the task.' }, routes: LLM_ROUTES }) },
  { key: 'loop', label: 'Autonomous loop', group: 'AI · bounded', hint: 'A model that investigates with tools',
    make: (id) => ({ ...BASE(id, 'loop', 'Investigate'), outputs: { answer: 'str' },
      budget: { max_iterations: 6, max_tokens: 20000, max_tool_calls: 6, timeout: '3m' },
      loop: { model: 'default', steering: 'Describe the goal and the rules.', tools: [] },
      routes: { done: 'END', max_iterations: 'END.failed', budget_exceeded: 'END.failed', timeout: 'END.failed', aborted: 'END.failed', error: 'END.failed' } }) },
  { key: 'decide', label: 'Decide', group: 'Control', hint: 'Rules first, a decision model if needed',
    make: (id) => ({ ...BASE(id, 'decide', 'Choose a lane'), outputs: { lane: 'enum[a, b]' },
      decide: { rules: [{ when: 'true', then: 'a' }] }, routes: { a: 'END', b: 'END', error: 'END.failed' } }) },
  { key: 'map', label: 'Map over a list', group: 'Control', hint: 'Run a workflow once for every item of a list, a few at a time',
    make: (id) => ({ ...BASE(id, 'map', 'Process every item'), inputs: { items: 'list[json]' }, outputs: { results: 'list[json]' },
      map: { over: 'items', workflow: 'child_workflow', as: 'item', concurrency: 4, max_items: 100 }, effect: 'write',
      routes: { default: 'END', error: 'END.failed' } }) },
  { key: 'parallel', label: 'Run lookups in parallel', group: 'Control', hint: 'Several different read-only lookups at the same time, joined into one step',
    make: (id) => ({ ...BASE(id, 'parallel', 'Look everything up at once'), inputs: { key: 'str' }, outputs: { first: 'json', second: 'json' },
      parallel: { on_error: 'fail', branches: [
        { id: 'first', engine: 'tool', inputs: { key: 'str' }, outputs: { first: 'json' }, tool: { use: 'http', method: 'GET', url: 'https://example.com/first/{{ key }}', map: { first: 'response.body' } } },
        { id: 'second', engine: 'tool', inputs: { key: 'str' }, outputs: { second: 'json' }, tool: { use: 'http', method: 'GET', url: 'https://example.com/second/{{ key }}', map: { second: 'response.body' } } },
      ] },
      routes: { default: 'END', error: 'END.failed' } }) },
  { key: 'human', label: 'Human approval', group: 'Control', hint: 'A person approves or reviews',
    make: (id) => ({ ...BASE(id, 'human', 'A person approves'), outputs: { approved: 'bool' },
      human: { title: 'Approve?', route_on: 'approved' }, routes: { true: 'END', false: 'END.rejected', error: 'END.failed' } }) },
  { key: 'pending', label: 'Pending agent', group: 'Contract only', hint: 'A typed contract, implemented later',
    make: (id) => ({ ...BASE(id, 'pending', 'What this agent will do'), routes: { default: 'END', error: 'END.failed' } }) },
]

const ENGINE_KEYS = ['code', 'tool', 'decide', 'llm', 'loop', 'human', 'map', 'parallel'] as const
const NO_DEFAULT = ['decide', 'human', 'loop']

/** Keep the contract (id, description, inputs, outputs, routes); swap the engine block for a preset's. */
export function changeEngine(text: string, id: string, presetKey: string): string {
  const preset = PRESETS.find((p) => p.key === presetKey)
  if (!preset) throw new Error(`unknown preset '${presetKey}'`)
  const fresh = preset.make(id)
  return withDoc(text, (doc) => {
    const at = ['spec', 'agents', agentIndex(doc, id)]
    const signals = Object.keys(asRecord(doc.toJS().spec.agents[at[2] as number].routes)).filter((s) => s !== 'default' && s !== 'error')
    if (preset.key === 'decide' && signals.length >= 2 && !doc.hasIn([...at, 'outputs'])) {
      // keep the agent's signals: the lanes become the decision enum
      fresh.outputs = { lane: `enum[${signals.join(', ')}]` }
      fresh.decide = { rules: [{ when: 'true', then: signals[0] }] }
      fresh.routes = {}
      doc.setIn([...at, 'outputs'], doc.createNode(fresh.outputs))
    }
    for (const key of ENGINE_KEYS) doc.deleteIn([...at, key])
    if (fresh.engine !== 'code' && fresh.engine !== 'tool' && fresh.engine !== 'map') doc.deleteIn([...at, 'effect'])
    doc.setIn([...at, 'engine'], fresh.engine)
    for (const [key, value] of Object.entries(fresh)) {
      if ((ENGINE_KEYS as readonly string[]).includes(key) || key === 'budget') {
        if (key === 'budget' && doc.hasIn([...at, 'budget'])) continue
        doc.setIn([...at, key], doc.createNode(value))
      }
    }
    if (fresh.outputs && !doc.hasIn([...at, 'outputs'])) doc.setIn([...at, 'outputs'], doc.createNode(fresh.outputs))
    const routes = asRecord(fresh.routes)
    // decide, human and loop agents have no `default` signal: its target moves to the first new one
    const fallback = doc.getIn([...at, 'routes', 'default'])
    if (fallback !== undefined && NO_DEFAULT.includes(String(fresh.engine))) {
      doc.deleteIn([...at, 'routes', 'default'])
      const first = Object.keys(routes).find((sig) => sig !== 'error')
      if (first) routes[first] = fallback
    }
    for (const [signal, target] of Object.entries(routes)) {
      if (!doc.hasIn([...at, 'routes', signal]) && signal !== 'default') doc.setIn([...at, 'routes', signal], target)
    }
    ensureEnds(doc, Object.values(routes).map(String))
  })
}
