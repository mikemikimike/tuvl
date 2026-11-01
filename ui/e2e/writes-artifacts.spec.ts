import { expect, test, type Page } from '@playwright/test'

// Storing an artifact reloads the dev server, so this runs with the other file-writing tests (see playwright.config.ts).
function watchErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
  page.on('console', (m) => {
    if (m.type() === 'error' && !/favicon|Failed to load resource/.test(m.text())) errors.push(`console: ${m.text()}`)
  })
  return errors
}

test('an LLM agent uses a stored prompt and skill artifact, pinned to a version', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/insight/workflows?wf=triage_ticket&agent=classify')
  const token = await page.evaluate(() => {
    for (const v of Object.values(sessionStorage)) {
      try { const key = JSON.parse(v)?.state?.devKey; if (key) return key as string } catch { /* not the store */ }
    }
    return undefined
  })
  const headers = token ? { authorization: `Bearer ${token}` } : {}
  for (const [name, type] of [['smoke-voice', 'prompt'], ['smoke-policy', 'skill']] as const) {
    const res = await page.request.post('/dev/artifacts', { headers, data: { name, type, content: `# ${name}`, description: `the ${name} ${type}` } })
    expect(res.ok()).toBeTruthy()
  }
  await page.reload()
  await page.getByRole('button', { name: 'Prompt', exact: true }).click()
  await page.getByLabel('system source').getByText('Use a stored artifact').click()
  const voice = page.getByLabel('system artifact', { exact: true })
  await expect(voice.locator('option', { hasText: 'smoke-policy' })).toHaveCount(0) // a skill is not a prompt
  await voice.selectOption('smoke-voice')
  await expect(page.getByLabel('system artifact version')).toHaveValue('1')
  await page.getByLabel('Add Skill').selectOption('smoke-policy')
  await page.getByRole('button', { name: 'Agent YAML', exact: true }).click()
  const yaml = page.getByLabel('Agent YAML', { exact: true }).locator('.cm-content')
  await expect(yaml).toContainText('artifact://smoke-voice@1')
  await expect(yaml).toContainText('artifact://smoke-policy@1')
  expect(errors).toEqual([])
})
