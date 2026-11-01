// Spec editor windows and the Specs page talk over one BroadcastChannel (same origin only).
const CHANNEL = 'tuvl-specs'

export function announceSpecSaved(name: string): void {
  const channel = new BroadcastChannel(CHANNEL)
  channel.postMessage({ type: 'saved', name })
  channel.close()
}

export function onSpecSaved(handler: (name: string) => void): () => void {
  const channel = new BroadcastChannel(CHANNEL)
  channel.onmessage = (e: MessageEvent<{ type: string; name: string }>) => {
    if (e.data?.type === 'saved') handler(e.data.name)
  }
  return () => channel.close()
}

const FEATURES = 'popup,width=960,height=900'

export function specEditorUrl(name: string): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, '')
  return `${base}/specs/edit/${encodeURIComponent(name)}`
}

/** Opens (or focuses) the editor window for one spec; one window per spec. */
export function openSpecEditor(name: string): void {
  window.open(specEditorUrl(name), `tuvl-spec-${name}`, FEATURES)
}

/** A blank editor window opened during the user's click, pointed at a spec once it exists
 * (browsers block windows opened after an await). */
export function reserveSpecEditor(): Window | null {
  return window.open('about:blank', '_blank', FEATURES)
}

export function taskWindowUrl(spec: string, id: string): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, '')
  return `${base}/specs/task/${encodeURIComponent(spec)}/${encodeURIComponent(id)}`
}

/** Opens (or focuses) one task in its own window. */
export function openTaskWindow(spec: string, id: string): void {
  window.open(taskWindowUrl(spec, id), `tuvl-task-${id}`, FEATURES)
}
