import { describe, expect, it } from 'vitest'
import { INITIALS, parseLinks, pickedFrom } from './ideaUpload'

describe('pickedFrom', () => {
  it('keeps the folder-relative path of a picked folder and the plain name of a picked file', () => {
    const inFolder = Object.assign(new File(['x'], 'flow.md'), { webkitRelativePath: 'returns/notes/flow.md' })
    const plain = new File(['y'], 'brief.pdf')
    expect(pickedFrom([inFolder, plain]).map((p) => p.name)).toEqual(['returns/notes/flow.md', 'brief.pdf'])
  })
})

describe('INITIALS', () => {
  it('takes 2 to 4 letters or digits, starting with a letter', () => {
    for (const ok of ['AB', 'ab', 'A1', 'ABCD']) expect(INITIALS.test(ok)).toBe(true)
    for (const bad of ['', 'A', 'ABCDE', '1A', 'A-', 'A B']) expect(INITIALS.test(bad)).toBe(false)
  })
})

describe('parseLinks', () => {
  it('splits on lines and spaces and sets aside what is not a link', () => {
    const { links, bad } = parseLinks('https://acme.atlassian.net/browse/PAY-12\n  https://github.com/o/r/issues/3 notalink\n')
    expect(links).toEqual(['https://acme.atlassian.net/browse/PAY-12', 'https://github.com/o/r/issues/3'])
    expect(bad).toEqual(['notalink'])
  })
  it('gives nothing for blank text', () => {
    expect(parseLinks('  \n ')).toEqual({ links: [], bad: [] })
  })
})
