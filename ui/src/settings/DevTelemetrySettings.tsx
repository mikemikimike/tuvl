import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { checkDevTelemetry, devTelemetry, forgetDevToken, registerDeveloper, rotateDevToken, saveDevTelemetry } from '../devApi'
import type { DevTelemetryState } from '../devApi'

type Form = Pick<DevTelemetryState, 'enabled' | 'server' | 'identity' | 'commands' | 'token_env'>

const EMPTY: Form = { enabled: false, server: '', identity: 'initials', commands: true, token_env: 'TUVL_DEV_TELEMETRY_TOKEN' }

/** Optional: share what developers do on this project through the team's collector, and see what the others did. Development only. */
export function DevTelemetrySettings() {
  const qc = useQueryClient()
  const state = useQuery({ queryKey: ['dev', 'dev-telemetry'], queryFn: devTelemetry, refetchInterval: 5000 })
  const [form, setForm] = useState<Form>(EMPTY)
  const [reg, setReg] = useState({ name: '', email: '', team_code: '' })
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    const s = state.data
    if (s) setForm({ enabled: s.enabled, server: s.server, identity: s.identity, commands: s.commands, token_env: s.token_env })
    // only when the stored settings change, so typing is not overwritten by the status refresh
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.data?.enabled, state.data?.server, state.data?.identity, state.data?.commands, state.data?.token_env])

  const refresh = () => void qc.invalidateQueries({ queryKey: ['dev', 'dev-telemetry'] })
  const fail = (e: unknown) => setMessage({ ok: false, text: (e as Error).message })
  const save = useMutation({
    mutationFn: () => saveDevTelemetry(form),
    onSuccess: () => { setMessage({ ok: true, text: 'Saved to .tuvl/dev-telemetry.yaml. Commit it so the team shares it.' }); refresh() },
    onError: fail,
  })
  const register = useMutation({
    mutationFn: () => registerDeveloper({ name: regName, email: regEmail, team_code: reg.team_code }),
    onSuccess: (r) => { setMessage({ ok: true, text: `Registered as ${r.developer.name} in team ${r.developer.team}. Your token is kept in your own config folder.` }); setReg({ name: '', email: '', team_code: '' }); refresh() },
    onError: fail,
  })
  const rotate = useMutation({ mutationFn: rotateDevToken, onSuccess: () => { setMessage({ ok: true, text: 'You have a new token; the old one no longer works.' }); refresh() }, onError: fail })
  const forget = useMutation({ mutationFn: forgetDevToken, onSuccess: () => { setMessage({ ok: true, text: 'Your token was removed from this machine.' }); refresh() }, onError: fail })
  const check = useMutation({
    mutationFn: (flush: boolean) => checkDevTelemetry(flush),
    onSuccess: (r) => { setMessage(r.ok ? { ok: true, text: r.sent ? `The collector knows you; sent ${r.sent} queued event(s).` : 'The collector knows you.' } : { ok: false, text: `The collector did not accept your token: ${r.error}` }); refresh() },
    onError: fail,
  })

  const s = state.data
  const mine = s?.local
  // the name and email git already knows are the starting point for registering
  const regName = reg.name || mine?.name || ''
  const regEmail = reg.email || mine?.email || ''
  const input = 'w-full rounded border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-sm text-slate-100'
  const btn = 'px-3 py-1.5 rounded text-sm bg-slate-700 hover:bg-slate-600 disabled:opacity-40'
  const registered = s?.token_source === 'registered' && s.developer.name
  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="px-6 py-5 border-b border-slate-800 flex-shrink-0">
        <h2 className="text-base font-semibold text-slate-100">Developer telemetry</h2>
        <p className="mt-1 text-xs text-slate-500 leading-relaxed max-w-xl">
          Optional. Share what developers do on this project (ideas, specs, approvals, tasks, agent runs, branches, gates, ships and one event per command) through your
          team&apos;s collector, and see what the others did on the Audit page (Team) and in each task. Development only: <code>tuvl ship</code> keeps it out of production.
        </p>
      </div>
      <div className="flex-1 min-w-0 overflow-y-auto">
        <form className="px-6 py-6 flex flex-col gap-4 max-w-xl" onSubmit={(e) => { e.preventDefault(); setMessage(null); save.mutate() }}>
          <label className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3">
            <span>
              <span className="block text-sm font-medium text-slate-200">Share developer actions</span>
              <span className="block text-xs text-slate-600">Off by default. Events are queued locally and sent in the background.</span>
            </span>
            <input type="checkbox" aria-label="Share developer actions" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
          </label>
          <label className="text-sm text-slate-300">Team collector (https)
            <input className={input} value={form.server} placeholder="https://collector.example.com" aria-label="Team collector" onChange={(e) => setForm({ ...form, server: e.target.value })} />
          </label>
          <div className="grid grid-cols-2 gap-4">
            <label className="text-sm text-slate-300">What the events say about you
              <select className={input} value={form.identity} aria-label="Identity" onChange={(e) => setForm({ ...form, identity: e.target.value as Form['identity'] })}>
                <option value="initials">Initials only</option>
                <option value="full">Name and email</option>
              </select>
            </label>
            <label className="text-sm text-slate-300">Token variable (optional override)
              <input className={input} value={form.token_env} aria-label="Token variable" onChange={(e) => setForm({ ...form, token_env: e.target.value })} />
            </label>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={form.commands} onChange={(e) => setForm({ ...form, commands: e.target.checked })} /> Also send one event per command run (no arguments)
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <button type="submit" className={`${btn} bg-sky-700 hover:bg-sky-600`} disabled={save.isPending}>Save</button>
            <button type="button" className={btn} disabled={check.isPending || !form.server} onClick={() => { setMessage(null); check.mutate(false) }}>Check my token</button>
            <button type="button" className={btn} disabled={check.isPending || !s?.queued} onClick={() => { setMessage(null); check.mutate(true) }}>Send the queue now</button>
          </div>
        </form>

        <section aria-label="Who the events say you are" className="px-6 pb-4 max-w-xl">
          <h3 className="text-sm font-semibold text-slate-200 mb-2">Who the events say you are</h3>
          <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 text-sm text-slate-300 space-y-1">
            <p>From <code>tuvl init</code>: initials <b>{mine?.initials || '—'}</b></p>
            <p>From <code>git config</code>: <b>{mine?.name || '—'}</b> &lt;{mine?.email || '—'}&gt;</p>
            <p className="text-xs text-slate-500">
              {form.identity === 'full'
                ? 'Events carry your initials and your git name and email.'
                : 'Events carry your initials only. Your name and email reach the collector only when you register.'}
              {' '}The collector decides who you are from your token, not from what an event says.
            </p>
          </div>
        </section>

        <section aria-label="Your registration" className="px-6 pb-6 max-w-xl">
          <h3 className="text-sm font-semibold text-slate-200 mb-2">You at the collector</h3>
          {registered ? (
            <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 text-sm text-slate-300 flex items-center justify-between gap-3">
              <span>Registered as <b>{s.developer.name}</b> ({s.developer.email}) in team <b>{s.developer.team}</b></span>
              <span className="flex gap-2 shrink-0">
                <button className={btn} onClick={() => { setMessage(null); rotate.mutate() }} disabled={rotate.isPending}>Rotate token</button>
                <button className={btn} onClick={() => { setMessage(null); forget.mutate() }} disabled={forget.isPending}>Forget my token</button>
              </span>
            </div>
          ) : s?.token_source === 'env' ? (
            <p className="text-sm text-emerald-400">Using the token in {s.token_env}.</p>
          ) : (
            <form className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 grid gap-3" onSubmit={(e) => { e.preventDefault(); setMessage(null); register.mutate() }}>
              <p className="text-xs text-slate-500">Register once to get a token of your own; it sends and reads for you. Ask whoever runs the collector for the team&apos;s join code. Save the collector&apos;s address first.</p>
              <input className={input} aria-label="Your name" placeholder="Your name" value={regName} onChange={(e) => setReg({ ...reg, name: e.target.value })} />
              <input className={input} aria-label="Your email" placeholder="you@company.com" value={regEmail} onChange={(e) => setReg({ ...reg, email: e.target.value })} />
              <input className={input} aria-label="Join code" type="password" placeholder="The team's join code" value={reg.team_code} onChange={(e) => setReg({ ...reg, team_code: e.target.value })} />
              <div><button type="submit" className={`${btn} bg-sky-700 hover:bg-sky-600`} disabled={register.isPending || !regName || !regEmail || !reg.team_code || !s?.server}>Register</button></div>
            </form>
          )}
        </section>

        <div className="px-6 pb-8 max-w-xl space-y-2">
          {message && <p role="status" className={`text-sm ${message.ok ? 'text-emerald-400' : 'text-rose-400'}`}>{message.text}</p>}
          {s && (
            <p className="text-xs text-slate-500">
              {s.queued} event(s) waiting · {s.sent} sent{s.last_ok ? ` · last delivery ${new Date(s.last_ok * 1000).toLocaleString()}` : ''}
              {s.last_error ? <span className="text-rose-400"> · last error: {s.last_error}</span> : null}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
