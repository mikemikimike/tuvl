const RECENT_KEY = 'tuvl.recentWorkflows'

export function recent(): string[] {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]') as string[] } catch { return [] }
}

export function rememberWorkflow(file: string) {
  try { localStorage.setItem(RECENT_KEY, JSON.stringify([file, ...recent().filter((f) => f !== file)].slice(0, 6))) } catch { /* storage unavailable */ }
}
