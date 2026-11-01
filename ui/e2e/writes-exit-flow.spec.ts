import { expect, test } from '@playwright/test'

// The P4 exit flow, offline: author a workflow in Insight, run it with a
// breakpoint, continue, pin the run as a fixture, change the agent's rules and
// check the change against the fixture.
test('author → breakpoint run → pin → change → check', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  const name = `exit_${Date.now().toString(36)}`

  await page.goto('/insight/workflows')
  await page.getByTitle('Browse workflows (⌘K)').click()
  await page.getByRole('button', { name: '+ New workflow' }).click()
  await page.getByLabel('New workflow name').fill(name)
  await page.getByLabel('New workflow name').press('Enter')
  const canvas = page.locator('.react-flow')
  await expect(canvas.getByText('first_step', { exact: true })).toBeVisible()

  // pending → decide (keeps the contract; rules route to lanes a | b)
  await canvas.getByText('first_step', { exact: true }).click()
  await page.getByLabel('Change engine').selectOption('decide')
  await expect(page.getByText('✓ valid (draft)')).toBeVisible()
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByText('✓ valid', { exact: true })).toBeVisible()

  // breakpoint, run, continue
  await page.getByLabel('Set breakpoint on first_step').click()
  await expect(page.getByLabel('Remove breakpoint on first_step')).toBeVisible()
  await page.getByRole('button', { name: '▶ Run' }).click()
  await page.getByLabel('Run input').fill('{"text": "hello"}')
  await page.getByRole('button', { name: 'Start' }).click()
  await expect(page).toHaveURL(/\/runs\?run=/)
  await expect(page.getByRole('button', { name: '▶ Continue' })).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: '▶ Continue' }).click()
  await expect(page.getByRole('button', { name: '📌 Pin as fixture' })).toBeVisible({ timeout: 15_000 }) // shown once the run ends
  await expect(page.locator('main').getByText('decided a by rule#1')).toBeVisible()

  // pin the run as a fixture
  await page.getByRole('button', { name: '📌 Pin as fixture' }).click()
  await page.getByLabel('Fixture name').fill('hello')
  await page.getByRole('button', { name: 'Pin', exact: true }).click()
  await expect(page.getByText(/hello\.journal\.json/)).toBeVisible()

  // change the rule, check it against the pinned run
  await page.goto('/insight/workflows')
  await page.getByTitle('Browse workflows (⌘K)').click()
  await page.getByRole('dialog', { name: 'Choose a workflow' }).getByRole('button', { name: new RegExp(name) }).click()
  await page.locator('.react-flow').getByText('first_step', { exact: true }).click()
  await page.getByRole('button', { name: 'Rules', exact: true }).click()  // a decide agent's engine tab
  await page.getByLabel('Rule 1 condition').fill("text != ''")
  await page.getByLabel('Rule 1 condition').press('Enter')
  await page.getByRole('button', { name: '⇄ Check vs fixtures' }).click()
  await expect(page.getByText('SAME', { exact: true })).toBeVisible({ timeout: 15_000 })

  // and a change that alters the outcome (no rule matches → error) is caught
  await page.getByLabel('Rule 1 condition').fill("text == 'something else'")
  await page.getByLabel('Rule 1 condition').press('Enter')
  await page.getByRole('button', { name: '⇄ Check vs fixtures' }).click()
  await expect(page.getByText('DIFF', { exact: true })).toBeVisible({ timeout: 15_000 })
  expect(errors).toEqual([])
})
