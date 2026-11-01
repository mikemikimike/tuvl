import { describe, expect, it } from 'vitest'
import type { ValidationIssue, ValidationResult } from '../types'
import { issuesByAgent } from './issues'

const issue = (file: string, message: string, severity: 'error' | 'warning' = 'error', code = 'V003'): ValidationIssue =>
  ({ file, message, severity, code }) as ValidationIssue

describe('issuesByAgent', () => {
  it('files issues under the agent they name, for this workflow only', () => {
    const report = {
      valid: false,
      errors: [
        issue('workflows/refund.yaml:12', '[V006] spec.agents[load].inputs.order_id is not produced upstream', 'error', 'V006'),
        issue('workflows/refund.yaml:14', '[V003] spec.agents[load].routes.default: unknown target'),
        issue('workflows/other.yaml:3', '[V003] spec.agents[load].routes.default: unknown target'),
        issue('workflows/refund.yaml:1', '[V022] spec.outputs.default.body.id is not produced'),
      ],
      warnings: [issue('workflows/refund.yaml:20', '[V014] spec.agents[dig].loop: tool schema drift', 'warning')],
    } as unknown as ValidationResult
    const { agents, workflow } = issuesByAgent(report, 'refund.yaml')
    expect(agents.load).toMatchObject({ errors: 2, warnings: 0, missingInputs: ['order_id'] })
    expect(agents.load.first).toContain('[V006]')
    expect(agents.dig).toMatchObject({ errors: 0, warnings: 1 })
    expect(workflow.map((w) => w.message)).toEqual(['[V022] spec.outputs.default.body.id is not produced'])
    expect(issuesByAgent(undefined, 'refund.yaml')).toEqual({ agents: {}, workflow: [] })
  })
})
