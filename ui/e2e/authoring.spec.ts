import { expect, test } from '@playwright/test'

// The idea → spec → approval trail, read-only: scripts/insight-smoke.sh imports IDEA-SM-0001, drafts
// SPEC-SM-0001-01 from it and approves it before the server starts.
test('an idea shows its text, its specs and their approval', async ({ page }) => {
  await page.goto('/insight/ideas')
  await expect(page.getByRole('button', { name: /IDEA-SM-0001/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Smoke brief' })).toBeVisible()
  await expect(page.locator('main')).toContainText('A short idea about tickets.')
  await expect(page.locator('main')).toContainText('SPEC-SM-0001-01')
  await expect(page.locator('main').getByText('approved', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'SPEC-SM-0001-01' }).click()
  await expect(page).toHaveURL(/specs\?spec=SPEC-SM-0001-01\.md/)
})

test('a spec tile and the pipeline show where the spec stands', async ({ page }) => {
  await page.goto('/insight/specs?spec=SPEC-SM-0001-01.md')
  const tile = page.getByRole('button', { name: /SPEC-SM-0001-01/ }).first()
  await expect(tile).toContainText('approved')
  const pipeline = page.getByLabel('Pipeline')
  await expect(pipeline).toContainText('IDEA-SM-0001')
  await expect(pipeline).toContainText('SPEC-SM-0001-01')
  await expect(pipeline).toContainText('approved')
  await pipeline.getByRole('link', { name: 'IDEA-SM-0001' }).click()
  await expect(page).toHaveURL(/ideas\?idea=IDEA-SM-0001/)
})

test('the audit page lists the commands that were run and checks the chain', async ({ page }) => {
  await page.goto('/insight/audit')
  const events = page.getByLabel('Events')
  await expect(events).toContainText('idea.imported')
  await expect(events).toContainText('spec.created')
  await expect(events).toContainText('spec.approved')
  await expect(page.getByRole('status')).toContainText(/chain intact/)

  await page.getByLabel('Kind').fill('spec.')
  await expect(events).not.toContainText('idea.imported')
  await expect(events).toContainText('spec.approved')
  await page.getByLabel('Kind').fill('')

  await page.getByLabel('Entity').fill('IDEA-SM-0001')
  await expect(events).toContainText('idea.imported')
  await expect(events).toContainText('spec.created')  // an idea also covers the specs drawn from it

  await events.getByRole('button', { name: /idea\.imported/ }).click()
  await expect(events).toContainText('"command": "import idea"')
})
