import { dump } from 'js-yaml'
import { describe, expect, it } from 'vitest'
import { coerceInput, inputText, normSchema, parseContext, serializeContext, serializeSchema } from './workflow-context'

describe('parseContext', () => {
  it('parses a single string', () => {
    expect(parseContext('Candidate')).toEqual({ names: ['Candidate'], versions: {}, isDict: false })
  })

  it('parses a list of names', () => {
    expect(parseContext(['Candidate', 'Application'])).toEqual({
      names: ['Candidate', 'Application'],
      versions: {},
      isDict: false,
    })
  })

  it('parses a list containing {name,version} dicts (mixed pins)', () => {
    expect(parseContext(['Candidate', { name: 'Application', version: 'v2' }])).toEqual({
      names: ['Candidate', 'Application'],
      versions: { Application: 'v2' },
      isDict: false,
    })
  })

  it('parses the {models:[{name,version}]} dict form', () => {
    expect(
      parseContext({ models: [{ name: 'Candidate', version: 'v1' }, { name: 'Application' }] }),
    ).toEqual({
      names: ['Candidate', 'Application'],
      versions: { Candidate: 'v1' },
      isDict: true,
    })
  })

  it('parses an empty/null context as empty', () => {
    expect(parseContext(null)).toEqual({ names: [], versions: {}, isDict: false })
    expect(parseContext(undefined)).toEqual({ names: [], versions: {}, isDict: false })
  })

  it('parses an empty dict form as empty but still isDict', () => {
    expect(parseContext({ models: [] })).toEqual({ names: [], versions: {}, isDict: true })
  })

  it('ignores malformed entries (no name)', () => {
    expect(parseContext([{ version: 'v1' }, 'Candidate'])).toEqual({
      names: ['Candidate'],
      versions: {},
      isDict: false,
    })
  })
})

describe('serializeContext', () => {
  it('serializes a single name back to a bare string', () => {
    expect(serializeContext(['Candidate'], {}, false)).toBe('Candidate')
  })

  it('serializes multiple names to a list', () => {
    expect(serializeContext(['Candidate', 'Application'], {}, false)).toEqual(['Candidate', 'Application'])
  })

  it('serializes dict-form input back to dict form, never to a bare object/string', () => {
    const result = serializeContext(['Candidate'], { Candidate: 'v1' }, true)
    expect(result).toEqual({ models: [{ name: 'Candidate', version: 'v1' }] })
    // The regression this whole module exists to prevent: the dict form must
    // stay a real object through to YAML emission, not get flattened/coerced
    // to the literal scalar string "[object Object]" along the way.
    const yamlText = dump({ context: result })
    expect(yamlText).not.toContain('[object Object]')
    expect(yamlText).toContain('models:')
  })

  it('promotes to dict form when any surviving pin exists, even if isDict was false', () => {
    const result = serializeContext(['Candidate', 'Application'], { Application: 'v3' }, false)
    expect(result).toEqual({
      models: [{ name: 'Candidate' }, { name: 'Application', version: 'v3' }],
    })
  })

  it('edit-drops-model-keeps-pin: dropping an unpinned model preserves the pinned one', () => {
    // Started as {models:[{name:A,version:v1},{name:B}]}; user removes B.
    const result = serializeContext(['A'], { A: 'v1' }, true)
    expect(result).toEqual({ models: [{ name: 'A', version: 'v1' }] })
  })

  it('edit-adds-model: adding an unpinned model to a dict-form context keeps dict shape', () => {
    // Started as {models:[{name:A,version:v1}]}; user adds B (no pin).
    const result = serializeContext(['A', 'B'], { A: 'v1' }, true)
    expect(result).toEqual({ models: [{ name: 'A', version: 'v1' }, { name: 'B' }] })
  })

  it('returns undefined for empty context (caller omits the key)', () => {
    expect(serializeContext([], {}, false)).toBeUndefined()
    expect(serializeContext([], {}, true)).toBeUndefined()
  })

  it('drops stale version pins for names no longer present', () => {
    // versions carries a leftover pin for a model that's no longer selected;
    // it must not resurrect it or otherwise corrupt the shape.
    const result = serializeContext(['Candidate'], { Candidate: 'v1', Stale: 'v9' }, false)
    expect(result).toEqual({ models: [{ name: 'Candidate', version: 'v1' }] })
  })
})

