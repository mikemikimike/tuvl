import { expect, test, type Page } from '@playwright/test'

// Every Insight page renders against the `tuvl init --sample` project without
// a page error or console error.
// `title` is the page's top bar; `shows` is content only that page renders.
const PAGES: { path: string; title?: string; shows: string }[] = [
  { path: 'specs', title: 'Specs', shows: 'triage-ticket' },
  { path: 'workflows', shows: 'Add step' },  // its top bar is the workflow switcher
  { path: 'runs', title: 'Runs', shows: 'Select a run to see its journal.' },
  { path: 'artifacts', title: 'Artifacts', shows: '+ New artifact' },
  { path: 'models', title: 'Models', shows: 'Ticket' },
  { path: 'datasources', shows: 'No datasource selected' },
  { path: 'agent-models', title: 'AI Models', shows: 'default' },
  { path: 'embeddings', shows: 'No embedding selected' },
  { path: 'collections', shows: 'Support articles' },
  { path: 'storage', title: 'Storage', shows: 'No storage declared. Add one to storage/.' },
  { path: 'api-docs', title: 'API Docs', shows: 'Swagger UI' },
  { path: 'iam', title: 'IAM', shows: 'Users' },
  { path: 'federation', title: 'Federation', shows: 'Federation' },
  { path: 'settings', title: 'Settings', shows: 'Settings' },
]

function watchErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
  page.on('console', (m) => {
    if (m.type() === 'error' && !/favicon|Failed to load resource/.test(m.text())) errors.push(`console: ${m.text()}`)
  })
  return errors
}

for (const { path, title, shows } of PAGES) {
  test(`${path} renders`, async ({ page }) => {
    const errors = watchErrors(page)
    await page.goto(`/insight/${path}`)
    if (title) await expect(page.locator('main header').first()).toContainText(title)
    await expect(page.locator('main').getByText(shows).first()).toBeVisible()
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })
}

test('workflow canvas shows the sample agents and validates', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/insight/workflows')
  await page.getByTitle('Browse workflows (⌘K)').click()
  await page.getByRole('dialog', { name: 'Choose a workflow' }).getByRole('button', { name: /triage_ticket/ }).click()
  for (const agent of ['classify', 'prioritise', 'review', 'store']) {
    await expect(page.locator('.react-flow').getByText(agent, { exact: true })).toBeVisible()
  }
  await expect(page.getByText('✓ valid')).toBeVisible()
  await page.getByText('YAML', { exact: true }).click()
  await expect(page.getByText('kind: Workflow').first()).toBeVisible()
  expect(errors).toEqual([])
})

test('specs page shows the derived task board', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/insight/specs')
  await page.getByText('triage-ticket').first().click()
  await expect(page.locator('main').getByText(/done/i).first()).toBeVisible()
  expect(errors).toEqual([])
})

test('specs are a row of tiles; double-click opens the spec in its own window', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/insight/specs')
  const tile = page.getByRole('button', { name: /triage-ticket/ }).first()
  await tile.click()
  await expect(tile).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: 'Open spec ↗' })).toBeVisible()

  const [editor] = await Promise.all([page.waitForEvent('popup'), tile.dblclick()])
  await expect(editor).toHaveURL(/\/specs\/edit\/triage-ticket\.md$/)
  await expect(editor.getByRole('button', { name: 'Save' })).toBeDisabled()
  await expect(editor.getByText('Intent').first()).toBeVisible()
  expect(errors).toEqual([])
})

