import { useState } from 'react'
import { ArtifactSelect } from './ArtifactPicker'
import { SITE_TYPES } from './artifactRefs'
import { Row, TextField } from './fields'
import { inputClass } from './styles'

type Tool = Record<string, unknown>
const isMcp = (t: unknown): t is Tool => !!t && typeof t === 'object' && typeof (t as Tool).mcp === 'string'
const names = (v: string) => v.split(',').map((s) => s.trim()).filter(Boolean)

/** The MCP servers a loop may call: each a stored `mcp` artifact with the tool names it is allowed to use. */
export function McpServers({ tools, onChange }: { tools: unknown[]; onChange: (tools: unknown[]) => void }) {
  const [server, setServer] = useState('')
  const [allow, setAllow] = useState('')
  const replace = (i: number, next: Tool | null) =>
    onChange(next ? tools.map((t, k) => (k === i ? next : t)) : tools.filter((_, k) => k !== i))
  return (
    <Row label="MCP servers" hint="Stored MCP artifacts the loop may call, with an explicit allow-list of tool names">
      <div className="space-y-2">
        {tools.map((t, i) => isMcp(t) && (
          <div key={i} className="rounded border border-slate-800 p-1.5 space-y-1">
            <div className="flex gap-1 items-start">
              <div className="flex-1 min-w-0">
                <ArtifactSelect label={`MCP server ${i + 1}`} types={SITE_TYPES.mcp} value={t.mcp as string}
                  onChange={(ref) => ref && replace(i, { ...t, mcp: ref })} />
              </div>
              <button className="text-slate-500 hover:text-rose-400 px-1 pt-1" aria-label={`Remove MCP server ${i + 1}`}
                onClick={() => replace(i, null)}>✕</button>
            </div>
            <TextField mono value={Array.isArray(t.allow) ? (t.allow as string[]).join(', ') : ''} ariaLabel={`MCP server ${i + 1} allowed tools`}
              placeholder="allowed tool names, comma-separated"
              onCommit={(v) => names(v).length && replace(i, { ...t, allow: names(v) })} />
          </div>
        ))}
        <div className="space-y-1">
          <ArtifactSelect label="New MCP server" types={SITE_TYPES.mcp} value={server} emptyLabel="+ add a server…" onChange={setServer} />
          {server && (
            <div className="flex gap-1">
              <input aria-label="New MCP server allowed tools" className={`${inputClass} font-mono`} value={allow}
                placeholder="allowed tool names, comma-separated" onChange={(e) => setAllow(e.target.value)} />
              <button className={`${inputClass} !w-auto shrink-0`} disabled={!names(allow).length}
                onClick={() => { onChange([...tools, { mcp: server, allow: names(allow) }]); setServer(''); setAllow('') }}>Add</button>
            </div>
          )}
        </div>
      </div>
    </Row>
  )
}
