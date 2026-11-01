import { useQuery } from '@tanstack/react-query'
import { listArtifacts } from '../api'
import type { ArtifactSummary, ArtifactType } from '../types'

/** Which stored artifact types each field of an LLM or loop agent accepts (the engine's REF_SITE_COMPAT). */
export const SITE_TYPES = {
  system: ['prompt'],
  prompt: ['prompt'],
  steering: ['steering', 'prompt'],
  skills: ['skill'],
  judge: ['judge'],
  mcp: ['mcp'],
} as const satisfies Record<string, ArtifactType[]>

export const isRef = (v: string) => v.startsWith('artifact://')

export function parseRef(ref: string): { name: string; version: number | null } {
  const [name, version] = ref.slice('artifact://'.length).split('@')
  return { name, version: version ? Number(version) : null }
}

export const makeRef = (name: string, version: number) => `artifact://${name}@${version}`

/** The artifacts stored in this project, shared with the Artifacts page's list. */
export function useArtifacts() {
  return useQuery({ queryKey: ['artifacts', 'all'], queryFn: () => listArtifacts() })
}

export const ofTypes = (all: ArtifactSummary[], types: readonly ArtifactType[]) =>
  all.filter((a) => types.includes(a.type))
