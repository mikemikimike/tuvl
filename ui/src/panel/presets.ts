import { useAllAgentModels, useFilesIndex } from '../queries'

/** The AgentModel presets configured in `llms/`, as the engines refer to them: `model: default`. */
export function usePresets(kind: 'llm' | 'decision') {
  const index = useFilesIndex()
  const names = index.data?.llms ?? []
  const results = useAllAgentModels(names)
  const presets = names.flatMap((name, i) => {
    const cfg = results[i]?.data
    if (!cfg) return []
    const spec = cfg.spec
    const type = spec?.type ?? 'llm'
    if (type !== kind) return []
    return [{ name: cfg.metadata?.name ?? name, model: spec?.model ?? cfg.model ?? '', provider: spec?.provider, enabled: cfg.enabled !== false }]
  })
  return { presets, loading: index.isLoading || results.some((r) => r.isLoading) }
}
