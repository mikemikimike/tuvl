import { useUIStore } from '../store'
import { useValidate } from '../queries'
import type { ValidationIssue } from '../types'

function IssueItem({ issue }: { issue: ValidationIssue }) {
  const error = issue.severity === 'error'
  return (
    <li className={`rounded border p-3 ${error ? 'bg-red-950 border-red-700' : 'bg-amber-950/40 border-amber-700/60'}`}>
      <p className={`font-medium text-xs ${error ? 'text-red-300' : 'text-amber-300'}`}>
        {issue.code && <span className="font-mono mr-1.5">{issue.code}</span>}
        {issue.file}
        {issue.line != null && <span className="text-slate-500">:{issue.line}</span>}
      </p>
      <p className={`text-xs mt-1 font-mono whitespace-pre-wrap ${error ? 'text-red-400' : 'text-amber-200/80'}`}>{issue.message}</p>
    </li>
  )
}

export function ValidationPanel() {
  const open = useUIStore((s) => s.validationOpen)
  const toggle = useUIStore((s) => s.toggleValidation)
  const { data, mutate, isPending } = useValidate()

  if (!open) return null

  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-slate-900 border-l border-slate-700 flex flex-col z-50 shadow-2xl">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
        <span className="font-semibold text-sm">Validation</span>
        <div className="flex gap-2">
          <button
            onClick={() => mutate()}
            disabled={isPending}
            className="text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-50"
          >
            {isPending ? 'Running…' : 'Run'}
          </button>
          <button onClick={toggle} className="text-slate-400 hover:text-white" aria-label="Close">✕</button>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-4 text-sm space-y-4">
        {!data && <p className="text-slate-400">Run validation to check the whole project.</p>}
        {data?.valid && data.warnings.length === 0 && <p className="text-emerald-400 font-medium">✔ Project is valid</p>}
        {data && data.errors.length > 0 && (
          <ul className="space-y-2">{data.errors.map((e, i) => <IssueItem key={`e${i}`} issue={e} />)}</ul>
        )}
        {data && data.warnings.length > 0 && (
          <ul className="space-y-2">{data.warnings.map((w, i) => <IssueItem key={`w${i}`} issue={w} />)}</ul>
        )}
        {data && Object.keys(data.profiles).length > 0 && (
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500 mb-1">Workflows</p>
            <ul className="space-y-1">
              {Object.entries(data.profiles).map(([name, p]) => (
                <li key={name} className="text-xs text-slate-300">
                  <span className="font-mono text-slate-100">{name}</span> — {p.summary}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
