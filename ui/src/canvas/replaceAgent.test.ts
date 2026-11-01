import { describe, expect, it } from 'vitest'
import { parseDocument } from 'yaml'
import { checkAgent, replaceAgent } from './model'

const FILE = `kind: Workflow
version: tuvl/v2
metadata:
  name: demo
spec:
  agents:
    - id: first
      engine: llm
      llm: { model: default }
      routes: { default: second }
    - id: second
      engine: code
      routes: { default: END }
`

describe('replaceAgent', () => {
  it('swaps the agent in place and leaves its neighbours alone', () => {
    const next = replaceAgent(FILE, 'first', { id: 'first', engine: 'llm', llm: { model: 'fast', prompt: 'Say hi' }, routes: { default: 'second' } })
    const agents = parseDocument(next).toJS().spec.agents
    expect(agents.map((a: { id: string }) => a.id)).toEqual(['first', 'second'])
    expect(agents[0].llm).toEqual({ model: 'fast', prompt: 'Say hi' })
    expect(agents[1]).toEqual({ id: 'second', engine: 'code', routes: { default: 'END' } })
  })

  it('refuses an id change, a non-mapping and an unknown agent', () => {
    expect(() => checkAgent('first', { id: 'renamed' })).toThrow(/stays 'first'/)
    expect(() => checkAgent('first', 'text')).toThrow(/mapping/)
    expect(() => checkAgent('first', [1])).toThrow(/mapping/)
    expect(() => replaceAgent(FILE, 'nope', { id: 'nope' })).toThrow(/no agent 'nope'/)
  })
})
