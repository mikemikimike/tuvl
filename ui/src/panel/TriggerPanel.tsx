import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiOn, fileInputs, setApiEnabled, setSchedule, setWorkflowField, type WorkflowView } from '../canvas/model'
import { fetchSchedules, schedulePreview } from '../devApi'
import { coerceInput, inputText } from '../lib/workflow-context'
import { Row, TextField } from './fields'
import { inputClass } from './styles'

const DEFAULT_CRON = '0 9 * * *'

const utc = (iso: string) => `${iso.slice(0, 16).replace('T', ' ')} UTC`

/** How the workflow starts: the API route and the schedule, each with its own switch. */
export function TriggerPanel({ view, apply }: { view: WorkflowView; apply: (e: (t: string) => string) => void }) {
  const set = (path: (string | number)[], value: unknown) => apply((t) => setWorkflowField(t, path, value))
  const { http, schedule } = view.trigger
  const api = apiOn(view.trigger)
  const [cronError, setCronError] = useState<string | null>(null)

  const preview = useQuery({
    queryKey: ['schedule-preview', schedule?.cron],
    queryFn: () => schedulePreview(schedule!.cron),
    enabled: !!schedule?.enabled && !!schedule.cron,
  })
  const status = useQuery({ queryKey: ['schedules'], queryFn: fetchSchedules, enabled: !!schedule, retry: false, refetchInterval: 15_000 })
  const row = status.data?.workflows.find((w) => w.workflow === view.name)

  const commitCron = async (value: string) => {
    const cron = value.trim()
    const check = cron ? await schedulePreview(cron) : { ok: false, error: 'Enter a 5-field cron expression, e.g. 0 9 * * 1-5' }
    setCronError(check.ok ? null : (check.error ?? 'Invalid cron expression'))
    if (check.ok) apply((t) => setSchedule(t, { cron }))
  }
  const setInput = (name: string, type: string, text: string) => {
    const next = { ...schedule!.input }
    const value = coerceInput(type, text)
    if (value === undefined) delete next[name]
    else next[name] = value
    apply((t) => setSchedule(t, { input: next }))
  }

  return (
    <div className="space-y-3">
      <p className="text-[11px] text-slate-400">Triggers — a workflow can start from the API, on a schedule, or both.</p>

      <div className="space-y-2 rounded border border-slate-700 p-2">
        <label className="flex items-center gap-2 text-xs text-slate-200">
          <input type="checkbox" checked={api} aria-label="API trigger"
            onChange={(e) => apply((t) => setApiEnabled(t, e.target.checked, `/${view.name.replace(/_/g, '-')}`))} />
          API
        </label>
        {http && (
          <div className={`grid grid-cols-3 gap-2 ${api ? '' : 'opacity-50'}`}>
            <select aria-label="Method" className={inputClass} value={http.method ?? 'POST'} onChange={(e) => set(['spec', 'trigger', 'http', 'method'], e.target.value)}>
              {['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => <option key={m}>{m}</option>)}
            </select>
            <div className="col-span-2"><TextField mono value={http.path ?? ''} ariaLabel="Path" onCommit={(v) => set(['spec', 'trigger', 'http', 'path'], v)} /></div>
          </div>
        )}
        {http && fileInputs(view.trigger.input).length > 0 && (
          <div className="space-y-1 border-t border-slate-800 pt-2">
            <p className="text-[11px] text-slate-400">File upload (multipart)</p>
            <Row label="Store" hint="a kind: Storage file; uploads land here">
              <TextField mono value={http.upload?.store ?? ''} ariaLabel="Upload store" placeholder="e.g. inbox"
                onCommit={(v) => set(['spec', 'trigger', 'http', 'upload'], v.trim() ? { ...http.upload, store: v.trim() } : undefined)} />
            </Row>
            {http.upload && (
              <div className="grid grid-cols-3 gap-2">
                <Row label="Max MiB">
                  <TextField value={String(Math.round((http.upload.max_bytes ?? 16 * 1048576) / 1048576))} ariaLabel="Upload max MiB"
                    onCommit={(v) => Number(v) > 0 && set(['spec', 'trigger', 'http', 'upload', 'max_bytes'], Math.round(Number(v) * 1048576))} />
                </Row>
                <Row label="Files">
                  <TextField value={String(http.upload.max_files ?? 10)} ariaLabel="Upload max files"
                    onCommit={(v) => Number(v) > 0 && set(['spec', 'trigger', 'http', 'upload', 'max_files'], Number(v))} />
                </Row>
                <Row label="Accept">
                  <TextField mono value={(http.upload.accept ?? []).join(', ')} ariaLabel="Upload accept" placeholder="any"
                    onCommit={(v) => set(['spec', 'trigger', 'http', 'upload', 'accept'], v.split(',').map((x) => x.trim()).filter(Boolean))} />
                </Row>
              </div>
            )}
            {!http.upload && <p className="text-[10px] text-amber-300">Without a store this route cannot receive the file input.</p>}
          </div>
        )}
        {!api && <p className="text-[10px] text-slate-500">The route is not mounted. Runs can still be started with POST /api/workflows/{view.name}/runs.</p>}
      </div>

      <div className="space-y-2 rounded border border-slate-700 p-2">
        <label className="flex items-center gap-2 text-xs text-slate-200">
          <input type="checkbox" checked={!!schedule?.enabled} aria-label="Schedule trigger"
            onChange={(e) => apply((t) => setSchedule(t, { cron: schedule?.cron || DEFAULT_CRON, enabled: e.target.checked }))} />
          Schedule
        </label>
        {schedule && (
          <div className={`space-y-2 ${schedule.enabled ? '' : 'opacity-50'}`}>
            <Row label="Cron (UTC)" hint="minute hour day-of-month month day-of-week — e.g. 0 9 * * 1-5">
              <TextField mono value={schedule.cron} ariaLabel="Schedule" onCommit={(v) => void commitCron(v)} />
            </Row>
            {cronError && <p role="alert" className="text-[11px] text-rose-400">{cronError}</p>}
            {schedule.enabled && !cronError && preview.data?.ok && (
              <p className="text-[11px] text-slate-400">Next: {preview.data.next?.map(utc).join(' · ')}</p>
            )}

            {status.data?.scheduler.multi_tenant && (
              <Row label="Tenants" hint="multi_tenant mode: one scheduled run per tenant, comma-separated">
                <TextField mono value={view.trigger.tenants.join(', ')} ariaLabel="Scheduled tenants"
                  onCommit={(v) => set(['spec', 'trigger', 'tenants'], v.split(',').map((x) => x.trim()).filter(Boolean))} />
              </Row>
            )}

            <div>
              <p className="text-[11px] text-slate-400 mb-1">Input for scheduled runs</p>
              {Object.keys(view.trigger.input).length === 0 && <p className="text-[10px] text-slate-500">This workflow takes no input.</p>}
              {Object.entries(view.trigger.input).map(([name, type]) => {
                const optional = type.endsWith('?')
                const value = schedule.input[name]
                return (
                  <div key={name} className="grid grid-cols-3 gap-2 items-center mb-1">
                    <span className="text-xs font-mono text-slate-300 truncate" title={`${name}: ${type}`}>
                      {name}{optional ? '' : ' *'} <span className="text-slate-500">{type}</span>
                    </span>
                    <div className="col-span-2">
                      {type.replace(/\?$/, '') === 'bool' ? (
                        <select aria-label={`Scheduled input ${name}`} className={inputClass} value={value === undefined ? '' : String(value)}
                          onChange={(e) => setInput(name, type, e.target.value)}>
                          <option value="">—</option><option value="true">true</option><option value="false">false</option>
                        </select>
                      ) : (
                        <TextField mono value={inputText(value)} ariaLabel={`Scheduled input ${name}`} placeholder={optional ? 'optional' : 'required'}
                          onCommit={(v) => setInput(name, type, v)} />
                      )}
                    </div>
                    {schedule.enabled && !optional && value === undefined && (
                      <p className="col-span-3 text-[10px] text-amber-300">Required: a scheduled run fails validation without it.</p>
                    )}
                  </div>
                )
              })}
            </div>

            {status.data && !status.data.scheduler.enabled && (
              <p className="text-[11px] text-amber-300">The scheduler is off on this server (TUVL_SCHEDULER_ENABLED=false).</p>
            )}
            {row?.warnings.map((w) => <p key={w} className="text-[11px] text-amber-300">{w}</p>)}
            {row?.last_run && (
              <p className="text-[11px] text-slate-400">Last scheduled run: {row.last_run.status} · {utc(row.last_run.at)}</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
