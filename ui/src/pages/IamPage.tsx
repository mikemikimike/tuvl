import { type FormEvent, type ReactNode, useMemo, useState } from 'react'
import { TopBar } from '../components/TopBar'
import {
  useIamUsers,
  useIamRoles,
  useCreateIamUser,
  useDeleteIamUser,
  useUpdateIamUser,
  useCreateIamRole,
  useDeleteIamRole,
  useUpdateRoleScopes,
  useAssignRole,
  useRevokeRole,
  useAdminScopes,
} from '../queries'
import { ApiError } from '../api'
import type { IamUser, IamRole } from '../types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function isAuthError(e: unknown) {
  return e instanceof ApiError && (e.status === 401 || e.status === 403)
}

const AVATAR_PALETTE = [
  'bg-violet-600', 'bg-indigo-500', 'bg-fuchsia-600',
  'bg-rose-600', 'bg-orange-500', 'bg-emerald-600', 'bg-cyan-600', 'bg-amber-500',
]

function avatarColor(seed: string) {
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0
  return AVATAR_PALETTE[Math.abs(h) % AVATAR_PALETTE.length]
}

// ── Shared primitives ─────────────────────────────────────────────────────────

function ScopePill({ label, onRemove }: { label: string; onRemove?: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-violet-700/40 bg-violet-900/30 px-2 py-0.5 font-mono text-[11px] text-violet-300">
      {label}
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={`Remove ${label}`}
          className="ml-0.5 leading-none text-violet-400/50 hover:text-red-400 transition-colors">×</button>
      )}
    </span>
  )
}

function RolePill({ label, onRemove }: { label: string; onRemove?: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-indigo-700/40 bg-indigo-900/40 px-2.5 py-0.5 text-[11px] font-medium text-indigo-300">
      {label}
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={`Remove ${label}`}
          className="ml-0.5 leading-none text-indigo-400/50 hover:text-red-400 transition-colors">×</button>
      )}
    </span>
  )
}

function TrashIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
    </svg>
  )
}

const inputCls = 'w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/20 transition-colors'
const labelCls = 'block text-xs font-medium text-slate-400 mb-1.5'

// ── Scope suggestion palette ──────────────────────────────────────────────────
// Shows all server-known scopes grouped by source. Clicking a suggestion adds
// it to the active scope list without typing.