test('a task opens as a readable document that can be dragged and popped out', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/insight/specs?spec=triage-ticket.md')
  await page.getByRole('button', { name: /Ticket model/ }).first().click()
  const panel = page.getByRole('dialog')
  await expect(panel.getByRole('heading', { level: 1 })).toContainText('Ticket model')
  await expect(panel.getByRole('heading', { name: /From the spec/ })).toBeVisible()

  await expect(panel.getByRole('button', { name: /Run with my agent/ })).toHaveCount(0)  // it is done

  const before = await panel.boundingBox()
  const grip = panel.locator('header')
  const box = await grip.boundingBox()
  await page.mouse.move(box!.x + 40, box!.y + 10)
  await page.mouse.down()
  await page.mouse.move(box!.x - 160, box!.y + 90, { steps: 5 })
  await page.mouse.up()
  const after = await panel.boundingBox()
  expect(after!.x).toBeLessThan(before!.x - 100)

  const [window] = await Promise.all([page.waitForEvent('popup'), panel.getByRole('button', { name: /Pop out/ }).click()])
  await expect(window).toHaveURL(/\/specs\/task\/triage-ticket\.md\//)
  await expect(window.getByRole('heading', { level: 1 })).toContainText('Ticket model')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('a model task is built by the scaffold, an agent task waits for what it depends on', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/insight/specs?spec=SPEC-SM-0001-01.md')
  await page.getByRole('button', { name: /Item model/ }).first().click()
  const panel = page.getByRole('dialog')
  await expect(panel.getByText(/not built by the coding agent/)).toBeVisible()
  await expect(panel.getByRole('button', { name: /Generate the scaffold/ })).toBeVisible()
  await expect(panel.getByRole('button', { name: /Run with my agent/ })).toHaveCount(0)
  await panel.getByRole('button', { name: 'Close' }).click()
  await page.getByRole('button', { name: /save/ }).first().click()
  const agent = page.getByRole('dialog')
  await expect(agent.getByRole('button', { name: /Run with my agent/ })).toBeDisabled()
  await expect(agent.getByRole('status')).toContainText('Blocked')
  expect(errors).toEqual([])
})

test('the tasks read as a dependency graph with each task\'s state', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/insight/specs?spec=triage-ticket.md')
  await page.getByRole('button', { name: 'Graph' }).click()
  const graph = page.getByTestId('task-graph')
  await expect(graph).toBeVisible()
  await expect(page.getByLabel('Legend')).toContainText('Running now')
  await graph.locator('button', { hasText: 'Ticket model' }).click()
  await expect(page.getByRole('dialog').getByRole('heading', { level: 1 })).toContainText('Ticket model')
  expect(errors).toEqual([])
})

test('developer telemetry is a settings section, off until a collector is given', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/insight/settings')
  await page.getByRole('button', { name: 'Developer telemetry' }).click()
  await expect(page.getByRole('heading', { name: 'Developer telemetry' })).toBeVisible()
  await expect(page.getByLabel('Share developer actions')).not.toBeChecked()
  await expect(page.getByRole('region', { name: 'Who the events say you are' })).toBeVisible()
  expect(errors).toEqual([])
})

// Who may run a workflow is set on its start node: pick (or create) an IAM role; it lands in metadata.required_group.
test('workflow access: an IAM role gates the trigger', async ({ page }) => {
  const errors = watchErrors(page)
  const role = `e2e_role_${Date.now().toString(36)}`
  await page.goto('/insight/workflows?wf=triage_ticket&agent=__start')
  const access = page.getByRole('region', { name: 'Access' })
  await expect(access.getByLabel('Any signed-in user')).toBeChecked()
  await access.getByLabel('Members of an IAM role').check()
  await access.getByLabel('Role required to run').selectOption('__new')
  await access.getByLabel('New role name').fill(role)
  await access.getByRole('button', { name: 'Create' }).click()
  await expect(access.getByText(`Members of ${role} (0)`)).toBeVisible()
  await expect(page.getByText('✓ valid (draft)')).toBeVisible()
  await page.getByRole('button', { name: 'YAML', exact: true }).click()
  await expect(page.locator('.cm-content')).toContainText(`required_group: ${role}`)
  await page.getByRole('button', { name: 'Canvas', exact: true }).click()
  expect(errors).toEqual([])
})

// Deciding a human step needs approvals:decide as well as the role; Insight says so and grants it.
test('a human step approver role without approvals:decide is flagged and fixed', async ({ page }) => {
  const errors = watchErrors(page)
  const role = `e2e_plain_${Date.now().toString(36)}`
  // a role with no scopes, made from the workflow access picker
  await page.goto('/insight/workflows?wf=triage_ticket&agent=__start')
  const access = page.getByRole('region', { name: 'Access' })
  await access.getByLabel('Members of an IAM role').check()
  await access.getByLabel('Role required to run').selectOption('__new')
  await access.getByLabel('New role name').fill(role)
  await access.getByRole('button', { name: 'Create' }).click()
  await expect(access.getByText(`Members of ${role} (0)`)).toBeVisible()

  await page.goto('/insight/workflows?wf=triage_ticket&agent=review')
  await page.getByRole('button', { name: 'Approval', exact: true }).click()
  const decides = page.getByRole('region', { name: 'Who decides' })
  await decides.getByLabel('Role that decides').selectOption(role)
  await expect(decides.getByText(/lacks the approvals:decide scope/)).toBeVisible()
  await decides.getByRole('button', { name: `Grant approvals:decide to ${role}` }).click()
  await expect(decides.getByText(/lacks the approvals:decide scope/)).toHaveCount(0)
  expect(errors).toEqual([])
})

