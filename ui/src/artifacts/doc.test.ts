import { describe, expect, it } from 'vitest'
import { addCalibration, judgeTemplate, readArtifact, removeCalibration, rulesTemplate, setIn } from './doc'

const JUDGE = `# reviewed by compliance
kind: Artifact
metadata: { name: reply, version: 2 }
spec:
  type: judge
  model: default
  rubric: States the amount.
  calibration:
    - { input: fixtures/judge/a.json, expect: pass }  # keep me
`

describe('structured artifact documents', () => {
  it('reads the envelope and edits the spec, keeping comments', () => {
    expect(readArtifact(JUDGE)).toMatchObject({ name: 'reply', version: 2, spec: { type: 'judge', model: 'default' } })
    const edited = setIn(JUDGE, ['min_score'], 0.8)
    expect(edited).toContain('# reviewed by compliance')
    expect(readArtifact(edited)!.spec.min_score).toBe(0.8)
    expect(readArtifact(setIn(edited, ['min_score'], undefined))!.spec.min_score).toBeUndefined()
    expect(readArtifact(setIn(JUDGE, ['metadata', 'description'], 'x'))!.description).toBe('x')
    expect(readArtifact('kind: Workflow\nmetadata: {}\nspec: {}')).toBeNull()
  })

  it('appends and removes calibration examples', () => {
    const added = addCalibration(JUDGE, { input: 'fixtures/judge/b.json', expect: 'fail' })
    expect(added).toContain('# keep me')
    expect(added).toContain('{ input: fixtures/judge/b.json, expect: fail }')
    expect(readArtifact(added)!.spec.calibration).toHaveLength(2)
    expect(readArtifact(removeCalibration(added, 0))!.spec.calibration).toEqual([{ input: 'fixtures/judge/b.json', expect: 'fail' }])
    const fresh = addCalibration(judgeTemplate('j', ''), { input: 'fixtures/judge/c.json', expect: 'pass' })
    expect(readArtifact(fresh)!.spec.calibration).toEqual([{ input: 'fixtures/judge/c.json', expect: 'pass' }])
  })

  it('templates are valid artifacts', () => {
    expect(readArtifact(judgeTemplate('j', 'd'))).toMatchObject({ name: 'j', description: 'd', spec: { type: 'judge' } })
    expect(readArtifact(rulesTemplate('r', ''))!.spec.rules).toEqual([{ when: 'true', then: 'default' }])
  })
})