function ScopeSuggestions({
  current,
  onAdd,
}: {
  current: string[]
  onAdd: (scope: string) => void
}) {
  const { data } = useAdminScopes()
  const [filter, setFilter] = useState('')

  const allScopes = useMemo(() => {
    if (!data) return []
    const out: Array<{ scope: string; group: string }> = []
    for (const [model, scopes] of Object.entries(data.crud)) {
      for (const s of scopes) out.push({ scope: s, group: model })
    }
    for (const [wf, scopes] of Object.entries(data.workflows)) {
      for (const s of scopes) out.push({ scope: s, group: `workflow: ${wf}` })
    }
    for (const s of data.system) out.push({ scope: s, group: 'system' })
    return out
  }, [data])

  const visible = allScopes.filter(
    (e) => !current.includes(e.scope) && e.scope.includes(filter.toLowerCase()),
  )

  if (!data || allScopes.length === 0) return null

  return (
    <div className="mt-3 rounded-lg border border-slate-700/60 bg-slate-800/40 p-3">
      <p className="mb-2 text-[11px] font-medium uppercase tracking-widest text-slate-500">
        Available scopes
      </p>
      {allScopes.length > 8 && (
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter…"
          className="mb-2 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300 placeholder-slate-600 outline-none focus:border-violet-500/60"
        />
      )}
      {visible.length === 0 ? (
        <p className="text-xs italic text-slate-600">All available scopes already added</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {visible.map((e) => (
            <button
              key={e.scope}
              type="button"
              onClick={() => onAdd(e.scope)}
              title={e.group}
              className="inline-flex items-center gap-1 rounded-md border border-violet-700/30 bg-violet-900/20 px-2 py-0.5 font-mono text-[11px] text-violet-300 hover:border-violet-500/60 hover:bg-violet-900/40 transition-colors"
            >
              <span className="text-violet-500/60">+</span>{e.scope}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Modal overlay ─────────────────────────────────────────────────────────────

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-md rounded-2xl border border-slate-700/80 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4">
          <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
          <button onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-800 hover:text-slate-200 transition-colors text-lg leading-none">
            ×
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  )
}

// ── Not-authorized banner ─────────────────────────────────────────────────────

function NotAuthorizedBanner() {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-amber-700/40 bg-amber-900/15 p-4">
      <span className="mt-0.5 text-amber-400">⚠</span>
      <div>
        <p className="text-sm font-semibold text-amber-300">IAM admin access required</p>
        <p className="mt-0.5 text-xs text-amber-400/70">
          Your token is missing the{' '}
          <code className="rounded bg-slate-800 px-1 text-amber-200">iam:admin</code> scope.
          In dev mode this should not appear — ensure{' '}
          <code className="rounded bg-slate-800 px-1 text-amber-200">tuvl_dev_mode</code> is set.
        </p>
      </div>
    </div>
  )
}

// ── API error extractor ──────────────────────────────────────────────────────

function extractApiError(e: unknown, fallback: string): string {
  // Only surface raw errors to the devtools console in dev builds; production
  // bundles should not leak stack traces or structured RPC errors that may
  // contain backend context.
  if (import.meta.env.DEV) {
    console.error('[IAM]', e)
  }
  if (e instanceof Error) return e.message || fallback
  return fallback
}

// ── Skeleton loader ───────────────────────────────────────────────────────────

function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-16 animate-pulse rounded-xl border border-slate-800 bg-slate-800/40" />
      ))}
    </div>
  )
}

// ── Create User modal body ────────────────────────────────────────────────────

function CreateUserModal({ onClose }: { onClose: () => void }) {
  const createUser = useCreateIamUser()
  const [email, setEmail] = useState('')
  const [phoneNumber, setPhoneNumber] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)

  const handle = async (e: FormEvent) => {
    e.preventDefault()
    setErr(null)
    if (!email.trim() && !phoneNumber.trim()) { setErr('Email or Phone Number is required.'); return }
    try {
      await createUser.mutateAsync({
        email: email.trim(),
        phone_number: phoneNumber.trim() || undefined,
        first_name: firstName.trim() || undefined,
        last_name: lastName.trim() || undefined,
        password: password || undefined
      })
      onClose()
    } catch (e) {
      setErr(extractApiError(e, 'Failed to create user.'))
    }
  }

  return (
    <form onSubmit={handle} className="space-y-4">
      <div>
        <label className={labelCls}>Email <span className="text-rose-500">*</span></label>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
          className={inputCls} placeholder="user@example.com" autoFocus autoComplete="off" />
      </div>
      <div>
        <label className={labelCls}>Phone Number</label>
        <input type="tel" value={phoneNumber} onChange={(e) => setPhoneNumber(e.target.value)}
          className={inputCls} placeholder="+15551234567" autoComplete="off" />
      </div>
      <div className="flex gap-3">
        <div className="flex-1">
          <label className={labelCls}>First Name</label>
          <input type="text" value={firstName} onChange={(e) => setFirstName(e.target.value)}
            className={inputCls} placeholder="Jane" autoComplete="off" />
        </div>
        <div className="flex-1">
          <label className={labelCls}>Last Name</label>
          <input type="text" value={lastName} onChange={(e) => setLastName(e.target.value)}
            className={inputCls} placeholder="Doe" autoComplete="off" />
        </div>
      </div>
      <div>
        <label className={labelCls}>
          Password{' '}
          <span className="font-normal text-slate-500">(optional — leave blank for federated)</span>
        </label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          className={inputCls} placeholder="••••••••" autoComplete="new-password" />
      </div>
      {err && <p className="text-xs text-red-400">{err}</p>}
      <div className="flex gap-2 pt-1">
        <button type="button" onClick={onClose}
          className="flex-1 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-400 hover:border-slate-600 hover:text-slate-200 transition-colors">
          Cancel
        </button>
        <button type="submit" disabled={createUser.isPending}
          className="flex-1 rounded-lg bg-violet-600 px-3 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50 transition-colors">
          {createUser.isPending ? 'Creating…' : 'Create user'}
        </button>
      </div>
    </form>
  )
}

