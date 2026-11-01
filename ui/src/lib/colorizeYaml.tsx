/**
 * Shared YAML syntax colorizer (TD-29).
 *
 * `colorizeValue` / `renderColorizedYaml` were previously copy-pasted verbatim
 * (modulo cosmetic variable-name/formatting differences) across ~8 files.
 * Five of the eight copies (Datasources, Federation, Settings, Models,
 * WorkflowCanvas) additionally colorize `- ` sequence-marker lines; the other
 * three (Embeddings, Collections, AgentModels) predate that branch and never
 * render arrays in their single-entry preview. `colorizeListItems` preserves
 * that split so behavior stays identical per caller.
 *
 * Lives under lib/ (not components/) so this plain-function module doesn't
 * mix with the `<ColorizedYaml>` component export and trip up Vite Fast
 * Refresh (react-refresh/only-export-components).
 */
import type { ReactElement } from 'react'

/** Colorizes a single scalar YAML value (already split off its key/marker). */
export function colorizeValue(val: string): ReactElement {
  if (!val) return <></>
  if (
    (val.startsWith("'") && val.endsWith("'")) ||
    (val.startsWith('"') && val.endsWith('"'))
  ) return <span className="text-yaml-quoted">{val}</span>
  if (/^-?\d+(\.\d+)?$/.test(val)) return <span className="text-yaml-num">{val}</span>
  if (val === 'true' || val === 'false') return <span className="text-yaml-bool">{val}</span>
  if (val === 'null' || val === '~') return <span className="text-yaml-null">{val}</span>
  return <span className="text-yaml-str">{val}</span>
}

/**
 * Splits a dumped YAML string into an array of syntax-highlighted line spans.
 *
 * @param colorizeListItems Handle `- ` sequence markers with their own span
 *   + recursive value colorization. Defaults to `true` (5 of the 8 original
 *   copies). Pass `false` to reproduce the 3 older copies that lack this
 *   branch (such lines fall through to the default/key-value handling).
 */
export function renderColorizedYaml(yaml: string, colorizeListItems = true): ReactElement[] {
  const lines = yaml.split('\n')
  if (lines[lines.length - 1] === '') lines.pop()
  return lines.map((line, i) => {
    if (!line) return <span key={i} className="block">&nbsp;</span>
    const il = line.search(/\S/)
    const indent = il > 0 ? line.slice(0, il) : ''
    const rest = il >= 0 ? line.slice(il) : line
    if (rest.startsWith('#'))
      return <span key={i} className="block"><span>{indent}</span><span className="text-yaml-comment">{rest}</span></span>
    if (colorizeListItems && rest.startsWith('- '))
      return <span key={i} className="block"><span>{indent}</span><span className="text-yaml-list">- </span>{colorizeValue(rest.slice(2))}</span>
    const ci = rest.indexOf(': ')
    const isKeyOnly = rest.endsWith(':') && !rest.includes(': ')
    if (ci > -1)
      return <span key={i} className="block"><span>{indent}</span><span className="text-yaml-key">{rest.slice(0, ci)}</span><span className="text-yaml-list">: </span>{colorizeValue(rest.slice(ci + 2))}</span>
    if (isKeyOnly)
      return <span key={i} className="block"><span>{indent}</span><span className="text-yaml-key">{rest}</span></span>
    return <span key={i} className="block"><span>{indent}</span><span className="text-yaml-default">{rest}</span></span>
  })
}
