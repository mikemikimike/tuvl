/** Where the thing a task builds is shown in Insight. */
export function resultLink(target: Record<string, string>): string | null {
  if (target.workflow) return `/workflows?wf=${encodeURIComponent(target.workflow)}`
  if (target.model) return '/models'
  if (target.artifact) return '/artifacts'
  return null
}
