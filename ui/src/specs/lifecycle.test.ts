import { describe, expect, it } from 'vitest'
import type { AuditEvent } from '../devApi'
import { actorOf, entityKind, entityLink, ideaOf, mergeEvents, shortTime, statusLabel } from './lifecycle'

const ev = (id: string): AuditEvent => ({
  id, ts: '2026-10-19T21:55:55.000Z', actor: { initials: 'SK' }, command: 'x', kind: 'spec.approved',
  entities: [], result: 'ok', detail: '', refs: {}, prev: '',
})

describe('statusLabel', () => {
  const base = { managed: true, status: 'draft' as const, stale: false, effective: 'draft' as const }
  it('reads approval honestly', () => {
    expect(statusLabel(base)).toEqual({ text: 'draft', tone: 'warn' })
    expect(statusLabel({ ...base, status: 'approved', effective: 'approved' })).toEqual({ text: 'approved', tone: 'ok' })
    expect(statusLabel({ ...base, status: 'approved', stale: true })).toEqual({ text: 'approved, changed since', tone: 'bad' })
    expect(statusLabel({ ...base, managed: false }).text).toBe('not under approval')
    expect(statusLabel({ ...base, status: 'superseded' }).tone).toBe('mute')
  })
})

describe('ids', () => {
  it('finds the idea behind any id', () => {
    expect(ideaOf('IDEA-SK-0004')).toBe('IDEA-SK-0004')
    expect(ideaOf('SPEC-SK-0004-01')).toBe('IDEA-SK-0004')
    expect(ideaOf('TASK-SK-0004-01-003')).toBe('IDEA-SK-0004')
    expect(ideaOf('specs/refunds.md')).toBeNull()
    expect(ideaOf('T3')).toBeNull()
  })
  it('classifies and links them', () => {
    expect(entityKind('TASK-SK-0004-01-003')).toBe('task')
    expect(entityLink('IDEA-SK-0004')).toBe('/ideas?idea=IDEA-SK-0004')
    expect(entityLink('SPEC-SK-0004-01')).toBe('/specs?spec=SPEC-SK-0004-01.md')
    expect(entityLink('TASK-SK-0004-01-003')).toBe('/specs?spec=SPEC-SK-0004-01.md')
    expect(entityLink('specs/refunds.md')).toBe('/specs?spec=refunds.md')
    expect(entityLink('billing')).toBeNull()
  })
})

describe('events', () => {
  it('names the actor and shortens times', () => {
    expect(actorOf({ actor: { initials: 'SK', git: 'Ada' } })).toBe('SK')
    expect(actorOf({ actor: { git: 'Ada <a@b.c>' } })).toBe('Ada <a@b.c>')
    expect(actorOf({ actor: {} })).toBe('—')
    const today = new Date('2026-10-19T23:00:00Z')
    expect(shortTime('2026-10-19T21:55:55.123Z', today)).toBe('21:55:55')
    expect(shortTime('2026-10-18T21:55:55.123Z', today)).toBe('10-18 21:55:55')
  })
  it('merges new events without repeating or growing without bound', () => {
    const shown = [ev('A'), ev('B')]
    expect(mergeEvents(shown, [ev('B'), ev('C')]).map((e) => e.id)).toEqual(['A', 'B', 'C'])
    expect(mergeEvents(shown, [])).toEqual(shown)
    expect(mergeEvents([ev('A'), ev('B'), ev('C')], [ev('D')], 3).map((e) => e.id)).toEqual(['B', 'C', 'D'])
  })
})
