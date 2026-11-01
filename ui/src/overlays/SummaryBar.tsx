import type { ValidationResult } from '../types'

export function SummaryBar({ report, file, pending, dirty }: {
  report: ValidationResult | undefined
  file: string
  pending: boolean
  dirty: boolean
}) {
  const profile = report ? Object.values(report.profiles).find((p) => p.file.endsWith(file)) : undefined
  const mine = (i: { file: string }) => i.file.split(':')[0].endsWith(file)
  const errors = report?.errors.filter(mine).length ?? 0
  const warnings = report?.warnings.filter(mine).length ?? 0
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="hidden xl:inline text-slate-400">{profile?.summary ?? ''}</span>
      {pending ? <span className="text-slate-500">validating…</span> : errors ? (
        <span className="text-rose-400">✗ {errors} error{errors === 1 ? '' : 's'}</span>
      ) : (
        <span className="text-emerald-400">✓ valid{dirty ? ' (draft)' : ''}</span>
      )}
      {warnings > 0 && <span className="text-amber-300">⚠ {warnings}</span>}
    </div>
  )
}
