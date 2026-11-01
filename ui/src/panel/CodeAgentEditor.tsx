import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../api'
import { CodeEditor, type LineIssue } from '../components/CodeEditor'
import { FloatingWindow } from '../components/FloatingWindow'
import { agentSource, assistCode, assistModels, saveAgentSource, type AssistMessage } from '../devApi'

function detail(e: unknown): { message: string; line: number | null } {
  if (e instanceof ApiError) {
    const d = (e.body as { detail?: unknown } | null)?.detail
    if (d && typeof d === 'object') {
      const o = d as { error?: string; line?: number | null }
      return { message: o.error ?? e.message, line: o.line ?? null }
    }
    if (typeof d === 'string') return { message: d, line: null }
  }
  return { message: (e as Error).message, line: null }
}

/** AI help writing the body: the contract and the agent-code skill go with every turn. */
function Assistant({ run, code, agent, onCode }: { run: string; code: string; agent?: Record<string, unknown>; onCode: (next: string) => void }) {
  const models = useQuery({ queryKey: ['dev', 'assist-models'], queryFn: assistModels })
  const usable = (models.data ?? []).filter((m) => m.configured)
  const [model, setModel] = useState<string>('')
  const chosen = model || usable.find((m) => m.name === 'default')?.name || usable[0]?.name || ''
  const [messages, setMessages] = useState<AssistMessage[]>([])
  const [prompt, setPrompt] = useState('')
  const [previous, setPrevious] = useState<string | null>(null)
  const end = useRef<HTMLDivElement>(null)
  // a block body: Chromium's scrollIntoView may return a promise, which React would call as a cleanup
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  const ask = useMutation({
    mutationFn: (text: string) => assistCode(run, { prompt: text, code, model: chosen || undefined, messages, agent }),
    onSuccess: (r, text) => {
      setMessages((m) => [...m, { role: 'user', content: text }, { role: 'assistant', content: r.reply, code: r.code }])
      if (r.code) {
        setPrevious(code)
        onCode(r.code)
      }
    },
    onError: (e, text) => setMessages((m) => [...m, { role: 'user', content: text }, { role: 'assistant', content: `⚠ ${detail(e).message}` }]),
  })
  const send = () => {
    const text = prompt.trim()
    if (!text || ask.isPending) return
    setPrompt('')
    ask.mutate(text)
  }

  return (
    <div className="flex flex-col h-full min-h-0 text-xs">
      <div className="flex items-center gap-2 px-2 py-1.5 border-b border-slate-800">
        <span className="text-slate-300 font-medium">✦ Assist</span>
        <select aria-label="Assist model" value={chosen} onChange={(e) => setModel(e.target.value)}
          className="ml-auto bg-slate-900 border border-slate-700 rounded px-1 py-0.5 text-[11px]">
          {(models.data ?? []).map((m) => (
            <option key={m.name} value={m.name} disabled={!m.configured}>
              {m.name} · {m.model}{m.configured ? '' : ` — needs ${m.missing.join(', ') || 'setup'}`}
            </option>
          ))}
        </select>
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-2 space-y-2">
        {usable.length === 0 && models.isSuccess && (
          <p className="text-amber-400">No configured LLM in llms/ — set its key in .env (see <code>tuvl doctor</code>).</p>
        )}
        {messages.length === 0 && usable.length > 0 && (
          <p className="text-slate-500">
            Ask for a change — e.g. “return forbidden when the community is inactive”. The assistant knows this agent&apos;s
            contract and returns the whole file into the editor; nothing is saved until you press Save Python.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-slate-200' : 'text-slate-300 bg-slate-800/60 rounded p-2'}>
            <p className="whitespace-pre-wrap">{m.role === 'user' ? `› ${m.content}` : m.content}</p>
            {m.code && <p className="mt-1 text-emerald-400">Inserted into the editor — review, then Save Python.</p>}
          </div>
        ))}
        {ask.isPending && <p className="text-slate-500">Thinking with {chosen}…</p>}
        <div ref={end} />
      </div>
      {previous !== null && (
        <button className="mx-2 mb-1 text-[11px] text-slate-400 hover:text-slate-200 text-left" onClick={() => { onCode(previous); setPrevious(null) }}>
          ↶ Undo the last insert
        </button>
      )}
      <form className="flex gap-1 p-2 border-t border-slate-800" onSubmit={(e) => { e.preventDefault(); send() }}>
        <textarea aria-label="Ask the assistant" rows={2} value={prompt} disabled={!chosen}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send() } }}
          placeholder={chosen ? 'Describe the change (⌘↵ to send)' : 'No model available'}
          className="flex-1 resize-none bg-slate-900 border border-slate-700 rounded px-2 py-1" />
        <button type="submit" disabled={!chosen || ask.isPending || !prompt.trim()} className="px-2 rounded bg-indigo-600 disabled:opacity-40">Send</button>
      </form>
    </div>
  )
}

