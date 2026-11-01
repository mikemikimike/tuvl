import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { uploadIdea } from '../devApi'
import type { IdeaSummary, IdeasMe } from '../devApi'
import { INITIALS, parseLinks, pickedFrom } from './ideaUpload'
import type { Picked } from './ideaUpload'

export function UploadIdea({ me, ideas, onClose, onDone }: { me: IdeasMe; ideas: IdeaSummary[]; onClose: () => void; onDone: (id: string) => void }) {
  const qc = useQueryClient()
  const [picked, setPicked] = useState<Picked[]>([])
  const [text, setText] = useState('')
  const [linkText, setLinkText] = useState('')
  const [internal, setInternal] = useState(false)
  const [title, setTitle] = useState('')
  const [supersedes, setSupersedes] = useState('')
  const [initials, setInitials] = useState('')
  const [commit, setCommit] = useState(false)
  const [over, setOver] = useState(false)
  const files = useRef<HTMLInputElement>(null)
  const folder = useRef<HTMLInputElement>(null)

  // read the files out of the event now: an input is cleared, and a drop's data is gone, once the handler returns
  const add = (list: FileList | null) => {
    const added = list ? pickedFrom(list) : []
    if (added.length > 0) setPicked((old) => [...old, ...added])
  }

  const needInitials = !me.initials
  const { links, bad } = parseLinks(linkText)
  const ready = (picked.length > 0 || text.trim() !== '' || links.length > 0) && bad.length === 0 && (!needInitials || INITIALS.test(initials))
  const send = useMutation({
    mutationFn: () => {
      const form = new FormData()
      for (const p of picked) form.append('files', p.file, p.name)
      if (text.trim()) form.append('text', text)
      for (const link of links) form.append('urls', link)
      if (links.length > 0 && internal) form.append('allow_private', 'true')
      if (title.trim()) form.append('title', title.trim())
      if (supersedes) form.append('supersedes', supersedes)
      if (needInitials) form.append('initials', initials.trim().toUpperCase())
      if (commit) form.append('commit', 'true')
      return uploadIdea(form)
    },
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['dev'] })
      onDone(r.id)
    },
  })

  const field = 'w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 placeholder-slate-600'
  const label = 'block text-[11px] uppercase tracking-wide text-slate-500 mb-1'
  const btn = 'px-3 py-1.5 rounded text-xs bg-slate-700 hover:bg-slate-600 disabled:opacity-40'
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-label="Upload an idea">
      <div className="w-full max-w-xl max-h-full overflow-auto rounded-xl border border-slate-700 bg-slate-950 p-5 flex flex-col gap-4">
        <h3 className="text-sm font-semibold text-slate-100">Upload an idea</h3>
        <p className="text-xs text-slate-500 leading-relaxed">
          An idea is the brief a spec is written from: notes, a PRD, mail, a spreadsheet export, a web page or a ticket. It is copied into <code>idea/</code> as a numbered,
          immutable record (what <code>tuvl import idea</code> does). Text from .pdf and .docx files is extracted.
        </p>

        <div
          onDragOver={(e) => { e.preventDefault(); setOver(true) }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files) }}
          className={`rounded border border-dashed p-4 text-center text-xs ${over ? 'border-indigo-400 bg-indigo-500/10' : 'border-slate-700'}`}
        >
          <p className="text-slate-400">Drop files here, or</p>
          <div className="mt-2 flex justify-center gap-2">
            <button className={btn} onClick={() => files.current?.click()}>Choose files</button>
            <button className={btn} onClick={() => folder.current?.click()}>Choose a folder</button>
          </div>
          <input ref={files} type="file" multiple className="hidden" aria-label="Idea files"
            onChange={(e) => { add(e.target.files); e.target.value = '' }} />
          <input ref={folder} type="file" multiple className="hidden" aria-label="Idea folder"
            {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
            onChange={(e) => { add(e.target.files); e.target.value = '' }} />
        </div>
        {picked.length > 0 && (
          <ul className="max-h-28 overflow-auto text-xs text-slate-300 space-y-0.5" aria-label="Files to upload">
            {picked.map((p, i) => (
              <li key={`${p.name}-${i}`} className="flex items-center gap-2">
                <span className="font-mono truncate">{p.name}</span>
                <span className="text-slate-500">{(p.file.size / 1024).toFixed(1)} KB</span>
                <button className="ml-auto text-slate-500 hover:text-rose-300" aria-label={`Remove ${p.name}`} onClick={() => setPicked((old) => old.filter((_, j) => j !== i))}>✕</button>
              </li>
            ))}
          </ul>
        )}

        <div>
          <label className={label} htmlFor="idea-text">Or write it here</label>
          <textarea id="idea-text" className={`${field} h-24 font-mono`} value={text} onChange={(e) => setText(e.target.value)}
            placeholder={'# Refund automation\n\nCustomers get a refund when…'} />
        </div>

        <div>
          <label className={label} htmlFor="idea-links">Or add links (one per line)</label>
          <textarea id="idea-links" className={`${field} h-16 font-mono`} value={linkText} onChange={(e) => setLinkText(e.target.value)}
            placeholder={'https://acme.atlassian.net/browse/PAY-123\nhttps://github.com/acme/app/issues/42\nhttps://example.com/spec'} />
          <p className="mt-1 text-[11px] text-slate-500">
            A web page, a Jira issue, a Confluence page or a GitHub issue is saved as a snapshot, taken now. Jira, Confluence and private GitHub need a token in the
            environment of the process that runs Insight (<code>TUVL_ATLASSIAN_EMAIL</code> + <code>TUVL_ATLASSIAN_TOKEN</code>, <code>TUVL_ATLASSIAN_PAT</code>,
            <code> TUVL_GITHUB_TOKEN</code>).
          </p>
          {bad.length > 0 && <p role="alert" className="mt-1 text-[11px] text-rose-400">Not a link: {bad.join(', ')}</p>}
          {links.length > 0 && (
            <label className="mt-1 flex items-start gap-2 text-[11px] text-slate-400">
              <input type="checkbox" className="mt-0.5" checked={internal} onChange={(e) => setInternal(e.target.checked)} />
              <span>These are on my own network (an internal Jira or wiki): allow internal addresses.</span>
            </label>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={label} htmlFor="idea-title">Title (optional)</label>
            <input id="idea-title" className={field} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="the first heading" />
          </div>
          <div>
            <label className={label} htmlFor="idea-supersedes">Replaces (optional)</label>
            <select id="idea-supersedes" className={field} value={supersedes} onChange={(e) => setSupersedes(e.target.value)}>
              <option value="">nothing</option>
              {ideas.map((i) => <option key={i.id} value={i.id}>{i.id} · {i.title.slice(0, 40)}</option>)}
            </select>
          </div>
        </div>

        {needInitials && (
          <div>
            <label className={label} htmlFor="idea-initials">Your initials</label>
            <input id="idea-initials" className={`${field} w-28 uppercase`} value={initials} maxLength={4} onChange={(e) => setInitials(e.target.value)} placeholder="AB" />
            <p className="mt-1 text-[11px] text-slate-500">2 to 4 letters or digits. Ideas are numbered with them (IDEA-AB-0001); they are saved in .tuvl/agent.yaml.</p>
          </div>
        )}

        <label className="flex items-start gap-2 text-xs text-slate-400">
          <input type="checkbox" className="mt-0.5" checked={commit} onChange={(e) => setCommit(e.target.checked)} />
          <span>Commit it to git. Needed to write the spec on a branch; not needed to write it into this project.</span>
        </label>

        {send.error && <p role="alert" className="text-xs text-rose-400 whitespace-pre-wrap">{(send.error as Error).message}</p>}
        <div className="flex justify-end gap-2">
          <button className={btn} onClick={onClose}>Cancel</button>
          <button className={`${btn} bg-indigo-700 hover:bg-indigo-600`} disabled={!ready || send.isPending} onClick={() => send.mutate()}>
            {send.isPending ? 'Importing…' : 'Import idea'}
          </button>
        </div>
      </div>
    </div>
  )
}
