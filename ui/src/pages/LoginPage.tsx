import { type FormEvent, useState } from 'react'
import { useUIStore } from '../store'

const KEY_RE = /^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/

/** Auto-format raw alphanumeric input into XXXX-XXXX-XXXX-XXXX */
function formatKey(raw: string): string {
  const clean = raw.replace(/[^A-Z0-9]/gi, '').toUpperCase().slice(0, 16)
  if (clean.length > 12) return `${clean.slice(0, 4)}-${clean.slice(4, 8)}-${clean.slice(8, 12)}-${clean.slice(12)}`
  if (clean.length > 8) return `${clean.slice(0, 4)}-${clean.slice(4, 8)}-${clean.slice(8)}`
  if (clean.length > 4) return `${clean.slice(0, 4)}-${clean.slice(4)}`
  return clean
}

export function LoginPage() {
  const setDevKey = useUIStore((s) => s.setDevKey)
  const existingKey = useUIStore((s) => s.devKey)
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setError(null)
    setInput(formatKey(e.target.value))
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!KEY_RE.test(input)) {
      setError('Key must be in XXXX-XXXX-XXXX-XXXX format (letters and numbers).')
      return
    }
    setLoading(true)
    setError(null)
    // Revoke-on-login: if a stale key is in storage, clear it before we
    // attempt to authenticate with a new one.  This prevents a brief window
    // where two valid keys coexist in the tab and avoids accidentally reusing
    // the old key if the new ``setDevKey`` call races a concurrent request.
    if (existingKey && existingKey !== input) {
      setDevKey(null)
    }
    try {
      const resp = await fetch('/dev/ping', {
        headers: { Authorization: `Bearer ${input}` },
      })
      if (resp.status === 401) {
        setError('Incorrect key. Copy the key printed in your terminal.')
      } else if (resp.status === 403) {
        setError('Access denied. The UI must be opened on localhost.')
      } else if (!resp.ok) {
        setError(`Unexpected error (${resp.status}).`)
      } else {
        setDevKey(input)
      }
    } catch {
      setError('Cannot reach the engine. Is `tuvl dev` running?')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950">
      <div className="w-full max-w-sm px-4">
        {/* Logo / wordmark */}
        <div className="mb-8 flex flex-col items-center gap-1">
          <img src={`${import.meta.env.BASE_URL}tuvl-dotted.svg`} alt="tuvl" className="w-20 h-20 object-contain" />
          <span className="text-3xl font-bold tracking-tight text-slate-100">tuvl <span className="text-cyan-400">insight</span></span>
          <span
            lang="ml"
            title="തൂവൽ — “feather” in Malayalam, the name tuvl is drawn from"
            className="text-lg leading-none text-cyan-500/70 select-none"
          >
            തൂവൽ
          </span>
          <span className="text-xs text-slate-500 italic">( Thoo-val )</span>
          <p className="mt-1 text-sm text-slate-400">dev console</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-xl border border-slate-800 bg-slate-900 px-6 py-8 shadow-xl"
        >
          <h1 className="mb-1 text-base font-semibold text-slate-100">Enter your security key</h1>
          <p className="mb-6 text-xs text-slate-400">
            Run <code className="rounded bg-slate-800 px-1 py-0.5 font-mono text-slate-200">tuvl dev</code> in
            your terminal and copy the key shown there.
          </p>

          <label className="mb-1.5 block text-xs font-medium text-slate-400" htmlFor="key-input">
            Security key
          </label>
          <input
            id="key-input"
            type="text"
            value={input}
            onChange={handleChange}
            placeholder="A1B2-C3D4-E5F6-G7H8"
            maxLength={19}
            autoComplete="off"
            autoFocus
            spellCheck={false}
            className={`w-full rounded-lg border bg-slate-800 px-4 py-3 text-center font-mono text-lg tracking-widest text-slate-100 outline-none transition-colors placeholder:text-slate-600 focus:ring-2 ${
              error
                ? 'border-rose-500 focus:ring-rose-500/40'
                : 'border-slate-700 focus:border-sky-500 focus:ring-sky-500/30'
            }`}
          />

          {error && (
            <p className="mt-2 text-xs text-rose-400">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading || input.length < 19}
            className="mt-5 w-full rounded-lg bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loading ? 'Connecting…' : 'Connect'}
          </button>
        </form>
      </div>
    </div>
  )
}