const typeText = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v))

/** What the function must take and give back, beside the editor in the window. */
function ContractColumn({ agent }: { agent?: Record<string, unknown> }) {
  const map = (v: unknown) => (v && typeof v === 'object' && !Array.isArray(v) ? Object.entries(v as Record<string, unknown>) : [])
  const signals = map(agent?.routes).map(([k]) => k).filter((k) => k !== 'error')
  const fields = (rows: [string, unknown][]) => rows.map(([k, v]) => (
    <p key={k} className="flex flex-wrap justify-between gap-x-2 font-mono leading-snug py-0.5">
      <span className="text-slate-200 break-all">{k}</span><span className="text-sky-300 break-all text-right ml-auto">{typeText(v)}</span>
    </p>
  ))
  const section = (title: string, rows: [string, unknown][]) => {
    // outputs keyed by signal (`default: { flag: Flag }`) list each signal's fields under it
    const perSignal = rows.length > 0 && rows.every(([, v]) => v && typeof v === 'object' && !Array.isArray(v))
    return (
      <div>
        <p className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">{title}</p>
        {rows.length === 0 ? <p className="text-slate-600">—</p> : perSignal ? rows.map(([sig, v]) => (
          <div key={sig} className="mb-1.5">
            <p className="text-slate-400">on <span className="font-mono text-slate-300">{sig}</span></p>
            <div className="pl-2 border-l border-slate-800">{fields(map(v))}</div>
          </div>
        )) : fields(rows)}
      </div>
    )
  }
  return (
    <div className="space-y-4 text-[11px]">
      {section('Inputs', map(agent?.inputs))}
      {section('Outputs', map(agent?.outputs))}
      <div>
        <p className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Signals</p>
        <div className="flex flex-wrap gap-1">{signals.map((sg) => <span key={sg} className="font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-200">{sg}</span>)}</div>
      </div>
      {typeof agent?.effect === 'string' && section('Effect', [['effect', agent.effect]])}
    </div>
  )
}

