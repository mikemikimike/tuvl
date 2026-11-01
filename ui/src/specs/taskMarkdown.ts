import type { TaskDetail, TaskFailure, TaskStatus } from '../devApi'

const STATUS: Record<TaskStatus['status'], string> = {
  todo: 'To do',
  in_progress: 'In progress',
  implemented: 'Implemented',
  tested: 'Tested',
  done: 'Done',
  untracked: 'Untracked',
}

/** Headings in a spec section move down two levels so they sit under the task's own; code fences are left alone. */
export function demoteHeadings(text: string): string {
  let fenced = false
  return text
    .split('\n')
    .map((line) => {
      if (/^\s*(```|~~~)/.test(line)) fenced = !fenced
      return !fenced && /^#{1,4}\s/.test(line) ? `##${line}` : line
    })
    .join('\n')
}

const GATE: Record<string, string> = {
  agent: 'the coding agent did not finish',
  scope: 'the agent changed files outside this task',
  validate: 'the project did not validate or the step was not implemented',
  review: 'the code review found blocking problems',
}

/** The last failed run, attempt by attempt, with what the agent printed at the end. */
export function failureMarkdown(f: TaskFailure): string {
  const when = f.when ? new Date(f.when * 1000).toLocaleString() : ''
  const out = [
    '## Why it failed',
    `**${f.summary}**`,
    `${f.agent}, ${f.attempts.length} of ${f.max_attempts} attempt(s), $${f.cost_usd.toFixed(3)}${when ? ` · ${when}` : ''}`,
  ]
  for (const a of f.attempts) {
    out.push(`### Attempt ${a.attempt}: ${GATE[a.gate] ?? a.gate}`, a.problems.map((p) => `- ${p}`).join('\n'))
    if (a.output) out.push('Agent output (end):', '```text\n' + a.output.trim() + '\n```')
  }
  return out.join('\n\n')
}

/** The task as one readable document. */
export function taskMarkdown(d: TaskDetail, s?: TaskStatus): string {
  const out: string[] = [`# ${d.title}`]
  const facts = [`**${d.id}**`, d.type]
  if (s) facts.push(STATUS[s.status])
  if (s?.stale) facts.push('stale: its spec section changed')
  if (s?.blocked) facts.push('blocked')
  if (d.obsolete) facts.push('obsolete')
  out.push(facts.join(' · '))
  if (s && s.reasons.length > 0) out.push(s.blocked ? '## Why it is blocked' : '## Why it is not done', s.reasons.map((r) => `- ${r}`).join('\n'))
  const failure = s?.failure ?? d.failure
  if (failure) out.push(failureMarkdown(failure))
  const target = Object.entries(d.target)
  if (target.length > 0) out.push('## Builds', target.map(([k, v]) => `- ${k}: \`${v}\``).join('\n'))
  if (d.depends_on.length > 0) {
    out.push('## Waits for', d.depends_on.map((t) => `- \`${t.id}\` ${t.title}`).join('\n'))
  }
  if (d.section) {
    out.push(`## From the spec: ${d.section.title}`)
    out.push(`*${d.spec}, line ${d.section.line}*${d.section.changed ? ' — **edited since the task was derived**' : ''}`)
    out.push(demoteHeadings(d.section.text.trim()))
  }
  return out.join('\n\n')
}
