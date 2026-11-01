import type { Determinism, Engine } from '../canvas/model'

export const ENGINE_LABEL: Record<Engine, string> = {
  pending: 'Pending', code: 'Code', tool: 'Tool', decide: 'Decide', llm: 'LLM', loop: 'Loop', human: 'Human', map: 'Map', parallel: 'Parallel',
}
/** Card frame by determinism class: neutral, violet (bounded AI), amber (external), hollow (pending). */
export const FRAME: Record<Determinism, string> = {
  deterministic: 'border-slate-500 bg-slate-800',
  bounded: 'border-violet-500/80 bg-violet-950/50',
  external: 'border-amber-500/70 bg-amber-950/30',
  pending: 'border-slate-500 border-dashed bg-transparent',
}
export const HEADER: Record<Determinism, string> = {
  deterministic: 'text-slate-300', bounded: 'text-violet-300', external: 'text-amber-300', pending: 'text-slate-400',
}
