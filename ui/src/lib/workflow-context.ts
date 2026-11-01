// Pure flow↔YAML conversion helpers extracted from WorkflowCanvas.tsx so they
// can be unit-tested without pulling in React/ReactFlow. Behavior-preserving
// extraction — no logic changes vs. the code that used to live inline there.

/** A scheduled run's input value as typed text → the YAML value the trigger input type expects. */
export function coerceInput(type: string, text: string): unknown {
  const t = text.trim()
  if (t === '') return undefined
  const base = type.replace(/\?$/, '').trim()
  if (base === 'int') return /^-?\d+$/.test(t) ? Number(t) : t
  if (base === 'float' || base === 'decimal') return Number.isFinite(Number(t)) ? Number(t) : t
  if (base === 'bool') return t === 'true' ? true : t === 'false' ? false : t
  if (/^[[{]/.test(t)) {
    try { return JSON.parse(t) } catch { return t }
  }
  return t
}

export function inputText(value: unknown): string {
  if (value === undefined || value === null) return ''
  return typeof value === 'string' ? value : JSON.stringify(value)
}

// Normalise schema: YAML array → JSON string; string → keep as-is
export function normSchema(raw: unknown): string {
  if (!raw) return 'context'
  if (Array.isArray(raw)) return JSON.stringify(raw)
  return String(raw)
}

/** Serialize a schema string back to YAML-safe form.
 * - 'context'            → 'context'
 * - 'Model.variant'      → 'Model.variant'
 * - 'list[Model]'        → 'list[Model]'
 * - JSON array string    → parsed array
 */
export function serializeSchema(s: string | undefined): string | unknown[] {
  if (!s || s === 'context') return 'context'
  try {
    const arr = JSON.parse(s)
    if (Array.isArray(arr)) return arr
  } catch { /* not JSON */ }
  return s
}

export interface ParsedContext {
  names: string[]
  versions: Record<string, string>
  isDict: boolean
}

// Parse the three accepted context forms into (names, version pins, shape):
//   "Candidate"                              → single string
//   [Candidate, Application]                 → list of names (or {name,version} dicts)
//   {models: [{name: Candidate, version: v1}]} → dict form (version-pinned)
// Names drive the editing UI; versions + shape are round-tripped on save so
// a version-pinned workflow isn't flattened (or corrupted to '[object Object]').
export function parseContext(raw: unknown): ParsedContext {
  const versions: Record<string, string> = {}
  const collect = (entry: unknown): string | null => {
    if (typeof entry === 'string') return entry
    if (entry && typeof entry === 'object') {
      const name = (entry as Record<string, unknown>).name
      const version = (entry as Record<string, unknown>).version
      if (typeof name === 'string') {
        if (typeof version === 'string') versions[name] = version
        return name
      }
    }
    return null
  }
  if (raw == null) return { names: [], versions, isDict: false }
  if (typeof raw === 'string') return { names: [raw], versions, isDict: false }
  if (Array.isArray(raw)) {
    return { names: raw.map(collect).filter((n): n is string => !!n), versions, isDict: false }
  }
  if (typeof raw === 'object') {
    const models = (raw as Record<string, unknown>).models
    const arr = Array.isArray(models) ? models : []
    return { names: arr.map(collect).filter((n): n is string => !!n), versions, isDict: true }
  }
  return { names: [], versions, isDict: false }
}

export type SerializedContext =
  | string
  | string[]
  | { models: Array<{ name: string; version?: string }> }
  | undefined

// Serialize context back to the form it came in, preserving version pins for
// models still selected. Dict form (or any surviving pin) → {models:[...]};
// otherwise a bare string (single) or list of names. Returns undefined when
// there's no context to emit (caller should omit the `context` key entirely).
export function serializeContext(
  names: string[],
  versions: Record<string, string>,
  isDict: boolean,
): SerializedContext {
  if (names.length === 0) return undefined
  const hasVersion = names.some((n) => versions[n])
  if (isDict || hasVersion) {
    return {
      models: names.map((n) =>
        versions[n] ? { name: n, version: versions[n] } : { name: n },
      ),
    }
  }
  if (names.length === 1) return names[0]
  return names
}
