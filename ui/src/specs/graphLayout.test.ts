import { describe, expect, it } from 'vitest'
import type { TaskStatus } from '../devApi'
import { layoutGraph, nodeState } from './graphLayout'

const t = (id: string, over: Partial<TaskStatus> = {}): TaskStatus => ({
  id, title: id, type: 'model', status: 'todo', blocked: false, stale: false, obsolete: false, reasons: [], target: {}, ...over,
})

describe('layoutGraph', () => {
  it('puts a task one level after the deepest task it waits for', () => {
    const g = layoutGraph([t('c', { depends_on: ['a', 'b'] }), t('a'), t('b', { depends_on: ['a'] })])
    const level = Object.fromEntries(g.nodes.map((n) => [n.task.id, n.level]))
    expect(level).toEqual({ a: 0, b: 1, c: 2 })
    expect(g.edges).toHaveLength(2)  // a -> c is implied by a -> b -> c
    expect(g.levels).toBe(3)
  })
  it('keeps independent tasks on one level and ignores obsolete tasks and unknown dependencies', () => {
    const g = layoutGraph([t('a'), t('b', { depends_on: ['gone'] }), t('x', { obsolete: true })])
    expect(g.nodes.map((n) => [n.level, n.slot])).toEqual([[0, 0], [0, 1]])
    expect(g.width).toBe(2)
    expect(g.edges).toEqual([])
  })
  it('survives a dependency cycle', () => {
    expect(layoutGraph([t('a', { depends_on: ['b'] }), t('b', { depends_on: ['a'] })]).nodes).toHaveLength(2)
  })
})

describe('nodeState', () => {
  it('shows what is happening before what is derived', () => {
    expect(nodeState(t('a', { live: { state: 'running' } }))).toBe('running')
    expect(nodeState(t('a', { live: { state: 'failed' } }))).toBe('failed')
    expect(nodeState(t('a', { status: 'done' }))).toBe('done')
    expect(nodeState(t('a', { blocked: true }))).toBe('blocked')
    expect(nodeState(t('a', { status: 'implemented' }))).toBe('in_progress')
    expect(nodeState(t('a'))).toBe('ready')
  })
})
