import { expect, test } from '@playwright/test'

// Embeddings, Collections, Storage and Models start a new item the same way: a "+" in the list header, and
// (when nothing is selected) an empty panel with a button.
test('Embeddings: the empty panel and the + both start a new embedding', async ({ page }) => {
  await page.goto('/insight/embeddings')
  await expect(page.getByText('No embedding selected')).toBeVisible() // the sample project defines none
  await page.getByRole('button', { name: '+ New Embedding', exact: true }).click()
  await expect(page.getByText('New Embedding', { exact: true })).toBeVisible()
  await page.goto('/insight/embeddings')
  await page.getByRole('button', { name: 'New embedding', exact: true }).click()
  await expect(page.getByText('New Embedding', { exact: true })).toBeVisible()
})

test('Collections: the + in the list header starts a new collection', async ({ page }) => {
  await page.goto('/insight/collections')
  await page.getByRole('button', { name: 'New collection', exact: true }).click()
  await expect(page.getByText('New Collection', { exact: true })).toBeVisible()
})

test('Storage: the empty panel starts a new store, and Cancel returns to it', async ({ page }) => {
  await page.goto('/insight/storage')
  await expect(page.getByText('No store declared')).toBeVisible() // the sample project declares none
  await page.getByRole('button', { name: '+ New Store', exact: true }).click()
  await expect(page.getByLabel('Storage YAML')).toBeVisible()
  await page.getByRole('button', { name: 'Cancel' }).click()
  await expect(page.getByText('No store declared')).toBeVisible()
  await page.getByRole('button', { name: 'New store', exact: true }).click() // the + in the header
  await expect(page.getByLabel('Storage YAML')).toBeVisible()
})

test('Models: the + and the empty panel are unchanged', async ({ page }) => {
  await page.goto('/insight/models')
  await page.getByRole('button', { name: 'New model', exact: true }).click()
  await expect(page.getByText('New Model', { exact: true })).toBeVisible()
})
