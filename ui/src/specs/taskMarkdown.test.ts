import { describe, expect, it } from 'vitest'
import type { TaskDetail, TaskStatus } from '../devApi'
import { demoteHeadings, failureMarkdown, taskMarkdown } from './taskMarkdown'

const detail: TaskDetail = {
  id: 'TASK-SK-0001-01-002',
  title: 'Save',
  type: 'agent',
  target: { workflow: 'refund', agent: 'save' },
  obsolete: false,
  depends_on: [{ id: 'TASK-SK-0001-01-001', title: 'Item model' }],
  spec: 'specs/SPEC-SK-0001-01.md',
  section: { anchor: 'flow-refund', title: 'Flow: refund', line: 24, text: '## Steps\n```yaml\n# not a heading\n```\n', changed: true },
}
const status: TaskStatus = {
  id: detail.id, title: 'Save', type: 'agent', status: 'todo', blocked: true, stale: false, obsolete: false,
  reasons: ['model Item does not exist'], target: detail.target,
}

describe('taskMarkdown', () => {
  it('reads as a document: title, facts, why, builds, waits for, the spec section', () => {
    const md = taskMarkdown(detail, status)
    expect(md.startsWith('# Save')).toBe(true)
    expect(md).toContain('**TASK-SK-0001-01-002** · agent · To do · blocked')
    expect(md).toContain('## Why it is blocked\n\n- model Item does not exist')
    expect(md).toContain('- workflow: `refund`')
    expect(md).toContain('- `TASK-SK-0001-01-001` Item model')
    expect(md).toContain('## From the spec: Flow: refund')
    expect(md).toContain('*specs/SPEC-SK-0001-01.md, line 24*')
    expect(md).toContain('edited since the task was derived')
  })
  it('works without a status, and without a section', () => {
    const md = taskMarkdown({ ...detail, section: null, depends_on: [], target: {} })
    expect(md).toBe('# Save\n\n**TASK-SK-0001-01-002** · agent')
  })
  it('moves section headings down but leaves code fences alone', () => {
    expect(demoteHeadings('# A\ntext\n```\n# keep\n```\n### B')).toBe('### A\ntext\n```\n# keep\n```\n##### B')
  })
})

describe('failureMarkdown', () => {
  const failure = {
    summary: 'step save is still pending', agent: 'claude', max_attempts: 3, cost_usd: 0.42, when: 1760000000,
    attempts: [
      { attempt: 1, gate: 'validate' as const, problems: ['refunds.save is pending'] },
      { attempt: 2, gate: 'agent' as const, problems: ['the agent failed: timeout', 'exit code 1 after 600s'], output: 'Error: budget exceeded' },
    ],
  }
  it('lists every attempt with the check it failed and what the agent printed', () => {
    const md = failureMarkdown(failure)
    expect(md).toContain('## Why it failed')
    expect(md).toContain('**step save is still pending**')
    expect(md).toContain('2 of 3 attempt(s), $0.420')
    expect(md).toContain('### Attempt 1: the project did not validate or the step was not implemented')
    expect(md).toContain('- exit code 1 after 600s')
    expect(md).toContain('```text\nError: budget exceeded\n```')
  })
  it('is part of the task document', () => {
    expect(taskMarkdown(detail, { ...status, failure })).toContain('## Why it failed')
  })
})