describe('flow ↔ YAML context round-trip', () => {
  const roundTrip = (raw: unknown) => {
    const parsed = parseContext(raw)
    return serializeContext(parsed.names, parsed.versions, parsed.isDict)
  }

  it('round-trips a single string', () => {
    expect(roundTrip('Candidate')).toBe('Candidate')
  })

  it('round-trips a list of names', () => {
    expect(roundTrip(['Candidate', 'Application'])).toEqual(['Candidate', 'Application'])
  })

  it('round-trips the {models:[...]} dict form, including version pins', () => {
    const raw = { models: [{ name: 'Candidate', version: 'v1' }, { name: 'Application' }] }
    expect(roundTrip(raw)).toEqual(raw)
  })

  it('round-trips a mixed list (plain name + pinned dict entry) into dict form', () => {
    const raw = ['Candidate', { name: 'Application', version: 'v2' }]
    expect(roundTrip(raw)).toEqual({
      models: [{ name: 'Candidate' }, { name: 'Application', version: 'v2' }],
    })
  })

  it('round-trips empty/null context to undefined (no context key emitted)', () => {
    expect(roundTrip(null)).toBeUndefined()
    expect(roundTrip(undefined)).toBeUndefined()
  })

  it('never serializes dict-form context to the string "[object Object]"', () => {
    const raw = { models: [{ name: 'Candidate', version: 'v1' }] }
    const result = roundTrip(raw)
    expect(result).not.toBe('[object Object]')
    expect(JSON.stringify(result)).not.toContain('[object Object]')
    // Emitted YAML must contain a real mapping, not a corrupted scalar.
    const yamlText = dump({ context: result })
    expect(yamlText).not.toContain('[object Object]')
    expect(yamlText).toContain('models:')
  })
})

describe('normSchema', () => {
  it('defaults falsy input to "context"', () => {
    expect(normSchema(undefined)).toBe('context')
    expect(normSchema(null)).toBe('context')
    expect(normSchema('')).toBe('context')
  })

  it('stringifies an array to JSON', () => {
    expect(normSchema(['Candidate', 'Application'])).toBe('["Candidate","Application"]')
  })

  it('passes through a non-empty string as-is', () => {
    expect(normSchema('Model.variant')).toBe('Model.variant')
    expect(normSchema('list[Model]')).toBe('list[Model]')
  })
})

describe('serializeSchema', () => {
  it('serializes falsy or "context" input back to "context"', () => {
    expect(serializeSchema(undefined)).toBe('context')
    expect(serializeSchema('')).toBe('context')
    expect(serializeSchema('context')).toBe('context')
  })

  it('parses a JSON array string back into an array', () => {
    expect(serializeSchema('["Candidate","Application"]')).toEqual(['Candidate', 'Application'])
  })

  it('passes through a non-JSON schema string as-is', () => {
    expect(serializeSchema('Model.variant')).toBe('Model.variant')
    expect(serializeSchema('list[Model]')).toBe('list[Model]')
  })

  it('treats a JSON-but-non-array string as passthrough', () => {
    expect(serializeSchema('{"not":"an array"}')).toBe('{"not":"an array"}')
  })

  it('round-trips normSchema output back through serializeSchema', () => {
    const raw = ['Candidate', 'Application']
    expect(serializeSchema(normSchema(raw))).toEqual(raw)
  })
})

describe('coerceInput', () => {
  it('types scalars by the declared input type', () => {
    expect(coerceInput('int', '5')).toBe(5)
    expect(coerceInput('int?', '-3')).toBe(-3)
    expect(coerceInput('float', '1.5')).toBe(1.5)
    expect(coerceInput('bool', 'true')).toBe(true)
    expect(coerceInput('str', '42')).toBe('42')
    expect(coerceInput('uuid', ' 7c9e ')).toBe('7c9e')
  })
  it('keeps text it cannot type so validation can flag it', () => {
    expect(coerceInput('int', 'five')).toBe('five')
    expect(coerceInput('bool', 'yes')).toBe('yes')
  })
  it('parses JSON for structured values and treats empty as unset', () => {
    expect(coerceInput('list[str]', '["a","b"]')).toEqual(['a', 'b'])
    expect(coerceInput('json', '{"k": 1}')).toEqual({ k: 1 })
    expect(coerceInput('json', '{oops')).toBe('{oops')
    expect(coerceInput('str', '  ')).toBeUndefined()
  })
  it('shows values back as text', () => {
    expect(inputText(undefined)).toBe('')
    expect(inputText('daily')).toBe('daily')
    expect(inputText(5)).toBe('5')
    expect(inputText(['a'])).toBe('["a"]')
  })
})
