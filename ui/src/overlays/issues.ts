import type { ValidationIssue, ValidationResult } from '../types'

export interface AgentIssues {
  errors: number
  warnings: number
  first?: string
  messages: ValidationIssue[]
  missingInputs: string[]
}

const AGENT = /agents\[([a-z][a-z0-9_]*)\]/
const MISSING_INPUT = /agents\[([a-z][a-z0-9_]*)\]\.inputs\.([a-z][A-Za-z0-9_]*)/

/** Validation issues of one workflow file, filed under the agent they name. */
export function issuesByAgent(report: ValidationResult | undefined, file: string): {
  agents: Record<string, AgentIssues>
  workflow: ValidationIssue[]
} {
  const agents: Record<string, AgentIssues> = {}
  const workflow: ValidationIssue[] = []
  if (!report) return { agents, workflow }
  for (const issue of [...report.errors, ...report.warnings]) {
    const path = issue.file.split(':')[0]
    if (!path.endsWith(`workflows/${file}`) && path !== file) continue
    const match = AGENT.exec(issue.message)
    if (!match) { workflow.push(issue); continue }
    const entry = (agents[match[1]] ??= { errors: 0, warnings: 0, messages: [], missingInputs: [] })
    entry.messages.push(issue)
    if (issue.severity === 'error') { entry.errors += 1; entry.first ??= issue.message } else entry.warnings += 1
    const missing = MISSING_INPUT.exec(issue.message)
    if (missing && issue.code === 'V006') entry.missingInputs.push(missing[2])
  }
  return { agents, workflow }
}