/** A code agent's Python, editable in Insight; saving lets codegen keep the contract's signature. */
/** `agent` is the agent as the canvas has it: an unsaved draft has no saved contract yet. */
export function CodeAgentEditor({ run, agent }: { run: string; agent?: Record<string, unknown> }) {
  const qc = useQueryClient()
  const description = typeof agent?.description === 'string' ? agent.description : ''
  const source = useQuery({ queryKey: ['dev', 'agent-source', run], queryFn: () => agentSource(run, description), retry: false })
  const [draft, setDraft] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [assistOpen, setAssistOpen] = useState(false)
  const [contractOpen, setContractOpen] = useState(true)
  const [status, setStatus] = useState<{ kind: 'ok' | 'warn' | 'error'; text: string; line?: number | null } | null>(null)

  const saved = source.data?.file_text ?? ''
  const text = draft ?? saved
  const isNew = source.data?.exists === false
  const dirty = isNew || (draft !== null && draft !== saved)
  const save = useMutation({
    mutationFn: () => saveAgentSource(run, text),
    onSuccess: async (r) => {
      setDraft(null)
      qc.setQueryData(['dev', 'agent-source', run], { ...r, exists: true })
      setStatus(r.load_error ? { kind: 'error', text: `Saved, but it doesn't import: ${r.load_error}` }
        : r.note ? { kind: 'warn', text: `Saved — ${r.note}.` } : { kind: 'ok', text: 'Saved and reloaded.' })
      await qc.invalidateQueries({ queryKey: ['dev', 'validate'] })
    },
    onError: (e) => { const d = detail(e); setStatus({ kind: 'error', text: d.message, line: d.line }) },
  })
  const doSave = () => { if (dirty && !save.isPending) save.mutate() }

  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setExpanded(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  if (source.isLoading) return <p className="text-[11px] text-slate-500">Loading {run}…</p>
  if (source.isError) return <p className="text-[11px] text-amber-400">{detail(source.error).message}</p>
  if (source.data?.builtin) {
    return <p className="text-[11px] text-slate-400">Built-in <span className="font-mono">{run}</span> — configured by <span className="font-mono">code.with</span>; no project Python.</p>
  }

  const issues: LineIssue[] = status?.kind === 'error' && status.line ? [{ line: status.line, message: status.text, severity: 'error' }] : []
  const btn = 'px-2.5 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40'
  const toolbar = (
    <div className="space-y-1.5 text-xs">
      <div className="flex items-center gap-2">
        <span className="font-mono text-slate-300 truncate">{source.data?.file}</span>
        {dirty && <span className="text-amber-400 shrink-0">● unsaved</span>}
      </div>
      <div className="flex items-center gap-1.5 flex-wrap">
        <button className="px-2.5 py-1 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white" disabled={!dirty || save.isPending} onClick={doSave} title="⌘S">
          {save.isPending ? 'Saving…' : 'Save Python'}
        </button>
        <button className={btn} disabled={!dirty} onClick={() => { setDraft(null); setStatus(null) }}>Revert</button>
        <span className="flex-1" />
        <button className={assistOpen ? `${btn} bg-slate-500` : btn} onClick={() => setAssistOpen((o) => !o)}>✦ Assist</button>
        {expanded && <button className={contractOpen ? `${btn} bg-slate-500` : btn} onClick={() => setContractOpen((o) => !o)}>Contract</button>}
        <button className={btn} onClick={() => setExpanded((x) => !x)} title={expanded ? 'Esc' : 'A window you can move, resize and maximize, with the assistant beside the code'}>
          {expanded ? '⤡ Back to panel' : '⤢ Open editor'}
        </button>
      </div>
    </div>
  )
  const fresh = isNew && !status && (
    <p className="text-[11px] text-sky-300">
      New: <span className="font-mono">{source.data?.file}</span> doesn&apos;t exist yet — this is codegen&apos;s stub. Write the body (or ask ✦ Assist); Save Python creates the file.
    </p>
  )
  const note = status && (
    <p className={`text-[11px] ${status.kind === 'ok' ? 'text-emerald-400' : status.kind === 'warn' ? 'text-amber-400' : 'text-rose-400'}`}>
      {status.text}{status.line ? ` (line ${status.line})` : ''}
    </p>
  )
  const editor = (height: string) => (
    <div
      className={`rounded border border-slate-700 overflow-hidden ${height === '100%' ? 'flex-1 min-h-0' : ''}`}
      onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); doSave() } }}
    >
      <CodeEditor value={text} language="python" issues={issues} onChange={setDraft} height={height} />
    </div>
  )

  if (expanded) {
    return (
      <>
        <p className="text-[11px] text-slate-400">
          Editing <span className="font-mono">{source.data?.file}</span> in its own window.{' '}
          <button className="text-indigo-300 hover:underline" onClick={() => setExpanded(false)}>⤡ Back to panel</button>
        </p>
        <FloatingWindow label={`Edit ${run}`} storageKey="tuvl.codeWindow" onClose={() => setExpanded(false)}
          title={<><span className="font-mono text-slate-100">{run}</span><span className="font-mono text-slate-500 truncate">{source.data?.file}</span>{dirty && <span className="text-amber-400">● unsaved</span>}</>}>
          <div className="flex flex-col h-full p-3 gap-2">
            {toolbar}
            {fresh}
            {note}
            <div className="flex flex-1 min-h-0 gap-2">
              {contractOpen && <aside aria-label="Contract" className="w-64 shrink-0 overflow-auto rounded border border-slate-800 bg-slate-900/60 p-3"><ContractColumn agent={agent} /></aside>}
              <div className="flex-1 min-w-0 min-h-0 flex flex-col">{editor('100%')}</div>
              {assistOpen && <div className="w-[360px] shrink-0 rounded border border-slate-700"><Assistant run={run} code={text} agent={agent} onCode={setDraft} /></div>}
            </div>
          </div>
        </FloatingWindow>
      </>
    )
  }
  return (
    <div className="space-y-1">
      <p className="text-[11px] text-slate-400">Python — the body is yours; <span className="font-mono">tuvl codegen</span> keeps the decorator and signature.</p>
      {toolbar}
      {fresh}
      {note}
      {editor(assistOpen ? '320px' : 'calc(100vh - 21rem)')}
      {assistOpen && <div className="h-80 rounded border border-slate-700"><Assistant run={run} code={text} agent={agent} onCode={setDraft} /></div>}
    </div>
  )
}
