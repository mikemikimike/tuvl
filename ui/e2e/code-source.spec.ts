import { expect, test } from '@playwright/test'

// A code agent's Python is editable in Insight: edit, save (codegen keeps the signature), expand, assist.
test('a code agent is edited and saved in Insight', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto('/insight/workflows?wf=triage_ticket&agent=prioritise')
  await expect(page.getByRole('button', { name: '</> Code' })).toBeVisible()  // a code agent opens on its Python
  await expect(page.getByText('agents/prioritise_ticket.py')).toBeVisible()
  const code = page.locator('.cm-content').filter({ hasText: 'async def prioritise_ticket' })
  await expect(code).toBeVisible()

  await code.getByText('return "normal"').click()
  await page.keyboard.press('End')
  await page.keyboard.type('  # reviewed in Insight')
  await expect(page.getByText('● unsaved')).toBeVisible()
  await page.getByRole('button', { name: 'Save Python', exact: true }).click()
  await expect(page.getByText(/^Saved/)).toBeVisible()
  await expect(page.getByText('● unsaved')).toHaveCount(0)

  await page.getByRole('button', { name: '⤢ Open editor' }).click()
  await expect(page.getByRole('dialog', { name: 'Edit prioritise_ticket' })).toBeVisible()
  await page.getByRole('button', { name: '✦ Assist' }).click()
  await expect(page.getByLabel('Assist model')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  // leaving the Code tab with the assistant open used to crash the page
  await page.getByRole('button', { name: 'Contract', exact: true }).click()
  await expect(page.getByText('Outputs')).toBeVisible()
  expect(errors).toEqual([])
})

// A code agent just added on the canvas has no Python yet: it opens on codegen's stub, with Assist.
test('a new code agent opens on a stub with the assistant', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto('/insight/workflows?wf=triage_ticket')
  await page.getByRole('button', { name: /Add step/ }).click()
  await page.getByRole('button', { name: '+ Code' }).click()
  await expect(page.getByText(/doesn.t exist yet/)).toBeVisible()
  await expect(page.locator('.cm-content').filter({ hasText: '@agent("code' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save Python' })).toBeEnabled()
  await page.getByRole('button', { name: '✦ Assist' }).click()
  await expect(page.getByLabel('Assist model')).toBeVisible()
  await expect(page.getByLabel('Ask the assistant')).toBeEnabled()
  expect(errors).toEqual([])
})

// The redesigned Workflows screen: the canvas has the width; workflows switch from ⌘K, steps come from + Add step / A,
// problems sit in a bar, and the code window moves, resizes and maximizes.
test('workflow switcher, step picker and the code window', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto('/insight/workflows?wf=triage_ticket')
  await expect(page.getByTitle('Browse workflows (⌘K)')).toContainText('triage_ticket')
  await page.keyboard.press('ControlOrMeta+k')
  const switcher = page.getByRole('dialog', { name: 'Choose a workflow' })
  await expect(switcher).toBeVisible()
  await page.getByLabel('Find a workflow').fill('triage')
  await expect(switcher.getByRole('button', { name: /triage_ticket/ })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(switcher).toHaveCount(0)

  await page.locator('.react-flow').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('a')
  await expect(page.getByRole('dialog', { name: 'Add step' })).toBeVisible()
  await page.getByLabel('Find a step type').fill('human')
  await expect(page.getByRole('button', { name: '+ Human approval' })).toBeVisible()
  await expect(page.getByRole('button', { name: '+ Code' })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: /^Problems/ })).toBeVisible()

  await page.goto('/insight/workflows?wf=triage_ticket&agent=prioritise')
  await page.getByRole('button', { name: '⤢ Open editor' }).click()
  const win = page.getByRole('dialog', { name: 'Edit prioritise_ticket' })
  await expect(win.locator('.cm-content').filter({ hasText: 'async def prioritise_ticket' })).toBeVisible()
  await expect(win.getByRole('complementary', { name: 'Contract' })).toBeVisible()
  const before = (await win.boundingBox())!
  const bar = win.getByText('prioritise_ticket', { exact: true }).first()
  const at = (await bar.boundingBox())!
  await page.mouse.move(at.x + 5, at.y + 5)
  await page.mouse.down()
  await page.mouse.move(at.x + 70, at.y + 40, { steps: 5 })
  await page.mouse.up()
  const moved = (await win.boundingBox())!
  expect(Math.round(moved.x - before.x)).toBe(65)
  expect(Math.round(moved.y - before.y)).toBe(35)
  await page.mouse.move(moved.x + 2, moved.y + 2)  // the top-left corner
  await page.mouse.down()
  await page.mouse.move(moved.x + 102, moved.y + 52, { steps: 5 })
  await page.mouse.up()
  const resized = (await win.boundingBox())!
  expect(Math.round(moved.width - resized.width)).toBe(100)
  expect(Math.round(moved.height - resized.height)).toBe(50)
  await win.getByRole('button', { name: 'Maximize window' }).click()
  const max = (await win.boundingBox())!
  const vp = page.viewportSize()!
  expect([max.width, max.height]).toEqual([vp.width, vp.height])
  await win.getByRole('button', { name: 'Restore window' }).click()
  expect(Math.round((await win.boundingBox())!.width)).toBe(Math.round(resized.width))
  await win.getByRole('button', { name: 'Close window' }).click()
  await expect(win).toHaveCount(0)
  expect(errors).toEqual([])
})
