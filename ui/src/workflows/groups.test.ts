import { describe, expect, it } from 'vitest'
import { groupNames, initials, sections } from './groups'
import type { WorkflowEntry } from './WorkflowSwitcher'

const e = (name: string, group?: string): WorkflowEntry => ({ file: `${name}.yaml`, name, group, unsaved: false })

describe('sections', () => {
  const list = [e('refund', 'payments'), e('charge', 'payments'), e('kyc', 'compliance'), e('triage'), e('alpha')]

  it('groups alphabetically, then the rest', () => {
    const s = sections(list, '', [])
    expect(s.map((x) => x.title)).toEqual(['compliance', 'payments', 'Other workflows'])
    expect(s[1].items.map((i) => i.name)).toEqual(['charge', 'refund'])
    expect(s[2].items.map((i) => i.name)).toEqual(['alpha', 'triage'])
  })

  it('calls the only section "All workflows" when nothing is grouped', () => {
    expect(sections([e('b'), e('a')], '', []).map((x) => x.title)).toEqual(['All workflows'])
  })

  it('searches names and group names', () => {
    expect(sections(list, 'pay', [])[0].items.map((i) => i.name)).toEqual(['charge', 'refund'])
    expect(sections(list, 'tri', [])[0].items.map((i) => i.name)).toEqual(['triage'])
  })

  it('shows Recent only once the list is long', () => {
    expect(sections(list, '', ['kyc.yaml']).some((x) => x.kind === 'recent')).toBe(false)
    const long = Array.from({ length: 9 }, (_, i) => e(`w${i}`))
    const s = sections(long, '', ['w3.yaml', 'gone.yaml'])
    expect(s[0]).toMatchObject({ kind: 'recent' })
    expect(s[0].items.map((i) => i.name)).toEqual(['w3'])
  })
})

describe('initials / groupNames', () => {
  it('takes the first letters of the first two words', () => {
    expect(initials('support_triage')).toBe('ST')
    expect(initials('kyc')).toBe('KY')
  })
  it('lists distinct groups sorted', () => {
    expect(groupNames([e('a', 'z'), e('b', 'a'), e('c', 'a'), e('d')])).toEqual(['a', 'z'])
  })
})
