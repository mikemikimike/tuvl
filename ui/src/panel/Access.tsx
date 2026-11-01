import { useState } from 'react'
import { Link } from 'react-router-dom'
import { setField, setWorkflowField, type AgentView, type WorkflowView } from '../canvas/model'
import { useAssignRole, useCreateIamRole, useIamRoles, useIamUsers, useRevokeRole, useUpdateRoleScopes } from '../queries'
import { Row, TextField } from './fields'
import { inputClass } from './styles'

type Apply = (e: (t: string) => string) => void
type Mode = 'public' | 'signed-in' | 'role' | 'scope'

const label = (u: { email: string; first_name?: string | null; last_name?: string | null }) =>
  [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email

/** An IAM role, picked from the roles that exist (or a new one, created in IAM right away). */
export function RolePicker({ value, onChange, ariaLabel, emptyLabel, newRoleScopes = [] }: {
  value: string | null
  onChange: (role: string | null) => void
  ariaLabel: string
  emptyLabel: string
  /** scopes a role created here starts with */
  newRoleScopes?: string[]
}) {
  const roles = useIamRoles()
  const create = useCreateIamRole()
  const [adding, setAdding] = useState<string | null>(null)
  const names = (roles.data ?? []).map((r) => r.name)
  const missing = value && roles.isSuccess && !names.includes(value)
  if (adding !== null) {
    return (
      <form className="flex gap-1" onSubmit={(e) => {
        e.preventDefault()
        const name = adding.trim()
        if (!name) return
        create.mutate({ name, scopes: newRoleScopes }, { onSuccess: () => { setAdding(null); onChange(name) } })
      }}>
        <input autoFocus aria-label="New role name" value={adding} onChange={(e) => setAdding(e.target.value)} placeholder="role name, e.g. cop_manager"
          className={`${inputClass} flex-1 font-mono`} />
        <button type="submit" disabled={create.isPending} className="text-xs px-2 rounded bg-indigo-600 disabled:opacity-40">Create</button>
        <button type="button" onClick={() => setAdding(null)} className="text-xs px-2 rounded bg-slate-700">Cancel</button>
        {create.error && <span className="text-[11px] text-rose-400">{(create.error as Error).message}</span>}
      </form>
    )
  }
  return (
    <div className="space-y-1">
      <select aria-label={ariaLabel} className={`${inputClass} w-full`} value={value ?? ''}
        onChange={(e) => (e.target.value === '__new' ? setAdding('') : onChange(e.target.value || null))}>
        <option value="">{emptyLabel}</option>
        {names.map((n) => <option key={n} value={n}>{n}</option>)}
        {missing && <option value={value}>{value} (no such role yet)</option>}
        <option value="__new">+ New role…</option>
      </select>
      {missing && <p className="text-[10px] text-amber-400">No IAM role named <span className="font-mono">{value}</span> — nobody can pass this check until it exists.</p>}
      {roles.isError && <p className="text-[10px] text-amber-400">Can&apos;t list IAM roles: {(roles.error as Error).message}</p>}
    </div>
  )
}

/** The users holding *role*; adding or removing one changes IAM immediately (it isn't part of the workflow file). */
export function RoleMembers({ role }: { role: string }) {
  const users = useIamUsers()
  const roles = useIamRoles()
  const assign = useAssignRole()
  const revoke = useRevokeRole()
  const [pick, setPick] = useState('')
  const roleId = roles.data?.find((r) => r.name === role)?.id
  if (!roleId) return null
  const all = users.data ?? []
  const members = all.filter((u) => u.roles.includes(role))
  const others = all.filter((u) => !u.roles.includes(role))
  const error = (assign.error ?? revoke.error) as Error | null
  return (
    <div className="rounded border border-slate-800 bg-slate-950/50 p-2 space-y-1.5">
      <p className="text-[11px] text-slate-400">Members of <span className="font-mono text-slate-200">{role}</span> ({members.length})</p>
      <ul className="space-y-0.5">
        {members.map((u) => (
          <li key={u.id} className="flex items-center gap-2 text-xs">
            <span className="text-slate-200 truncate">{label(u)}</span>
            {label(u) !== u.email && <span className="text-slate-500 truncate">{u.email}</span>}
            {!u.is_active && <span className="text-amber-400">inactive</span>}
            <button className="ml-auto text-slate-500 hover:text-rose-400" aria-label={`Remove ${u.email} from ${role}`}
              disabled={revoke.isPending} onClick={() => revoke.mutate({ userId: u.id, roleId })}>✕</button>
          </li>
        ))}
        {members.length === 0 && <li className="text-[11px] text-slate-500">Nobody yet — only <span className="font-mono">iam:admin</span> can run it.</li>}
      </ul>
      {others.length > 0 && (
        <div className="flex gap-1">
          <select aria-label={`Add a user to ${role}`} className={`${inputClass} flex-1`} value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">Add a user…</option>
            {others.map((u) => <option key={u.id} value={u.id}>{label(u)}{label(u) !== u.email ? ` · ${u.email}` : ''}</option>)}
          </select>
          <button className="text-xs px-2 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40" disabled={!pick || assign.isPending}
            onClick={() => assign.mutate({ userId: pick, roleId }, { onSuccess: () => setPick('') })}>Add</button>
        </div>
      )}
      {error && <p className="text-[11px] text-rose-400">{error.message}</p>}
      <p className="text-[10px] text-slate-500">
        Changes IAM now, for every workflow using this role (they apply at the user&apos;s next sign-in). New users: <Link to="/iam" className="text-indigo-300 hover:underline">IAM</Link>.
      </p>
    </div>
  )
}

/** Who may start the workflow — the trigger check the engine runs before any agent. */
export function WorkflowAccess({ view, apply }: { view: WorkflowView; apply: Apply }) {
  const { requiredGroup, requiredScope, public: isPublic } = view.access
  const http = !!view.trigger.http
  const mode: Mode = requiredGroup ? 'role' : requiredScope ? 'scope' : isPublic ? 'public' : 'signed-in'
  // one apply: the three keys are exclusive (the validator rejects public with a scope or group)
  const write = (next: { group?: string | null; scope?: string | null; open?: boolean }) => apply((t) => {
    let out = setWorkflowField(t, ['metadata', 'required_group'], next.group ?? undefined)
    out = setWorkflowField(out, ['metadata', 'required_scope'], next.scope ?? undefined)
    if (http) out = setWorkflowField(out, ['spec', 'trigger', 'http', 'public'], next.open ? true : undefined)
    return out
  })
  const [pendingMode, setPendingMode] = useState<Mode | null>(null)
  const shown = pendingMode ?? mode
  const choose = (m: Mode) => {
    if (m === 'public') { setPendingMode(null); write({ open: true }) }
    else if (m === 'signed-in') { setPendingMode(null); write({}) }
    else setPendingMode(m) // waits for the role / scope to be picked
  }
  const option = (m: Mode, title: string, hint: string, disabled = false) => (
    <label className={`flex items-start gap-2 text-xs ${disabled ? 'opacity-40' : ''}`}>
      <input type="radio" name="workflow-access" className="mt-0.5" checked={shown === m} disabled={disabled} onChange={() => choose(m)} />
      <span><span className="text-slate-200">{title}</span><span className="block text-[10px] text-slate-500">{hint}</span></span>
    </label>
  )
  return (
    <section aria-label="Access" className="space-y-2">
      <p className="text-[11px] text-slate-400">Who can run it</p>
      {option('signed-in', 'Any signed-in user', 'A valid token, no particular role (the default)')}
      {option('role', 'Members of an IAM role', 'Checked before the first agent runs; others get 403')}
      {option('scope', 'Callers with a scope', 'For service tokens and fine-grained grants')}
      {option('public', 'Anyone — no sign-in', http ? 'For webhooks and public endpoints' : 'Needs the HTTP trigger', !http)}
      {shown === 'role' && (
        <>
          <RolePicker value={requiredGroup} ariaLabel="Role required to run" emptyLabel="Choose a role…"
            onChange={(r) => { if (r) { setPendingMode(null); write({ group: r }) } }} />
          {requiredGroup && <RoleMembers role={requiredGroup} />}
        </>
      )}
      {shown === 'scope' && (
        <Row label="Required scope" hint="e.g. flags:write — grant it to a role on the IAM page">
          <TextField mono value={requiredScope ?? ''} ariaLabel="Required scope" placeholder="resource:action"
            onCommit={(v) => { if (v.trim()) { setPendingMode(null); write({ scope: v.trim() }) } }} />
        </Row>
      )}
      <p className="text-[10px] text-slate-500">
        <span className="font-mono">iam:admin</span> always passes. Rules about the record itself (e.g. &quot;a member of this community&quot;) belong in an agent.
        {' '}Under <span className="font-mono">tuvl dev</span>, workflows with no role or scope accept calls without a token.
      </p>
    </section>
  )
}

const DECIDE = 'approvals:decide'

/** Deciding needs the scope as well as the group: say so, and offer to grant it. */
function DecideScopeCheck({ role }: { role: string }) {
  const roles = useIamRoles()
  const update = useUpdateRoleScopes()
  const found = roles.data?.find((r) => r.name === role)
  if (!found || found.scopes.includes(DECIDE) || found.scopes.includes('iam:admin')) return null
  return (
    <div className="rounded border border-amber-700/60 bg-amber-950/30 p-2 text-[11px] text-amber-200 space-y-1.5">
      <p>
        <span className="font-mono">{role}</span> lacks the <span className="font-mono">{DECIDE}</span> scope, so its
        members can&apos;t see or decide this step — only <span className="font-mono">iam:admin</span> can.
      </p>
      <button className="px-2 py-1 rounded bg-amber-600 text-white disabled:opacity-40" disabled={update.isPending}
        onClick={() => update.mutate({ roleId: found.id, scopes: [...found.scopes, DECIDE] })}>
        Grant {DECIDE} to {role}
      </button>
      <p className="text-amber-300/80">Members get it at their next sign-in.</p>
      {update.error && <p className="text-rose-400">{(update.error as Error).message}</p>}
    </div>
  )
}

/** A human step: which IAM role may decide it (enforced), and who it's addressed to (shown on the task only). */
export function HumanAccess({ agent, apply }: { agent: AgentView; apply: Apply }) {
  const human = (agent.raw.human ?? {}) as { required_group?: string; assignee?: string }
  const set = (key: string, value: string | null) => apply((t) => setField(t, agent.id, ['human', key], value ?? undefined))
  return (
    <section aria-label="Who decides" className="space-y-2">
      <Row label="Who can decide (IAM role)" hint="Others are refused when they submit a decision">
        <RolePicker value={human.required_group ?? null} ariaLabel="Role that decides" emptyLabel="Any signed-in user"
          newRoleScopes={[DECIDE]} onChange={(r) => set('required_group', r)} />
      </Row>
      {human.required_group && <DecideScopeCheck role={human.required_group} />}
      {human.required_group && <RoleMembers role={human.required_group} />}
      <Row label="Addressed to (optional)" hint="Shown on the task, e.g. {{ owner_email }} — a label, not a permission">
        <TextField mono value={human.assignee ?? ''} ariaLabel="Assignee" placeholder="{{ field }} or a name" onCommit={(v) => set('assignee', v.trim() || null)} />
      </Row>
    </section>
  )
}
