import ReactMarkdown from 'react-markdown'

/** Markdown in Insight's dark theme: headings, lists, code, quotes and tables read like a document. */
export function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      components={{
        h1: (p) => <h1 className="mb-3 text-xl font-semibold text-slate-50" {...p} />,
        h2: (p) => <h2 className="mt-5 mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400" {...p} />,
        h3: (p) => <h3 className="mt-4 mb-1.5 text-base font-semibold text-slate-100" {...p} />,
        h4: (p) => <h4 className="mt-3 mb-1 text-sm font-semibold text-slate-200" {...p} />,
        h5: (p) => <h5 className="mt-3 mb-1 text-sm font-medium text-slate-200" {...p} />,
        h6: (p) => <h6 className="mt-3 mb-1 text-xs font-medium text-slate-300" {...p} />,
        p: (p) => <p className="my-2 text-sm leading-relaxed text-slate-200" {...p} />,
        ul: (p) => <ul className="my-2 list-disc space-y-1 pl-5 text-sm text-slate-200" {...p} />,
        ol: (p) => <ol className="my-2 list-decimal space-y-1 pl-5 text-sm text-slate-200" {...p} />,
        blockquote: (p) => <blockquote className="my-2 rounded border-l-2 border-slate-600 bg-slate-800/40 py-1 pl-3 text-slate-300" {...p} />,
        hr: () => <hr className="my-4 border-slate-700" />,
        a: (p) => <a className="text-indigo-300 underline" target="_blank" rel="noreferrer" {...p} />,
        strong: (p) => <strong className="font-semibold text-slate-50" {...p} />,
        pre: (p) => <pre className="my-3 overflow-auto rounded border border-slate-700 bg-slate-950/70 p-3 text-xs leading-snug text-slate-200" {...p} />,
        code: ({ className, ...p }) => (
          <code className={className ? `font-mono ${className}` : 'rounded bg-slate-800 px-1 py-0.5 font-mono text-[0.85em] text-slate-100'} {...p} />
        ),
        table: (p) => <table className="my-3 w-full border-collapse text-xs" {...p} />,
        th: (p) => <th className="border border-slate-700 bg-slate-800 px-2 py-1 text-left font-medium" {...p} />,
        td: (p) => <td className="border border-slate-700 px-2 py-1 align-top" {...p} />,
      }}
    >
      {children}
    </ReactMarkdown>
  )
}
