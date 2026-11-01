import { describe, expect, it } from 'vitest'
import { boundedInt, keyKind, parseWrite, writeText } from './memory'

describe('the memory form', () => {
  it('reads the owner key', () => {
    expect(keyKind(undefined)).toBe('principal')
    expect(keyKind('principal')).toBe('principal')
    expect(keyKind('tenant')).toBe('tenant')
    expect(keyKind('{{ customer_id }}')).toBe('input')
  })
  it('shows write as a list and parses it back; nothing means every output', () => {
    expect(writeText(['question', 'answer'])).toBe('question, answer')
    expect(writeText(undefined)).toBe('')
    expect(parseWrite(' question ,answer,, ')).toEqual(['question', 'answer'])
    expect(parseWrite('  ')).toBeUndefined()
  })
  it('accepts only whole numbers in range', () => {
    expect(boundedInt('5', 0, 50)).toBe(5)
    expect(boundedInt('0', 0, 50)).toBe(0)
    expect(boundedInt('51', 0, 50)).toBeUndefined()
    expect(boundedInt('2.5', 0, 50)).toBeUndefined()
    expect(boundedInt('abc', 0, 50)).toBeUndefined()
    expect(boundedInt('', 0, 50)).toBeUndefined() // an empty field changes nothing
  })
})
