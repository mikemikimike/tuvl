import { Fragment, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { decideApproval, type Approval } from '../runsApi'

function enumValues(type: string): string[] | null {
  const m = /^enum\[(.*)\]\??$/.exec(type)
  return m ? m[1].split(',').map((v) => v.trim()) : null
}

function coerce(type: string, raw: string): unknown {
  const base = type.replace(/\?$/, '')
  if (raw === '' && type.endsWith('?')) return null
  if (base === 'int') return Number.parseInt(raw, 10)
  if (base === 'float') return Number.parseFloat(raw)
  if (base === 'json' || base.startsWith('list[')) return JSON.parse(raw)
  return raw
}

export function ApprovalCard({ approval, onDone }: { approval: Approval; onDone?: () => void }) {
  const qc = useQueryClient()
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [args, setArgs] = useState(JSON.stringify(approval.args ?? {}, null, 2))
  const [message, setMessage] = useState('')
  const [error, setError] = useState<string | null>(null)
  const decide = useMutation({
    mutationFn: (body: Parameters<typeof decideApproval>[1]) => decideApproval(approval.approval_id, body),
    onSuccess: async () => {
      setError(null)
      await qc.invalidateQueries({ queryKey: ['runs'] })
      await qc.invalidateQueries({ queryKey: ['approvals'] })
      onDone?.()
    },
    onError: (e: Error) => setError(e.message),
  })

  if (approval.kind === 'tool') {
    return (
      <div className="rounded border border-amber-700/60 bg-amber-950/20 p-3 space-y-2 text-sm">
        <p className="text-amber-300">
          <span className="font-mono">{approval.agent_id}</span> wants to call <b className="font-mono">{approval.tool}</b>
          {approval.required_group && <span className="text-xs text-slate-400"> · needs {approval.required_group}</span>}
        </p>
        <textarea
          aria-label="Tool arguments"
          value={args}
          onChange={(e) => setArgs(e.target.value)}
          rows={Math.min(8, args.split('\n').length + 1)}
          className="w-full font-mono text-xs bg-slate-900 border border-slate-700 rounded p-2"
        />
        <input
          aria-label="Message to the agent"
          placeholder="Message to the agent (optional)"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          className="w-full text-xs bg-slate-900 border border-slate-700 rounded px-2 py-1"
        />
        <div className="flex gap-2">
          <button className="px-3 py-1 rounded bg-emerald-700 hover:bg-emerald-600 text-xs" disabled={decide.isPending}
            onClick={() => {
              let edited: unknown
              try { edited = JSON.parse(args) } catch { setError('arguments are not valid JSON'); return }
              const changed = JSON.stringify(edited) !== JSON.stringify(approval.args ?? {})
              decide.mutate(changed ? { decision: 'edit', edited_args: edited, message: message || undefined } : { decision: 'approve', message: message || undefined })
            }}>
            Approve{args !== JSON.stringify(approval.args ?? {}, null, 2) ? ' edited' : ''}
          </button>
          <button className="px-3 py-1 rounded bg-rose-800 hover:bg-rose-700 text-xs" disabled={decide.isPending}
            onClick={() => decide.mutate({ decision: 'reject', message: message || undefined })}>Reject</button>
        </div>
        {error && <p className="text-xs text-rose-400">{error}</p>}
      </div>
    )
  }

  const form = approval.form ?? {}
  return (
    <div className="rounded border border-emerald-700/60 bg-emerald-950/20 p-3 space-y-2 text-sm">
      <p className="text-emerald-300 font-medium">{approval.title ?? approval.agent_id}</p>
      {approval.instruction && <p className="text-xs text-slate-300">{approval.instruction}</p>}
      {approval.show && Object.keys(approval.show).length > 0 && (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
          {Object.entries(approval.show).map(([k, v]) => (
            <Fragment key={k}><dt className="text-slate-500 font-mono">{k}</dt><dd className="text-slate-200 break-words">{typeof v === 'string' ? v : JSON.stringify(v)}</dd></Fragment>
          ))}
        </dl>
      )}
      <div className="space-y-1.5">
        {Object.entries(form).map(([key, field]) => {
          const label = `${field.label ?? key}${field.required ? '' : ' (optional)'}`
          const options = enumValues(field.type)
          if (field.type.replace(/\?$/, '') === 'bool') {
            return (
              <label key={key} className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={values[key] === true} onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.checked }))} />
                {label}
              </label>
            )
          }
          return (
            <label key={key} className="block text-xs">
              <span className="text-slate-400">{label}</span>
              {options ? (
                <select className="mt-0.5 w-full bg-slate-900 border border-slate-700 rounded px-1.5 py-1"
                  value={String(values[key] ?? '')} onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value || null }))}>
                  <option value="">—</option>
                  {options.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <input className="mt-0.5 w-full bg-slate-900 border border-slate-700 rounded px-1.5 py-1"
                  onChange={(e) => {
                    try { setValues((v) => ({ ...v, [key]: coerce(field.type, e.target.value) })); setError(null) }
                    catch { setError(`${key}: not valid ${field.type}`) }
                  }} />
              )}
              {field.help && <span className="text-[11px] text-slate-500">{field.help}</span>}
            </label>
          )
        })}
      </div>
      <button className="px-3 py-1 rounded bg-emerald-700 hover:bg-emerald-600 text-xs" disabled={decide.isPending}
        onClick={() => {
          const filled = Object.fromEntries(Object.entries(form).map(([k, f]) => [k, values[k] ?? (f.type.replace(/\?$/, '') === 'bool' ? false : null)]))
          decide.mutate({ values: filled })
        }}>Submit decision</button>
      {error && <p className="text-xs text-rose-400">{error}</p>}
    </div>
  )
}
