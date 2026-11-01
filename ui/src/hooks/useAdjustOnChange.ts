import { useState } from 'react'

/**
 * Runs `adjust` during render whenever `deps` change (and on the first render): React's
 * "adjust state when a value changes" pattern, which settles in one commit, unlike a
 * setState-in-effect that renders twice.
 */
export function useAdjustOnChange(deps: readonly unknown[], adjust: () => void): void {
  const [seen, setSeen] = useState<readonly unknown[] | null>(null)
  if (seen === null || seen.length !== deps.length || deps.some((d, i) => !Object.is(d, seen[i]))) {
    setSeen(deps)
    adjust()
  }
}

/** Filenames known to be disabled, accumulated as each config is loaded. */
export function useDisabledNames(
  selected: string | null,
  loaded: { enabled?: boolean } | undefined,
): Set<string> {
  const [names, setNames] = useState<Set<string>>(new Set())
  useAdjustOnChange([selected, loaded], () => {
    if (!selected || !loaded) return
    setNames((prev) => {
      const next = new Set(prev)
      if (loaded.enabled === false) next.add(selected)
      else next.delete(selected)
      return next
    })
  })
  return names
}