// ── Create Role modal body ────────────────────────────────────────────────────

function CreateRoleModal({ onClose }: { onClose: () => void }) {
  const createRole = useCreateIamRole()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [scopeInput, setScopeInput] = useState('')
  const [scopes, setScopes] = useState<string[]>([])
  const [err, setErr] = useState<string | null>(null)

  const addScope = () => {
    const s = scopeInput.trim()
    if (s && !scopes.includes(s)) setScopes((p) => [...p, s])
    setScopeInput('')
  }

  const handle = async (e: FormEvent) => {
    e.preventDefault()
    setErr(null)
    if (!name.trim()) { setErr('Role name is required.'); return }
    try {
      await createRole.mutateAsync({ name: name.trim(), description: description.trim() || undefined, scopes })
      onClose()
    } catch (e) {
      setErr(extractApiError(e, 'Failed to create role.'))
    }
  }

  return (
    <form onSubmit={handle} className="space-y-4">
      <div>
        <label className={labelCls}>Name <span className="text-rose-500">*</span></label>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)}
          className={inputCls} placeholder="hr_manager" autoFocus spellCheck={false} />
      </div>
      <div>
        <label className={labelCls}>Description</label>
        <input type="text" value={description} onChange={(e) => setDescription(e.target.value)}
          className={inputCls} placeholder="Optional" />
      </div>
      <div>
        <label className={labelCls}>Scopes</label>
        <div className="flex gap-2">
          <input type="text" value={scopeInput} onChange={(e) => setScopeInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addScope() } }}
            className={inputCls} placeholder="e.g. requisition:write" spellCheck={false} />
          <button type="button" onClick={addScope}
            className="shrink-0 rounded-lg border border-slate-700 bg-slate-800 px-3 text-lg font-light text-slate-400 hover:border-slate-600 hover:text-slate-100 transition-colors">
            +
          </button>
        </div>
        {scopes.length > 0 && (
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {scopes.map((s) => (
              <ScopePill key={s} label={s} onRemove={() => setScopes((p) => p.filter((x) => x !== s))} />
            ))}
          </div>
        )}
        <ScopeSuggestions
          current={scopes}
          onAdd={(s) => setScopes((p) => (p.includes(s) ? p : [...p, s]))}
        />
      </div>
      {err && <p className="text-xs text-red-400">{err}</p>}
      <div className="flex gap-2 pt-1">
        <button type="button" onClick={onClose}
          className="flex-1 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-400 hover:border-slate-600 hover:text-slate-200 transition-colors">
          Cancel
        </button>
        <button type="submit" disabled={createRole.isPending}
          className="flex-1 rounded-lg bg-violet-600 px-3 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50 transition-colors">
          {createRole.isPending ? 'Creating…' : 'Create role'}
        </button>
      </div>
    </form>
  )
}

// ── Edit User modal body ──────────────────────────────────────────────────────

