import type { TaskStatus } from '../devApi'

export type NodeState = 'done' | 'running' | 'failed' | 'blocked' | 'ready' | 'in_progress'

export interface GraphNode {
  task: TaskStatus
  state: NodeState
  /** execution order: 0 runs first; tasks on one level do not depend on each other */
  level: number
  slot: number
}

export interface GraphEdge {
  from: string
  to: string
}

/** What a task looks like on the graph: a running or failed agent wins, then done, blocked, started, ready. */
export function nodeState(t: TaskStatus): NodeState {
  const live = t.live?.state
  if (live === 'running' || live === 'in_review') return 'running'
  if (live === 'failed') return 'failed'
  if (t.status === 'done') return 'done'
  if (t.blocked) return 'blocked'
  if (t.status === 'in_progress' || t.status === 'implemented' || t.status === 'tested') return 'in_progress'
  return 'ready'
}

/** Levels are the execution order: a task sits one level below the deepest task it waits for; tasks that do not depend on each other share a level. */
export function layoutGraph(tasks: TaskStatus[]): { nodes: GraphNode[]; edges: GraphEdge[]; levels: number; width: number } {
  const live = tasks.filter((t) => !t.obsolete)
  const byId = new Map(live.map((t) => [t.id, t]))
  const depth = new Map<string, number>()
  const visit = (id: string, seen: Set<string>): number => {
    const known = depth.get(id)
    if (known !== undefined) return known
    if (seen.has(id)) return 0
    seen.add(id)
    const parents = (byId.get(id)?.depends_on ?? []).filter((d) => byId.has(d))
    const d = parents.length === 0 ? 0 : 1 + Math.max(...parents.map((p) => visit(p, seen)))
    seen.delete(id)
    depth.set(id, d)
    return d
  }
  const perLevel = new Map<number, number>()
  const nodes = live.map((task): GraphNode => {
    const level = visit(task.id, new Set())
    const slot = perLevel.get(level) ?? 0
    perLevel.set(level, slot + 1)
    return { task, state: nodeState(task), level, slot }
  })
  // an edge already implied by a longer path is not drawn: a -> c when a -> b -> c
  const dependsOn = (task: string, target: string, seen = new Set<string>()): boolean => {
    if (seen.has(task)) return false
    seen.add(task)
    return (byId.get(task)?.depends_on ?? []).some((d) => byId.has(d) && (d === target || dependsOn(d, target, seen)))
  }
  const edges = live.flatMap((t) =>
    (t.depends_on ?? [])
      .filter((d) => byId.has(d))
      .filter((d) => !(t.depends_on ?? []).some((o) => o !== d && byId.has(o) && dependsOn(o, d)))
      .map((d) => ({ from: d, to: t.id })),
  )
  return { nodes, edges, levels: Math.max(0, ...nodes.map((n) => n.level + 1)), width: Math.max(0, ...perLevel.values()) }
}
