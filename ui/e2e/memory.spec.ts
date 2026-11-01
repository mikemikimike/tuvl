import { expect, test } from '@playwright/test'

// An agent's memory block is edited in the panel, and the Memory page starts empty. Nothing is saved to disk.
test('an LLM agent can be told to remember across runs, and the block lands in its YAML', async ({ page }) => {
  await page.goto('/insight/workflows?wf=triage_ticket&agent=classify')
  await page.getByRole('button', { name: 'Prompt', exact: true }).click()
  const remember = page.getByLabel('Remember across runs')
  await expect(remember).not.toBeChecked()
  await remember.check()

  const collection = page.getByLabel('Memory collection', { exact: true })
  await collection.selectOption('kb') // configured in models/collections.yaml
  await page.getByLabel('Whose memory').selectOption('tenant')
  await page.getByLabel('Latest memories').fill('7')
  await page.getByLabel('Latest memories').blur()
  await page.getByLabel('Store after a run').fill('category, urgency')
  await page.getByLabel('Store after a run').blur()
  await page.getByLabel('Forget after').fill('90d')
  await page.getByLabel('Forget after').blur()

  await page.getByRole('button', { name: 'Agent YAML', exact: true }).click()
  const yaml = page.getByLabel('Agent YAML', { exact: true }).locator('.cm-content')
  await expect(yaml).toContainText('memory:')
  await expect(yaml).toContainText('collection: kb')
  await expect(yaml).toContainText('key: tenant')
  await expect(yaml).toContainText('window: 7')
  await expect(yaml).toContainText('retention: 90d')
  await expect(yaml).toContainText('write:')

  await page.getByRole('button', { name: 'Prompt', exact: true }).click()
  await page.getByLabel('Remember across runs').uncheck()
  await page.getByRole('button', { name: 'Agent YAML', exact: true }).click()
  await expect(yaml).not.toContainText('memory:')
})

test('the Memory page says so when nothing has been remembered', async ({ page }) => {
  await page.goto('/insight/memory')
  await expect(page.getByRole('heading', { name: 'Memory' }).or(page.getByText('what agents remember'))).toBeVisible()
  await expect(page.getByText('Nothing remembered yet.')).toBeVisible()
})
