import type { WorkflowEntry } from './WorkflowSwitcher'

export interface Section {
  title: string
  kind: 'recent' | 'group' | 'other' | 'matches'
  items: WorkflowEntry[]
}

const RECENT_AFTER = 8
const RECENT_MAX = 5

const byName = (a: WorkflowEntry, b: WorkflowEntry) => a.name.localeCompare(b.name)

/**
 * The picker's sections: matches while searching; otherwise a Recent row (only once the list is long
 * enough to need one), each group alphabetically, then whatever has no group.
 */
export function sections(entries: WorkflowEntry[], query: string, recentFiles: string[]): Section[] {
  const q = query.trim().toLowerCase()
  if (q) {
    const items = entries.filter((e) => e.name.toLowerCase().includes(q) || (e.group ?? '').toLowerCase().includes(q)).sort(byName)
    return [{ title: 'Matches', kind: 'matches', items }]
  }
  const out: Section[] = []
  if (entries.length >= RECENT_AFTER) {
    const recents = recentFiles
      .map((f) => entries.find((e) => e.file === f))
      .filter((e): e is WorkflowEntry => !!e)
      .slice(0, RECENT_MAX)
    if (recents.length) out.push({ title: 'Recent', kind: 'recent', items: recents })
  }
  const grouped = new Map<string, WorkflowEntry[]>()
  const other: WorkflowEntry[] = []
  for (const e of entries) {
    if (e.group) grouped.set(e.group, [...(grouped.get(e.group) ?? []), e])
    else other.push(e)
  }
  for (const [title, items] of [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    out.push({ title, kind: 'group', items: items.sort(byName) })
  }
  if (other.length) out.push({ title: grouped.size ? 'Other workflows' : 'All workflows', kind: 'other', items: other.sort(byName) })
  return out
}

/** Two letters for a tile: `support_triage` → `ST`, `issue_credit` → `IC`, `kyc` → `KY`. */
export function initials(name: string): string {
  const parts = name.split(/[_\-\s]+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return name.slice(0, 2).toUpperCase()
}

/** The groups that exist, for the new-workflow form's suggestions. */
export function groupNames(entries: WorkflowEntry[]): string[] {
  return [...new Set(entries.map((e) => e.group).filter((g): g is string => !!g))].sort((a, b) => a.localeCompare(b))
}