function EditUserModal({ user, onClose }: { user: IamUser; onClose: () => void }) {
  const updateUser = useUpdateIamUser()
  const [phoneNumber, setPhoneNumber] = useState(user.phone_number || '')
  const [firstName, setFirstName] = useState(user.first_name || '')
  const [lastName, setLastName] = useState(user.last_name || '')
  const [password, setPassword] = useState('')
  const [isActive, setIsActive] = useState(user.is_active)
  const [err, setErr] = useState<string | null>(null)

  const handle = async (e: FormEvent) => {
    e.preventDefault()
    setErr(null)
    const body: { password?: string; is_active?: boolean; phone_number?: string | null; first_name?: string | null; last_name?: string | null } = {}
    if (password) body.password = password
    if (isActive !== user.is_active) body.is_active = isActive
    // An empty string clears the field server-side; null/omitted leaves it unchanged.
    if (phoneNumber.trim() !== (user.phone_number || '')) body.phone_number = phoneNumber.trim()
    if (firstName.trim() !== (user.first_name || '')) body.first_name = firstName.trim()
    if (lastName.trim() !== (user.last_name || '')) body.last_name = lastName.trim()
    if (!Object.keys(body).length) { onClose(); return }
    try {
      await updateUser.mutateAsync({ userId: user.id, body })
      onClose()
    } catch (e) {
      setErr(extractApiError(e, 'Failed to update user.'))
    }
  }

  return (
    <form onSubmit={handle} className="space-y-4">
      <div className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-800/40 px-3 py-2.5">
        <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white ${avatarColor(user.email || user.phone_number || 'default')}`}>
          {(user.email || user.phone_number || '?')[0].toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <span className="block truncate font-mono text-sm text-slate-300">{user.email || user.phone_number || 'No login configured'}</span>
          {(user.first_name || user.last_name) && (
            <span className="block truncate text-xs text-slate-500">{[user.first_name, user.last_name].filter(Boolean).join(' ')}</span>
          )}
        </div>
      </div>
      <div>
        <label className={labelCls}>Phone Number</label>
        <input type="tel" value={phoneNumber} onChange={(e) => setPhoneNumber(e.target.value)}
          className={inputCls} placeholder="+15551234567" autoComplete="off" />
      </div>
      <div className="flex gap-3">
        <div className="flex-1">
          <label className={labelCls}>First Name</label>
          <input type="text" value={firstName} onChange={(e) => setFirstName(e.target.value)}
            className={inputCls} placeholder="Jane" autoComplete="off" />
        </div>
        <div className="flex-1">
          <label className={labelCls}>Last Name</label>
          <input type="text" value={lastName} onChange={(e) => setLastName(e.target.value)}
            className={inputCls} placeholder="Doe" autoComplete="off" />
        </div>
      </div>
      <div>
        <label className={labelCls}>New Password <span className="font-normal text-slate-500">(leave blank to keep current)</span></label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          className={inputCls} placeholder="••••••••" autoComplete="new-password" />
      </div>
      <div className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-800/40 px-4 py-3">
        <span className="text-sm text-slate-300">Account active</span>
        <button type="button" onClick={() => setIsActive((v) => !v)}
          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${isActive ? 'bg-emerald-600' : 'bg-slate-600'}`}>
          <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${isActive ? 'translate-x-4.5' : 'translate-x-0.5'}`} />
        </button>
      </div>
      {err && <p className="text-xs text-red-400">{err}</p>}
      <div className="flex gap-2 pt-1">
        <button type="button" onClick={onClose}
          className="flex-1 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-400 hover:border-slate-600 hover:text-slate-200 transition-colors">
          Cancel
        </button>
        <button type="submit" disabled={updateUser.isPending}
          className="flex-1 rounded-lg bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50 transition-colors">
          {updateUser.isPending ? 'Saving…' : 'Save changes'}
        </button>
      </div>
    </form>
  )
}

// ── Edit Role Scopes modal body ───────────────────────────────────────────────

function EditRoleScopesModal({ role, onClose }: { role: IamRole; onClose: () => void }) {
  const updateScopes = useUpdateRoleScopes()
  const [scopes, setScopes] = useState<string[]>([...role.scopes])
  const [scopeInput, setScopeInput] = useState('')
  const [err, setErr] = useState<string | null>(null)

  const addScope = () => {
    const s = scopeInput.trim()
    if (s && !scopes.includes(s)) setScopes((p) => [...p, s])
    setScopeInput('')
  }

  const handle = async (e: FormEvent) => {
    e.preventDefault()
    setErr(null)
    try {
      await updateScopes.mutateAsync({ roleId: role.id, scopes })
      onClose()
    } catch (e) {
      setErr(extractApiError(e, 'Failed to update scopes.'))
    }
  }

  return (
    <form onSubmit={handle} className="space-y-4">
      <div className="rounded-lg border border-slate-800 bg-slate-800/40 px-3 py-2.5">
        <p className="text-sm font-semibold text-violet-300">{role.name}</p>
        {role.description && <p className="mt-0.5 text-xs text-slate-500">{role.description}</p>}
      </div>
      <div>
        <label className={labelCls}>Scopes</label>
        <div className="flex gap-2">
          <input type="text" value={scopeInput} onChange={(e) => setScopeInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addScope() } }}
            className={inputCls} placeholder="e.g. requisition:write" spellCheck={false} />
          <button type="button" onClick={addScope}
            className="shrink-0 rounded-lg border border-slate-700 bg-slate-800 px-3 text-lg font-light text-slate-400 hover:border-slate-600 hover:text-slate-100 transition-colors">
            +
          </button>
        </div>
        <div className="mt-2.5 min-h-[2rem] flex flex-wrap gap-1.5">
          {scopes.length === 0
            ? <span className="text-xs italic text-slate-600">No scopes — role will be empty</span>
            : scopes.map((s) => (
                <ScopePill key={s} label={s} onRemove={() => setScopes((p) => p.filter((x) => x !== s))} />
              ))
          }
        </div>
        <ScopeSuggestions
          current={scopes}
          onAdd={(s) => setScopes((p) => (p.includes(s) ? p : [...p, s]))}
        />
      </div>
      {err && <p className="text-xs text-red-400">{err}</p>}
      <div className="flex gap-2 pt-1">
        <button type="button" onClick={onClose}
          className="flex-1 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-400 hover:border-slate-600 hover:text-slate-200 transition-colors">
          Cancel
        </button>
        <button type="submit" disabled={updateScopes.isPending}
          className="flex-1 rounded-lg bg-violet-600 px-3 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50 transition-colors">
          {updateScopes.isPending ? 'Saving…' : 'Save scopes'}
        </button>
      </div>
    </form>
  )
}

// ── Users section ─────────────────────────────────────────────────────────────

function UsersSection({ roles }: { roles: IamRole[] }) {
  const { data: users = [], isLoading, error } = useIamUsers()
  const deleteUser = useDeleteIamUser()
  const assignRole = useAssignRole()
  const revokeRole = useRevokeRole()

  const [showCreate, setShowCreate] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editingUser, setEditingUser] = useState<IamUser | null>(null)
  const [search, setSearch] = useState('')

  const filtered = users.filter((u) => u.email.toLowerCase().includes(search.toLowerCase()))

  const handleRevoke = async (userId: string, roleName: string) => {
    const role = roles.find((r) => r.name === roleName)
    if (!role) return
    await revokeRole.mutateAsync({ userId, roleId: role.id })
  }

  const handleAssign = async (userId: string, roleId: string) => {
    await assignRole.mutateAsync({ userId, roleId })
    setExpandedId(null)
  }

  const handleDelete = async (user: IamUser) => {
    if (!confirm(`Delete user "${user.email}"? This cannot be undone.`)) return
    await deleteUser.mutateAsync(user.id)
  }

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <svg className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500"
            viewBox="0 0 16 16" fill="currentColor">
            <path d="M6.5 1a5.5 5.5 0 1 0 3.16 10.013l3.163 3.163a.75.75 0 1 0 1.06-1.06L10.72 9.952A5.5 5.5 0 0 0 6.5 1zm-4 5.5a4 4 0 1 1 8 0 4 4 0 0 1-8 0z" />
          </svg>
          <input type="text" value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search users…"
            className="w-full rounded-lg border border-slate-700 bg-slate-800/60 py-2 pl-9 pr-3 text-sm text-slate-200 placeholder-slate-500 outline-none focus:border-violet-500/60 focus:ring-1 focus:ring-violet-500/15 transition-colors" />
        </div>
        <button onClick={() => setShowCreate(true)}
          className="flex shrink-0 items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 transition-colors">
          <span className="text-base font-light leading-none">+</span>
          New User
        </button>
      </div>

      {/* Error states */}
      {error && isAuthError(error) && <NotAuthorizedBanner />}
      {error && !isAuthError(error) && <p className="text-sm text-red-400">Failed to load users.</p>}

      {/* Loading */}
      {isLoading && <Skeleton rows={3} />}

      {/* Empty state */}
      {!isLoading && !error && filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="mb-4 rounded-full border border-dashed border-slate-700 p-5">
            <svg className="h-8 w-8 text-slate-600" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0zM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
            </svg>
          </div>
          <p className="text-sm font-medium text-slate-400">
            {search ? `No users matching "${search}"` : 'No users yet'}
          </p>
          {!search && <p className="mt-1 text-xs text-slate-600">Hit "New user" to create the first one.</p>}
        </div>
      )}

      {/* User cards */}
      {!isLoading && filtered.length > 0 && (
        <div className="space-y-2">
          {filtered.map((user) => {
            const isExpanded = expandedId === user.id
            const unassigned = roles.filter((r) => !user.roles.includes(r.name))
            return (
              <div key={user.id}
                className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/70 transition-colors hover:border-slate-700">
                {/* Main row */}
                <div className="flex items-center gap-4 px-4 py-3.5">
                  {/* Avatar */}
                  <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white ${avatarColor(user.email || user.phone_number || 'default')}`}>
                    {(user.email || user.phone_number || '?')[0].toUpperCase()}
                  </div>

                  {/* Identity */}
                  <div className="flex-1 min-w-0">
                    <p className="truncate font-mono text-sm text-slate-100">
                      {user.email || user.phone_number || 'No login configured'}
                    </p>
                    {(user.first_name || user.last_name) && (
                      <p className="truncate text-xs text-slate-500 mt-0.5">
                        {[user.first_name, user.last_name].filter(Boolean).join(' ')}
                      </p>
                    )}
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${user.is_active ? 'bg-emerald-900/50 text-emerald-400' : 'bg-slate-700 text-slate-400'}`}>
                        {user.is_active ? 'active' : 'inactive'}
                      </span>
                      {user.roles.map((r) => (
                        <RolePill key={r} label={r} onRemove={() => handleRevoke(user.id, r)} />
                      ))}
                      <button type="button"
                        onClick={() => setExpandedId(isExpanded ? null : user.id)}
                        className="rounded-full border border-dashed border-slate-700 px-2 py-0.5 text-[10px] text-slate-500 hover:border-indigo-500/60 hover:text-indigo-400 transition-colors">
                        + role
                      </button>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-0.5 shrink-0">
                    <button type="button" onClick={() => setEditingUser(user)} title="Edit user"
                      className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-700/60 hover:text-slate-300 transition-colors">
                      <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
                      </svg>
                    </button>
                    <button type="button" onClick={() => handleDelete(user)} title="Delete user"
                      className="rounded-lg p-1.5 text-slate-700 hover:bg-red-900/30 hover:text-red-400 transition-colors">
                      <TrashIcon />
                    </button>
                  </div>
                </div>

                {/* Role-assignment tray */}
                {isExpanded && (
                  <div className="border-t border-slate-800 bg-slate-800/30 px-4 py-3">
                    <p className="mb-2 text-[11px] font-medium uppercase tracking-widest text-slate-500">Assign role</p>
                    <div className="flex flex-wrap gap-1.5">
                      {unassigned.map((r) => (
                        <button key={r.id} type="button" onClick={() => handleAssign(user.id, r.id)}
                          className="rounded-full border border-indigo-700/50 bg-indigo-900/30 px-3 py-1 text-xs text-indigo-300 hover:bg-indigo-900/60 hover:border-indigo-600 transition-colors">
                          {r.name}
                        </button>
                      ))}
                      {unassigned.length === 0 && (
                        <p className="text-xs italic text-slate-500">All roles already assigned</p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {showCreate && (
        <Modal title="New user" onClose={() => setShowCreate(false)}>
          <CreateUserModal onClose={() => setShowCreate(false)} />
        </Modal>
      )}
      {editingUser && (
        <Modal title="Edit user" onClose={() => setEditingUser(null)}>
          <EditUserModal user={editingUser} onClose={() => setEditingUser(null)} />
        </Modal>
      )}
    </div>
  )
}

// ── Roles section ─────────────────────────────────────────────────────────────

const ROLE_ACCENT: [string, string][] = [
  ['border-indigo-700/40 bg-indigo-900/20', 'text-indigo-300'],
  ['border-violet-700/40 bg-violet-900/20', 'text-violet-300'],
  ['border-fuchsia-700/40 bg-fuchsia-900/20', 'text-fuchsia-300'],
  ['border-cyan-700/40 bg-cyan-900/20', 'text-cyan-300'],
  ['border-teal-700/40 bg-teal-900/20', 'text-teal-300'],
]

function RolesSection() {
  const { data: roles = [], isLoading, error } = useIamRoles()
  const deleteRole = useDeleteIamRole()
  const [showCreate, setShowCreate] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editingRole, setEditingRole] = useState<IamRole | null>(null)
  const [search, setSearch] = useState('')

  const filtered = roles.filter((r) => r.name.toLowerCase().includes(search.toLowerCase()))

  const handleDelete = async (role: IamRole) => {
    if (!confirm(`Delete role "${role.name}"? Users with this role will lose its scopes.`)) return
    await deleteRole.mutateAsync(role.id)
  }

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" viewBox="0 0 16 16" fill="currentColor">
            <path d="M6.5 1a5.5 5.5 0 1 0 3.16 10.013l3.163 3.163a.75.75 0 1 0 1.06-1.06L10.72 9.952A5.5 5.5 0 0 0 6.5 1zm-4 5.5a4 4 0 1 1 8 0 4 4 0 0 1-8 0z" />
          </svg>
          <input type="text" value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search roles…"
            className="w-full rounded-lg border border-slate-700 bg-slate-800/60 py-2 pl-9 pr-3 text-sm text-slate-200 placeholder-slate-500 outline-none focus:border-sky-500/60 focus:ring-1 focus:ring-sky-500/15 transition-colors" />
        </div>
        <button onClick={() => setShowCreate(true)}
          className="flex shrink-0 items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 transition-colors">
          <span className="text-base font-light leading-none">+</span>
          New Role
        </button>
      </div>

      {error && isAuthError(error) && <NotAuthorizedBanner />}
      {error && !isAuthError(error) && <p className="text-sm text-red-400">Failed to load roles.</p>}

      {isLoading && <Skeleton rows={2} />}

      {/* Empty state */}
      {!isLoading && !error && filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="mb-4 rounded-full border border-dashed border-slate-700 p-5">
            <svg className="h-8 w-8 text-slate-600" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
            </svg>
          </div>
          <p className="text-sm font-medium text-slate-400">
            {search ? `No roles matching "${search}"` : 'No roles yet'}
          </p>
          {!search && <p className="mt-1 text-xs text-slate-600">Create a role to start granting scopes.</p>}
        </div>
      )}

      {/* Role cards grid */}
      {!isLoading && filtered.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((role, i) => {
            const [cardCls, textCls] = ROLE_ACCENT[i % ROLE_ACCENT.length]
            const isExpanded = expandedId === role.id
            return (
              <div key={role.id} className={`overflow-hidden rounded-xl border ${cardCls}`}>
                <div className="p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <p className={`font-semibold ${textCls}`}>{role.name}</p>
                      {role.description && (
                        <p className="mt-0.5 truncate text-xs text-slate-400">{role.description}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-0.5 shrink-0">
                      <button type="button" onClick={() => setEditingRole(role)} title="Edit scopes"
                        className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-700/60 hover:text-slate-300 transition-colors">
                        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
                        </svg>
                      </button>
                      <button type="button" onClick={() => handleDelete(role)} title="Delete role"
                        className="rounded-lg p-1.5 text-slate-600 hover:bg-red-900/30 hover:text-red-400 transition-colors">
                        <TrashIcon />
                      </button>
                    </div>
                  </div>

                  {/* Scope toggle */}
                  <button type="button"
                    onClick={() => setExpandedId(isExpanded ? null : role.id)}
                    className="mt-3 flex items-center gap-1.5 text-[11px] text-slate-500 hover:text-slate-300 transition-colors">
                    <svg className={`h-3 w-3 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                      viewBox="0 0 16 16" fill="currentColor">
                      <path d="M6 12l4-4-4-4v8z" />
                    </svg>
                    {role.scopes.length === 0
                      ? 'No scopes'
                      : `${role.scopes.length} scope${role.scopes.length !== 1 ? 's' : ''}`}
                  </button>

                  {isExpanded && (
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {role.scopes.length === 0
                        ? <span className="text-xs italic text-slate-600">No scopes assigned</span>
                        : role.scopes.map((s) => <ScopePill key={s} label={s} />)
                      }
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {showCreate && (
        <Modal title="New role" onClose={() => setShowCreate(false)}>
          <CreateRoleModal onClose={() => setShowCreate(false)} />
        </Modal>
      )}
      {editingRole && (
        <Modal title="Edit scopes" onClose={() => setEditingRole(null)}>
          <EditRoleScopesModal role={editingRole} onClose={() => setEditingRole(null)} />
        </Modal>
      )}
    </div>
  )
}

