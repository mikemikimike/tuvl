import type { SpecCheck, SpecFinding } from '../devApi'

const MARK: Record<SpecFinding['severity'], { sign: string; cls: string }> = {
  error: { sign: '✗', cls: 'text-rose-400' },
  warning: { sign: '!', cls: 'text-amber-400' },
  waived: { sign: '·', cls: 'text-slate-500' },
}

export function FindingList({ findings }: { findings: SpecFinding[] }) {
  return (
    <ul className="space-y-1">
      {findings.map((f, i) => (
        <li key={i} className="flex gap-2 text-xs">
          <span className={`w-3 shrink-0 ${MARK[f.severity].cls}`}>{MARK[f.severity].sign}</span>
          <span className="w-12 shrink-0 font-mono text-slate-400">{f.code}</span>
          <span className="shrink-0 font-mono text-slate-500">{f.file ? `${f.file.replace(/^specs\//, '')}:` : ':'}{f.line}</span>
          <span className="text-slate-200">{f.message}</span>
        </li>
      ))}
    </ul>
  )
}

/** `tuvl lint spec`: blocking findings, warnings, waivers, and the prose sections nothing checks. */
export function FindingsView({ check }: { check: SpecCheck | undefined }) {
  if (!check) return <p className="text-xs text-slate-500">Checking the spec…</p>
  const order = { error: 0, warning: 1, waived: 2 }
  const findings = [...check.findings].sort((a, b) => order[a.severity] - order[b.severity] || a.line - b.line)
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-400">
        <span className={check.errors ? 'text-rose-400' : 'text-emerald-400'}>{check.errors} blocking</span>
        {' · '}
        <span className={check.warnings ? 'text-amber-400' : ''}>{check.warnings} warning(s)</span>
        {' · '}unchecked: {check.unchecked.length ? check.unchecked.map((s) => `#${s}`).join(', ') : 'none'} (prose)
      </p>
      {findings.length ? <FindingList findings={findings} /> : <p className="text-xs text-emerald-400">The spec is complete and consistent.</p>}
    </div>
  )
}
