import { afterEach, describe, expect, it, vi } from 'vitest'
import { useUIStore } from './store'
import { ApiError } from './api'
import { readText, specStatus, validateProject, writeText } from './devApi'

function mockFetch(response: Response) {
  const fn = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => vi.unstubAllGlobals())

describe('devApi', () => {
  it('reads files as text with the dev key', async () => {
    useUIStore.setState({ devKey: 'k1' })
    const fetch = mockFetch(new Response('# keep\nkind: Workflow\n', { status: 200 }))
    expect(await readText('workflows', 'sub/a b.yaml')).toBe('# keep\nkind: Workflow\n')
    const [url, init] = fetch.mock.calls[0]
    expect(url).toMatch(/\/dev\/text\/workflows\/sub\/a%20b\.yaml$/)
    expect(init.headers.authorization).toBe('Bearer k1')
  })

  it('writes text/plain and surfaces the server detail on error', async () => {
    const fetch = mockFetch(new Response(JSON.stringify({ detail: 'YAML parse error: x' }), { status: 422 }))
    const err = await writeText('workflows', 'a.yaml', 'a: [').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(422)
    expect(err.message).toBe('YAML parse error: x')
    expect(fetch.mock.calls[0][1].headers['content-type']).toBe('text/plain')
    expect(fetch.mock.calls[0][1].body).toBe('a: [')
  })

  it('parses JSON reports', async () => {
    mockFetch(new Response(JSON.stringify({ valid: true, errors: [], warnings: [], profiles: {} }), { status: 200 }))
    expect((await validateProject()).valid).toBe(true)
    const fetch = mockFetch(new Response(JSON.stringify({ done: false, plans: [] }), { status: 200 }))
    await specStatus('specs/a.md', false)
    expect(fetch.mock.calls[0][0]).toMatch(/\/dev\/specs\/status\?tests=false&spec=specs%2Fa\.md$/)
  })
})
