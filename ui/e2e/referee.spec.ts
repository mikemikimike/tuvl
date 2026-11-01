import { expect, test } from '@playwright/test'

// The spec referee on the `--sample` project: findings, traceability, and the way back to the spec.
test('specs show findings and trace a step to its canvas node and back', async ({ page }) => {
  await page.goto('/insight/specs?spec=triage-ticket.md')
  await page.getByRole('button', { name: /^Findings/ }).click()
  await expect(page.getByText('The spec is complete and consistent.')).toBeVisible()

  await page.getByRole('button', { name: 'Traceability' }).click()
  await expect(page.getByText('0 mismatch(es)')).toBeVisible()
  await page.getByRole('button', { name: 'Run tests' }).click()
  await expect(page.locator('main')).toContainText(/passed\s*a routine ticket is stored/, { timeout: 20_000 })
  await expect(page.locator('main')).toContainText(/prioritise.*3 passed/s)

  await page.getByRole('button', { name: 'prioritise', exact: true }).click()
  await expect(page).toHaveURL(/workflows\?wf=triage_ticket&agent=prioritise/)
  await page.getByRole('button', { name: /^spec :\d+/ }).click()
  await expect(page).toHaveURL(/specs\?spec=triage-ticket\.md&view=trace/)
  await expect(page.getByText('0 mismatch(es)')).toBeVisible()
})
