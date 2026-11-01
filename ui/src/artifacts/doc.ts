// Structured artifact documents (judge, rules) edited as YAML text, keeping comments.
import { parseDocument } from 'yaml'

export interface Calibration { input: string; expect: 'pass' | 'fail' | 'uncertain' }
export interface Rule { when: string; then: string }

function edit(text: string, fn: (doc: ReturnType<typeof parseDocument>) => void): string {
  const doc = parseDocument(text)
  if (doc.errors.length) throw new Error(doc.errors[0].message)
  fn(doc)
  return doc.toString()
}

export function readArtifact(text: string): { name: string; version: number; description: string; spec: Record<string, unknown> } | null {
  const doc = parseDocument(text)
  if (doc.errors.length) return null
  const data = doc.toJS() as { kind?: string; metadata?: Record<string, unknown>; spec?: Record<string, unknown> } | null
  if (!data || data.kind !== 'Artifact' || !data.metadata || !data.spec) return null
  return {
    name: String(data.metadata.name ?? ''),
    version: Number(data.metadata.version ?? 1),
    description: String(data.metadata.description ?? ''),
    spec: data.spec,
  }
}

/** Set (or with `undefined` remove) `spec.<path>`; `['metadata', …]` paths start at the root. */
export function setIn(text: string, path: (string | number)[], value: unknown): string {
  const at = path[0] === 'metadata' ? path : ['spec', ...path]
  return edit(text, (doc) => {
    if (value === undefined || value === '') doc.deleteIn(at)
    else doc.setIn(at, doc.createNode(value))
  })
}

export function addCalibration(text: string, example: Calibration): string {
  return edit(text, (doc) => {
    const node = doc.createNode(example)
    node.flow = true
    if (doc.hasIn(['spec', 'calibration'])) doc.addIn(['spec', 'calibration'], node)
    else doc.setIn(['spec', 'calibration'], doc.createNode([example]))
  })
}

export function removeCalibration(text: string, index: number): string {
  return edit(text, (doc) => { doc.deleteIn(['spec', 'calibration', index]) })
}

export function judgeTemplate(name: string, description: string): string {
  return `kind: Artifact
metadata:
  name: ${name}
  version: 1
  description: ${description || 'What a passing subject looks like'}
spec:
  type: judge
  model: default
  rubric: |
    Pass when … Fail when … Use uncertain only when the subject does not
    contain enough to decide.
  verdict: [pass, fail, uncertain]
  min_score: 0.7
  calibration: []
  min_agreement: 0.9
`
}

export function rulesTemplate(name: string, description: string): string {
  return `kind: Artifact
metadata:
  name: ${name}
  version: 1
  description: ${description || 'A reusable decision table'}
spec:
  type: rules
  rules:
    - { when: "true", then: default }
`
}
