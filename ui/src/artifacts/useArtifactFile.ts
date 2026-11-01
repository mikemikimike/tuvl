import { useQuery } from '@tanstack/react-query'
import { listText, readText } from '../devApi'
import { readArtifact } from './doc'

/** The YAML file under artifacts/ that holds the latest version of artifact *name*. */
export function useArtifactFile(name: string) {
  return useQuery({
    queryKey: ['artifact-file', name],
    queryFn: async () => {
      const files = (await listText('artifacts')).filter((f) => /\.ya?ml$/.test(f))
      const likely = [...files.filter((f) => f.includes(name)), ...files.filter((f) => !f.includes(name))]
      let best: { file: string; text: string; version: number } | null = null
      for (const file of likely) {
        const text = await readText('artifacts', file)
        const art = readArtifact(text)
        if (art?.name === name && (!best || art.version > best.version)) best = { file, text, version: art.version }
        if (best && !file.includes(name)) break
      }
      if (!best) throw new Error(`no YAML file under artifacts/ defines '${name}'`)
      return best
    },
  })
}