// ── Stat pill ─────────────────────────────────────────────────────────────────

function StatPill({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-baseline gap-1.5 rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-2.5">
      <span className="text-lg font-semibold tabular-nums text-slate-100">{value}</span>
      <span className="text-xs text-slate-500">{label}</span>
    </div>
  )
}

// ── Page shell ────────────────────────────────────────────────────────────────

type Tab = 'users' | 'roles'

export function IamPage() {
  const [tab, setTab] = useState<Tab>('users')
  const { data: users = [] } = useIamUsers()
  const { data: roles = [] } = useIamRoles()

  const activeUsers = users.filter((u) => u.is_active).length
  const totalScopes = roles.reduce((acc, r) => acc + r.scopes.length, 0)

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <TopBar title="IAM" />

      <div className="flex-1 overflow-auto">
        {/* Summary strip */}
        <div className="flex items-center gap-3 border-b border-slate-800 px-6 py-3">
          <StatPill label="total users" value={users.length} />
          <StatPill label="active" value={activeUsers} />
          <StatPill label="roles" value={roles.length} />
          <StatPill label="scopes" value={totalScopes} />
        </div>

        {/* Segmented tabs */}
        <div className="px-6 pt-5">
          <div className="inline-flex rounded-lg border border-slate-800 bg-slate-900 p-0.5">
            {(['users', 'roles'] as Tab[]).map((t) => (
              <button key={t} type="button" onClick={() => setTab(t)}
                className={`rounded-md px-5 py-1.5 text-sm font-medium capitalize transition-all ${
                  tab === t
                    ? 'bg-slate-700 text-slate-100 shadow-sm'
                    : 'text-slate-500 hover:text-slate-300'
                }`}>
                {t}
              </button>
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="px-6 py-5">
          {tab === 'users' && <UsersSection roles={roles} />}
          {tab === 'roles' && <RolesSection />}
        </div>
      </div>
    </div>
  )
}