test('an idea is uploaded from the Ideas page, as a file and as text, and numbered by the CLI', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/insight/ideas')
  await page.getByRole('button', { name: 'Upload idea' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Upload an idea' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Import idea' })).toBeDisabled() // nothing to import yet

  await dialog.getByLabel('Idea files').setInputFiles({
    name: 'notes.md', mimeType: 'text/markdown', buffer: Buffer.from('# Uploaded notes\n\nA brief that came from the browser.\n'),
  })
  await expect(dialog.getByLabel('Files to upload')).toContainText('notes.md')
  await dialog.getByLabel('Idea files').setInputFiles({ name: 'extra.csv', mimeType: 'text/csv', buffer: Buffer.from('a,b\n1,2\n') })
  await expect(dialog.getByLabel('Files to upload').getByRole('listitem')).toHaveCount(2) // a second pick adds to the first
  await dialog.getByLabel('Title (optional)').fill('Uploaded notes') // with several files the CLI would title it from the first one
  await dialog.getByRole('button', { name: 'Import idea' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('heading', { name: 'Uploaded notes' })).toBeVisible()
  await expect(page.locator('main')).toContainText('source/notes.md')
  await expect(page.locator('main')).toContainText('source/extra.csv')

  await page.getByRole('button', { name: 'Upload idea' }).first().click()
  await page.getByLabel('Or write it here').fill('# Typed brief\n\nWritten in Insight.\n')
  await page.getByLabel('Title (optional)').fill('A typed idea')
  await page.getByRole('button', { name: 'Import idea' }).click()
  await expect(page.getByRole('heading', { name: 'A typed idea' })).toBeVisible()
  await expect(page.locator('main')).toContainText('source/idea.md')
  await page.waitForLoadState('networkidle')
  expect(errors).toEqual([])
})

test('generating a spec from an idea asks you to choose a coding agent first', async ({ page }) => {
  await page.goto('/insight/ideas')
  await expect(page.locator('main')).toContainText('choose it first')
  await expect(page.getByRole('button', { name: /Generate a spec with my agent/ })).toHaveCount(0)
})

test('an LLM agent picks its model from the configured AI models, and the whole agent is editable as YAML', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/insight/workflows?wf=triage_ticket&agent=classify')
  await page.getByRole('button', { name: 'Prompt', exact: true }).click()
  const model = page.getByLabel('AI model', { exact: true })
  await expect(model).toHaveValue('default') // the preset the sample's agent names
  await expect(model.locator('option', { hasText: 'default' })).toHaveCount(1) // configured in llms/
  await expect(page.getByText('Configured on the')).toBeVisible()
  await model.selectOption({ label: 'Other: a provider/model id…' })
  await expect(page.getByLabel('AI model (provider/model)')).toBeVisible()

  await page.getByRole('button', { name: 'Agent YAML', exact: true }).click()
  const yaml = page.getByLabel('Agent YAML', { exact: true }).locator('.cm-content')
  await expect(yaml).toContainText('id: classify')
  await expect(yaml).toContainText('engine: llm')
  await page.waitForLoadState('networkidle')
  expect(errors).toEqual([])
})

test('retrieve-and-answer adds a search and an answer step, and the search picks its collection', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/insight/workflows?wf=triage_ticket')
  await page.getByRole('button', { name: /Add step/ }).click()
  await page.getByRole('button', { name: '+ Retrieve and answer' }).click()
  await page.getByRole('button', { name: 'Engine', exact: true }).click()
  const collection = page.getByLabel('Collection', { exact: true })
  await expect(collection).toHaveValue('kb') // configured in models/collections.yaml
  await expect(collection.locator('option', { hasText: 'kb' })).toHaveCount(1)
  await expect(page.getByText('Support articles')).toBeVisible()
  await page.getByLabel('Results', { exact: true }).fill('3')
  await page.getByLabel('Results', { exact: true }).blur()

  await page.getByRole('button', { name: 'Agent YAML', exact: true }).click()
  const yaml = page.getByLabel('Agent YAML', { exact: true }).locator('.cm-content')
  await expect(yaml).toContainText('tuvl.data_search')
  await expect(yaml).toContainText('top_k: 3')
  await expect(yaml).toContainText('default: rag_answer')
  await page.waitForLoadState('networkidle')
  expect(errors).toEqual([])
})

test('a loop searches a configured collection as a tool', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/insight/workflows?wf=triage_ticket')
  await page.getByRole('button', { name: /Add step/ }).click()
  await page.getByRole('button', { name: '+ Autonomous loop' }).click()
  await page.getByRole('button', { name: 'Loop', exact: true }).click()
  await page.getByLabel('New collection tool', { exact: true }).selectOption('kb')
  await expect(page.getByLabel('Collection tool 1', { exact: true })).toHaveValue('kb')

  await page.getByRole('button', { name: 'Agent YAML', exact: true }).click()
  const yaml = page.getByLabel('Agent YAML', { exact: true }).locator('.cm-content')
  await expect(yaml).toContainText('collection: kb')
  await page.waitForLoadState('networkidle')
  expect(errors).toEqual([])
})
