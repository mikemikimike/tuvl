import { useCallback, useMemo } from 'react'
import {
  Background, Controls, MarkerType, MiniMap, ReactFlow, ReactFlowProvider,
  type Connection, type Edge, type Node, type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { AgentCard, type AgentCardData } from '../cards/AgentCard'
import { EndNode, StartNode } from '../cards/StartEnd'
import type { AgentIssues } from '../overlays/issues'
import { layout, type Positions } from './layout'
import { setRoute, setWorkflowField, START, toGraph, type WorkflowView } from './model'
import { outletsOf } from './outlets'
import { useUIStore } from '../store'

const nodeTypes: NodeTypes = { agent: AgentCard, start: StartNode, end: EndNode }

const EDGE_STYLE: Record<string, Partial<Edge>> = {
  route: { style: { stroke: '#94a3b8' } },
  entry: { style: { stroke: '#34d399' } },
  tool: { style: { stroke: '#a78bfa', strokeDasharray: '4 4' }, animated: false },
  compensate: { style: { stroke: '#f59e0b', strokeDasharray: '2 4' } },
}

/** Lines from an output key to each agent that consumes it. */
function dataFlowEdges(view: WorkflowView): Edge[] {
  const out: Edge[] = []
  for (const consumer of view.agents) {
    for (const key of Object.keys(consumer.inputs)) {
      const producers = view.agents.filter((p) => p.id !== consumer.id && key in p.outputs)
      if (!producers.length && key in view.trigger.input) {
        out.push({ id: `df:${START}:${consumer.id}:${key}`, source: START, sourceHandle: 'out', target: consumer.id, label: key,
          style: { stroke: '#38bdf8', strokeDasharray: '1 3' }, labelStyle: { fill: '#7dd3fc', fontSize: 10 } })
      }
      for (const p of producers) {
        out.push({ id: `df:${p.id}:${consumer.id}:${key}`, source: p.id, sourceHandle: '__tools', target: consumer.id, label: key,
          style: { stroke: '#38bdf8', strokeDasharray: '1 3' }, labelStyle: { fill: '#7dd3fc', fontSize: 10 } })
      }
    }
  }
  return out
}

function Canvas({ view, saved, issues, selected, dataFlow, apply, onSelect, onMoved, breakpoints, onToggleBreakpoint }: Props) {
  const graph = useMemo(() => toGraph(view), [view])
  const positions = useMemo(() => layout(view, graph.edges, saved), [view, graph.edges, saved])
  const nodes: Node[] = useMemo(() => [
    { id: START, type: 'start', position: positions[START], data: { trigger: view.trigger, access: view.access }, selected: selected === START },
    ...view.agents.map((a): Node => ({
      id: a.id,
      type: 'agent',
      position: positions[a.id],
      selected: selected === a.id,
      data: {
        agent: a,
        issues: issues[a.id] ?? { errors: 0, warnings: 0 },
        outlets: outletsOf(a),
        missingInputs: issues[a.id]?.missingInputs ?? [],
        breakpoint: breakpoints.includes(a.id),
        onToggleBreakpoint: () => onToggleBreakpoint(a.id),
      } satisfies AgentCardData,
    })),
    ...Object.entries(view.ends).map(([name, e]): Node => ({
      id: `END.${name}`, type: 'end', position: positions[`END.${name}`], data: { name, status: e.status }, selectable: false,
    })),
  ], [view, positions, issues, selected, breakpoints, onToggleBreakpoint])
  const edges: Edge[] = useMemo(() => [
    ...graph.edges.map((e): Edge => ({
      id: e.id, source: e.source, sourceHandle: e.sourceHandle, target: e.target,
      label: e.kind === 'route' ? undefined : e.label || undefined,
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
      deletable: e.kind === 'route' || e.kind === 'entry',
      ...EDGE_STYLE[e.kind],
    })),
    ...(dataFlow ? dataFlowEdges(view) : []),
  ], [graph.edges, dataFlow, view])

  const onConnect = useCallback((c: Connection) => {
    if (!c.source || !c.target || c.target === START) return
    const target = c.target.startsWith('END.') ? (c.target === 'END.default' ? 'END' : c.target) : c.target
    if (c.source === START) {
      if (!target.startsWith('END')) apply((t) => setWorkflowField(t, ['spec', 'start'], target))
      return
    }
    if (!c.sourceHandle || c.sourceHandle === '__tools') return
    apply((t) => setRoute(t, c.source!, c.sourceHandle!, target))
  }, [apply])

  const onEdgesDelete = useCallback((deleted: Edge[]) => {
    for (const e of deleted) {
      if (e.id === 'entry') apply((t) => setWorkflowField(t, ['spec', 'start'], undefined))
      else if (e.sourceHandle && e.sourceHandle !== '__tools' && !e.id.startsWith('df:')) apply((t) => setRoute(t, e.source, e.sourceHandle!, null))
    }
  }, [apply])

  const theme = useUIStore((st) => st.theme)
  const light = theme === 'light'

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onConnect={onConnect}
      onEdgesDelete={onEdgesDelete}
      onNodeClick={(_, n) => { if (n.type !== 'end') onSelect(n.id) }}
      onPaneClick={() => onSelect(null)}
      onNodeDragStop={(_, n) => onMoved({ ...positions, [n.id]: n.position })}
      deleteKeyCode={['Backspace', 'Delete']}
      nodesConnectable
      fitView
      fitViewOptions={{ padding: 0.15 }}
      minZoom={0.2}
      proOptions={{ hideAttribution: true }}
      colorMode={light ? 'light' : 'dark'}
    >
      <Background gap={20} color={light ? '#e4e4e7' : '#27272a'} />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable className="!bg-slate-900" maskColor={light ? 'rgba(244,244,245,0.7)' : 'rgba(9,9,11,0.6)'} />
    </ReactFlow>
  )
}

interface Props {
  view: WorkflowView
  saved: Positions
  issues: Record<string, AgentIssues>
  selected: string | null
  dataFlow: boolean
  apply: (edit: (text: string) => string) => void
  onSelect: (id: string | null) => void
  onMoved: (positions: Positions) => void
  breakpoints: string[]
  onToggleBreakpoint: (agentId: string) => void
}

export function CanvasView(props: Props) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  )
}
