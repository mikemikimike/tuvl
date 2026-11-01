import { useState } from 'react'
import type { ValidationIssue, ValidationResult } from '../types'

/** The workflow's validation problems, one line at the bottom; opens upward into the full list. */
export function ProblemsBar({ report, file, onPick }: {
  report: ValidationResult | undefined
  file: string
  onPick: (agentId: string) => void
}) {
  const [open, setOpen] = useState(false)
  const mine = (i: ValidationIssue) => i.file.split(':')[0].endsWith(file)
  const issues = [...(report?.errors.filter(mine) ?? []), ...(report?.warnings.filter(mine) ?? [])]
  const errors = issues.filter((i) => i.severity === 'error').length
  const warnings = issues.length - errors
  const agentOf = (i: ValidationIssue) => /spec\.agents\[([^\]]+)\]/.exec(i.message)?.[1] ?? null
  return (
    <div className="relative shrink-0 border-t border-slate-800 bg-slate-950 text-[11px]">
      {open && issues.length > 0 && (
        <ul aria-label="Problems" className="absolute left-0 right-0 bottom-full max-h-[40vh] overflow-auto border-t border-slate-800 bg-slate-950/95 backdrop-blur py-1 z-30">
          {issues.map((i, k) => {
            const agent = agentOf(i)
            return (
              <li key={k}>
                <button disabled={!agent} onClick={() => agent && onPick(agent)}
                  className="w-full text-left px-3 py-1 font-mono hover:bg-slate-900 disabled:hover:bg-transparent">
                  <span className={i.severity === 'error' ? 'text-rose-300' : 'text-amber-300'}>{i.severity === 'error' ? '✕' : '⚠'} {i.code}</span>{' '}
                  <span className="text-slate-300">{i.message}</span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      <button onClick={() => setOpen((o) => !o)} disabled={issues.length === 0} aria-expanded={open}
        className="flex items-center gap-3 w-full px-3 h-7 text-left text-slate-400 disabled:cursor-default">
        <span className="text-slate-300">Problems {issues.length > 0 && (open ? '▾' : '▴')}</span>
        <span className={errors ? 'text-rose-300' : 'text-slate-500'}>✕ {errors}</span>
        <span className={warnings ? 'text-amber-300' : 'text-slate-500'}>⚠ {warnings}</span>
      </button>
    </div>
  )
}
