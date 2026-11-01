import type { AuditEvent, SpecLifecycle } from '../devApi'

/** How a spec's approval reads: stale beats approved, because an edited body is a draft again. */
export function statusLabel(s: Pick<SpecLifecycle, 'managed' | 'status' | 'stale' | 'effective'>): {
  text: string
  tone: 'ok' | 'warn' | 'bad' | 'mute'
} {
  if (!s.managed) return { text: 'not under approval', tone: 'mute' }
  if (s.stale) return { text: 'approved, changed since', tone: 'bad' }
  if (s.status === 'approved') return { text: 'approved', tone: 'ok' }
  if (s.status === 'superseded') return { text: 'superseded', tone: 'mute' }
  return { text: 'draft', tone: 'warn' }
}

export const TONE: Record<'ok' | 'warn' | 'bad' | 'mute', string> = {
  ok: 'bg-emerald-900/60 text-emerald-300',
  warn: 'bg-amber-900/60 text-amber-300',
  bad: 'bg-rose-900/60 text-rose-300',
  mute: 'bg-slate-800 text-slate-400',
}

/** `IDEA-SK-0004` for `SPEC-SK-0004-01` and `TASK-SK-0004-01-003`; null for anything else. */
export function ideaOf(id: string): string | null {
  const m = /^(?:IDEA|SPEC|TASK)-([A-Z][A-Z0-9]{1,3})-(\d{4,})(?:-\d{2,}(?:-\d{3,})?)?$/.exec(id)
  return m ? `IDEA-${m[1]}-${m[2]}` : null
}

export function entityKind(id: string): 'idea' | 'spec' | 'task' | 'other' {
  if (/^IDEA-/.test(id)) return 'idea'
  if (/^SPEC-/.test(id)) return 'spec'
  if (/^TASK-/.test(id)) return 'task'
  return 'other'
}

/** Where an id lives in Insight, or null when it has no page. */
export function entityLink(id: string): string | null {
  switch (entityKind(id)) {
    case 'idea':
      return `/ideas?idea=${encodeURIComponent(id)}`
    case 'spec':
      return `/specs?spec=${encodeURIComponent(`${id}.md`)}`
    case 'task': {
      const m = /^TASK-([A-Z0-9]+)-(\d+)-(\d+)-\d+$/.exec(id)
      return m ? `/specs?spec=${encodeURIComponent(`SPEC-${m[1]}-${m[2]}-${m[3]}.md`)}` : null
    }
    default:
      return id.startsWith('specs/') ? `/specs?spec=${encodeURIComponent(id.replace(/^specs\//, ''))}` : null
  }
}

export function actorOf(e: Pick<AuditEvent, 'actor'>): string {
  return e.actor.initials || e.actor.git || '—'
}

/** `2026-10-19T21:55:55.123Z` as `21:55:55`, with the date only when it is not today. */
export function shortTime(ts: string, now = new Date()): string {
  const d = ts.slice(0, 10)
  const t = ts.slice(11, 19)
  return d === now.toISOString().slice(0, 10) ? t : `${d.slice(5)} ${t}`
}

/** New events appended to what is shown, by id, keeping the order and the last `max`. */
export function mergeEvents(shown: AuditEvent[], incoming: AuditEvent[], max = 500): AuditEvent[] {
  const seen = new Set(shown.map((e) => e.id))
  const merged = [...shown, ...incoming.filter((e) => !seen.has(e.id))]
  return merged.slice(-max)
}
