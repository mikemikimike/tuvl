import { load } from 'js-yaml'

/**
 * Typed wrapper around js-yaml's `load()`. This is the single point where an
 * `as any`/`as unknown` cast happens for parsed YAML — callers should type
 * the generic to the (possibly partial, since the source is often
 * hand-edited text) shape they expect rather than casting locally.
 */
export function parseYaml<T = unknown>(text: string): T {
  return load(text) as T
}
