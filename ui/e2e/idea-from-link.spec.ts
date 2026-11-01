import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { expect, test } from '@playwright/test'

// An idea from a link: the dialog takes links, refuses an internal address until it is allowed, and the idea
// keeps a snapshot with its source. The page is served from this process on 127.0.0.1, which is an internal address.
const PAGE = '<html><head><title>Loyalty brief</title></head><body><nav>Home Pricing</nav><main><h1>Loyalty points</h1>'
  + '<p>Customers earn <b>one point</b> per order.</p><ul><li>Points expire after a year</li></ul></main></body></html>'

let close: () => void
let link = ''

test.beforeAll(async () => {
  const server = createServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'text/html' })
    res.end(PAGE)
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  link = `http://127.0.0.1:${(server.address() as AddressInfo).port}/brief`
  close = () => server.close()
})

test.afterAll(() => close())

test('a link becomes an idea snapshot, after the internal address is allowed', async ({ page }) => {
  await page.goto('/insight/ideas')
  await page.getByRole('button', { name: 'Upload idea' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Upload an idea' })
  const submit = dialog.getByRole('button', { name: 'Import idea' })
  await expect(submit).toBeDisabled()

  const links = dialog.getByLabel('Or add links (one per line)')
  await links.fill('not-a-link')
  await expect(dialog.getByRole('alert')).toContainText('Not a link: not-a-link')
  await expect(submit).toBeDisabled()

  await links.fill(link)
  await expect(dialog.getByRole('alert')).toHaveCount(0)
  await expect(submit).toBeEnabled()
  if (await dialog.getByLabel('Your initials').isVisible()) await dialog.getByLabel('Your initials').fill('LK')

  await submit.click() // the address is internal and has not been allowed
  await expect(dialog.getByRole('alert')).toContainText('--allow-private')
  await expect(dialog).toBeVisible()

  await dialog.getByLabel(/allow internal addresses/).check()
  await submit.click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('heading', { name: 'Loyalty points' })).toBeVisible()
  const main = page.locator('main')
  await expect(main).toContainText(`Snapshot of ${link}`)
  await expect(main).toContainText('(web)')
  await expect(main).toContainText('Customers earn **one point** per order.')
  await expect(main).not.toContainText('Home Pricing') // the menu is not part of the snapshot
})
