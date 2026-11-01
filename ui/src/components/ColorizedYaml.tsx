import { renderColorizedYaml } from '../lib/colorizeYaml'

/**
 * JSX convenience wrapper around `renderColorizedYaml` (see lib/colorizeYaml.tsx
 * for the colorizing logic — kept in a separate plain-function module so this
 * file only exports a component, per react-refresh/only-export-components).
 */
export function ColorizedYaml({
  yaml,
  colorizeListItems = true,
}: {
  yaml: string
  colorizeListItems?: boolean
}) {
  return <>{renderColorizedYaml(yaml, colorizeListItems)}</>
}
