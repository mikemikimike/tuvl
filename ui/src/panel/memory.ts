/** The `memory:` block of an `llm` or `loop` agent: its defaults and how the form reads it. */
export const DEFAULT_MEMORY = { collection: '', key: 'principal', window: 5, recall_top_k: 3, max_tokens: 1000 }

export type KeyKind = 'principal' | 'tenant' | 'input'

export const keyKind = (key: unknown): KeyKind => (key === 'tenant' ? 'tenant' : key === 'principal' || key == null || key === '' ? 'principal' : 'input')

/** `write` as the form shows it: nothing set means every output; an empty list means the agent only reads. */
export const writeText = (write: unknown): string => (Array.isArray(write) ? write.join(', ') : '')

export function parseWrite(text: string): string[] | undefined {
  const names = text.split(',').map((s) => s.trim()).filter(Boolean)
  return names.length ? names : undefined
}

/** A whole number within bounds, or undefined when the text is not one (the field then keeps its old value). */
export function boundedInt(text: string, min: number, max: number): number | undefined {
  if (text.trim() === '') return undefined
  const n = Number(text)
  return Number.isInteger(n) && n >= min && n <= max ? n : undefined
}
