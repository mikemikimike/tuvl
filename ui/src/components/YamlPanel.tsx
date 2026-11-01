import { useRef, useState } from 'react'
import { dump } from 'js-yaml'
import { ColorizedYaml } from './ColorizedYaml'
import { parseYaml } from '../lib/yaml'

interface YamlPanelProps {
  /** The object the form currently describes; shown as the read-only preview. */
  obj: object
  /** What the editor starts from when "Advanced" is opened (defaults to `obj`). */
  seedObj?: object
  editable?: boolean
  title?: string
  saveLabel?: string
  className?: string
  advanced: boolean
  onAdvancedChange: (v: boolean) => void
  /** Called with every successfully parsed edit so the form can follow the YAML. */
  onParsed: (doc: unknown) => void
  /** Returns a message when the parsed document must not be saved yet. */
  validate?: (doc: unknown) => string | null
  onSave: () => Promise<void>
  savePending: boolean
  saveError: string | null
}

/** A YAML preview beside a form, with an "Advanced" raw editor that feeds the form back. */
export function YamlPanel({
  obj,
  seedObj,
  editable = true,
  title = 'YAML',
  saveLabel = 'Save',
  className = 'border-l border-slate-800',
  advanced,
  onAdvancedChange,
  onParsed,
  validate,
  onSave,
  savePending,
  saveError,
}: YamlPanelProps) {
  const [rawYaml, setRawYaml] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const originalYamlRef = useRef('')

  const handleEnterAdvanced = () => {
    const seed = dump(seedObj ?? obj, { lineWidth: -1 })
    originalYamlRef.current = seed
    setRawYaml(seed)
    setParseError(null)
    setValidationError(null)
    onAdvancedChange(true)
  }

  const handleYamlChange = (text: string) => {
    setRawYaml(text)
    setValidationError(null)
    try {
      const parsed = parseYaml(text)
      if (parsed && typeof parsed === 'object') onParsed(parsed)
      setParseError(null)
    } catch (e: unknown) {
      setParseError(e instanceof Error ? e.message : 'Invalid YAML')
    }
  }

  const handleValidateAndSave = async () => {
    if (parseError) {
      setValidationError('Fix YAML syntax errors before saving.')
      return
    }
    if (validate) {
      try {
        const problem = validate(parseYaml(rawYaml))
        if (problem) {
          setValidationError(problem)
          return
        }
      } catch {
        setValidationError('Invalid YAML — cannot parse.')
        return
      }
    }
    setValidationError(null)
    await onSave()
  }

  const previewYaml = advanced ? rawYaml : dump(obj, { lineWidth: -1 })
  const displayError = parseError || validationError || saveError

  return (
    <div className={`flex flex-col h-full ${className}`}>
      <div className="px-4 py-3 border-b border-slate-800 flex-shrink-0 flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest">{title}</span>
        {editable && (
          <button
            type="button"
            onClick={advanced ? () => onAdvancedChange(false) : handleEnterAdvanced}
            className={`text-xs px-2 py-1 rounded border transition-colors ${
              advanced
                ? 'border-sky-600 text-sky-400 bg-sky-900/20 hover:bg-sky-900/40'
                : 'border-slate-700 text-slate-500 hover:text-slate-300 hover:border-slate-600'
            }`}
          >
            {advanced ? '← Preview' : 'Advanced'}
          </button>
        )}
      </div>
      {advanced ? (
        <div className="flex flex-col flex-1 min-h-0">
          <textarea
            value={rawYaml}
            onChange={(e) => handleYamlChange(e.target.value)}
            className="flex-1 min-h-0 w-full resize-none bg-transparent p-4 text-xs font-mono text-slate-200 outline-none leading-5 focus:ring-1 focus:ring-inset focus:ring-sky-800"
            spellCheck={false}
            autoComplete="off"
          />
          <div className="flex-shrink-0 border-t border-slate-800 px-4 py-3 flex flex-col gap-2">
            {displayError && <p className="text-xs text-rose-400 font-mono break-all">{displayError}</p>}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleValidateAndSave}
                disabled={savePending || !!parseError}
                className="flex-1 px-3 py-2 rounded-lg bg-sky-600 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-40 transition-colors"
              >
                {savePending ? 'Saving…' : saveLabel}
              </button>
              <button
                type="button"
                onClick={() => {
                  handleYamlChange(originalYamlRef.current)
                  onAdvancedChange(false)
                }}
                className="px-3 py-2 rounded-lg border border-slate-700 text-sm text-slate-300 hover:bg-slate-800 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-4">
          <pre className="text-xs font-mono leading-5 select-all whitespace-pre">
            <ColorizedYaml yaml={previewYaml} />
          </pre>
        </div>
      )}
    </div>
  )
}
