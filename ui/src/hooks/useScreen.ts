import { useSyncExternalStore } from 'react'

/** wide ≥1440 px: panels dock · mid 1024–1439: panels float over the canvas · narrow <1024: bottom sheets */
export type Screen = 'wide' | 'mid' | 'narrow'

const wide = () => window.matchMedia('(min-width: 1440px)')
const mid = () => window.matchMedia('(min-width: 1024px)')

function subscribe(onChange: () => void) {
  const queries = [wide(), mid()]
  queries.forEach((q) => q.addEventListener('change', onChange))
  return () => queries.forEach((q) => q.removeEventListener('change', onChange))
}

const snapshot = (): Screen => (wide().matches ? 'wide' : mid().matches ? 'mid' : 'narrow')

export function useScreen(): Screen {
  return useSyncExternalStore(subscribe, snapshot, () => 'wide')
}
