import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CodeEditor, type LineIssue } from '../components/CodeEditor'
import { readText, specCheck, writeText } from '../devApi'
import { announceSpecSaved } from './channel'

/** One spec in its own window (opened from the Specs page); saving refreshes the page's status. */
export function SpecEditorWindow() {
  const { name = '' } = useParams()
  const qc = useQueryClient()
  const text = useQuery({ queryKey: ['dev', 'text', 'specs', name], queryFn: () => readText('specs', name), enabled: !!name })
  const [draft, setDraft] = useState<string | null>(null)
  const value = draft ?? text.data ?? ''
  const dirty = draft !== null && draft !== text.data
  const check = useQuery({ queryKey: ['dev', 'specs', 'check', name], queryFn: () => specCheck(`specs/${name}`), enabled: !!name })
  // spec check runs on the saved file: show its findings until the next edit
  const issues = useMemo<LineIssue[]>(
    () => (dirty ? [] : (check.data?.specs[0]?.findings ?? []).filter((f) => !f.file && f.severity !== 'waived')
      .map((f) => ({ line: f.line, message: `${f.code} ${f.message}`, severity: f.severity as LineIssue['severity'] }))),
    [check.data, dirty],
  )

  const save = useMutation({
    mutationFn: () => writeText('specs', name, value),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['dev', 'text', 'specs', name] })
      await qc.invalidateQueries({ queryKey: ['dev', 'specs', 'check', name] })
      setDraft(null)
      announceSpecSaved(name)
    },
  })

  useEffect(() => {
    document.title = `${dirty ? '● ' : ''}${name.replace(/\.md$/, '')} — spec`
  }, [name, dirty])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault()
        if (dirty && !save.isPending) save.mutate()
      }
    }
    const onLeave = (e: BeforeUnloadEvent) => {
      if (dirty) e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('beforeunload', onLeave)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('beforeunload', onLeave)
    }
  }, [dirty, save])

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-100">
      <header className="flex items-center gap-3 px-4 py-2 border-b border-slate-800 text-xs">
        <span className="font-mono text-sm text-slate-200">{name.replace(/\.md$/, '')}</span>
        <span className="text-slate-500">specs/{name}</span>
        <span className="flex-1" />
        {save.isError && <span className="text-rose-400">{(save.error as Error).message}</span>}
        {dirty && <span className="text-amber-400">unsaved</span>}
        {!dirty && check.data?.specs[0] && (
          <span className={check.data.specs[0].errors ? 'text-rose-400' : 'text-emerald-400'}>
            spec check: {check.data.specs[0].errors} blocking · {check.data.specs[0].warnings} warning(s)
          </span>
        )}
        <span className="text-slate-600">⌘S</span>
        <button
          className="px-2.5 py-1 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40"
          disabled={!dirty || save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending ? 'Saving…' : 'Save'}
        </button>
      </header>
      <div className="flex-1 min-h-0">
        {text.isError ? (
          <p className="p-6 text-sm text-rose-400">Could not open specs/{name}.</p>
        ) : (
          <CodeEditor value={value} language="markdown" issues={issues} onChange={setDraft} />
        )}
      </div>
    </div>
  )
}
