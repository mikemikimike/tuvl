import { START, type GraphEdge, type WorkflowView } from './model'

export type Positions = Record<string, { x: number; y: number }>

const COL = 300
const ROW = 190

/** Left-to-right layers by distance from Start; side agents (loop tools,
 * compensators) sit under the agent that uses them. Saved positions win. */
export function layout(view: WorkflowView, edges: GraphEdge[], saved: Positions = {}): Positions {
  const depth: Record<string, number> = { [START]: 0 }
  const queue = [START]
  const routes = edges.filter((e) => e.kind === 'route' || e.kind === 'entry')
  while (queue.length) {
    const node = queue.shift()!
    for (const e of routes.filter((r) => r.source === node && !r.target.startsWith('END.'))) {
      if (depth[e.target] === undefined) {
        depth[e.target] = depth[node] + 1
        queue.push(e.target)
      }
    }
  }
  const spine = view.agents.filter((a) => a.role === 'spine')
  let last = 0
  for (const a of spine) {
    if (depth[a.id] === undefined) depth[a.id] = 1 // unreachable: still drawn, flagged by validation
    last = Math.max(last, depth[a.id])
  }
  const out: Positions = { [START]: { x: 0, y: 0 } }
  const rows: Record<number, number> = {}
  for (const a of spine) {
    const d = depth[a.id]
    rows[d] = (rows[d] ?? 0) + 1
    out[a.id] = { x: d * COL, y: (rows[d] - 1) * ROW }
  }
  const below: Record<string, number> = {}
  for (const e of edges.filter((x) => x.kind === 'tool' || x.kind === 'compensate')) {
    const parent = out[e.source]
    if (!parent || out[e.target]) continue
    below[e.source] = (below[e.source] ?? 0) + 1
    out[e.target] = { x: parent.x + 40, y: parent.y + below[e.source] * ROW * 0.85 + 40 }
  }
  for (const a of view.agents) if (!out[a.id]) out[a.id] = { x: COL, y: Object.keys(out).length * 40 }
  Object.keys(view.ends).forEach((name, i) => { out[`END.${name}`] = { x: (last + 1) * COL, y: i * 110 } })
  for (const [id, p] of Object.entries(saved)) if (out[id]) out[id] = p
  return out
}
