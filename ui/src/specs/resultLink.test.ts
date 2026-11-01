import { describe, expect, it } from 'vitest'
import { resultLink } from './resultLink'

describe('resultLink', () => {
  it('points a task at what it builds', () => {
    expect(resultLink({ workflow: 'refund flow' })).toBe('/workflows?wf=refund%20flow')
    expect(resultLink({ model: 'Item' })).toBe('/models')
    expect(resultLink({ artifact: 'policy' })).toBe('/artifacts')
    expect(resultLink({})).toBeNull()
  })
})
