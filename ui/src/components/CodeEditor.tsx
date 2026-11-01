import CodeMirror from '@uiw/react-codemirror'
import { yaml } from '@codemirror/lang-yaml'
import { python } from '@codemirror/lang-python'
import { json } from '@codemirror/lang-json'
import { markdown } from '@codemirror/lang-markdown'
import { linter, type Diagnostic } from '@codemirror/lint'
import { oneDark } from '@codemirror/theme-one-dark'
import { useMemo } from 'react'
import { useUIStore } from '../store'

export interface LineIssue {
  line: number
  message: string
  severity: 'error' | 'warning'
}

const LANGUAGES = { yaml, python, json, markdown } as const

/** A CodeMirror editor; `issues` are shown as line diagnostics (1-based lines). */
export function CodeEditor({
  value,
  onChange,
  language = 'yaml',
  issues = [],
  readOnly = false,
  height = '100%',
}: {
  value: string
  onChange?: (value: string) => void
  language?: keyof typeof LANGUAGES
  issues?: LineIssue[]
  readOnly?: boolean
  height?: string
}) {
  const theme = useUIStore((s) => s.theme)
  const extensions = useMemo(
    () => [
      LANGUAGES[language](),
      linter((view) =>
        issues
          .filter((i) => i.line >= 1 && i.line <= view.state.doc.lines)
          .map((i): Diagnostic => {
            const line = view.state.doc.line(i.line)
            return { from: line.from, to: line.to, severity: i.severity, message: i.message }
          }),
      ),
    ],
    [language, issues],
  )
  return (
    <CodeMirror
      value={value}
      height={height}
      theme={theme === 'dark' ? oneDark : 'light'}
      extensions={extensions}
      editable={!readOnly}
      onChange={onChange}
      basicSetup={{ foldGutter: true, highlightActiveLine: !readOnly }}
      className="text-[13px] h-full"
    />
  )
}
