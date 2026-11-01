import { useNavigate } from 'react-router-dom'
import type { ExampleTrace, SpecVerify, StepTrace } from '../devApi'
import { FindingList } from './FindingsView'

const IMPL: Record<StepTrace['impl'], { label: string; cls: string }> = {
  ok: { label: '✓', cls: 'text-emerald-400' },
  pending: { label: 'pending', cls: 'text-amber-400' },
  mismatch: { label: '✗ mismatch', cls: 'text-rose-400' },
  missing: { label: '✗ missing', cls: 'text-rose-400' },
}

const TEST: Record<ExampleTrace['status'], string> = {
  passed: 'bg-emerald-900/60 text-emerald-300',
  stubbed: 'bg-amber-900/60 text-amber-300',
  failed: 'bg-rose-900/60 text-rose-300',
  missing: 'bg-slate-700 text-slate-300',
  'not run': 'bg-slate-800 text-slate-400',
}

function tests(step: StepTrace, ran: boolean): string {
  if (step.tests.passed.length) return `${step.tests.passed.length} passed`
  if (step.tests.mocked.length) return `mocked in ${step.tests.mocked.length}`
  return ran ? '—' : 'not run'
}

/** `tuvl verify spec`: spec step → workflow agent → tests. A step opens its node on the canvas. */
export function TraceView({ verify, onRunTests, running }: { verify: SpecVerify | undefined; onRunTests: () => void; running: boolean }) {
  const navigate = useNavigate()
  if (!verify) return <p className="text-xs text-slate-500">Comparing the spec with the project…</p>
  const s = verify.summary
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <span className={verify.errors ? 'text-rose-400' : 'text-emerald-400'}>{verify.errors} mismatch(es)</span>
        <span>· implemented {s.implemented}/{s.steps} · exercised by real tests {s.exercised}/{s.steps}</span>
        <span className="flex-1" />
        <button className="px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40" disabled={running} onClick={onRunTests}
          title="Runs the project's tests offline (zero tokens)">{running ? 'Running tests…' : 'Run tests'}</button>
      </div>
      {verify.flows.map((flow) => (
        <div key={flow.flow}>
          <p className="text-xs font-medium text-slate-200 mb-1">
            {flow.flow} {!flow.workflow && <span className="text-amber-400">(no workflow yet)</span>}
          </p>
          <table className="w-full text-xs">
            <tbody>
              {flow.steps.map((st) => (
                <tr key={st.step} className="border-t border-slate-800">
                  <td className="py-1 pr-2">
                    <button className="font-mono text-indigo-300 hover:underline disabled:text-slate-400 disabled:no-underline" disabled={!flow.workflow}
                      onClick={() => navigate(`/workflows?wf=${encodeURIComponent(flow.flow)}&agent=${encodeURIComponent(st.step)}`)}>{st.step}</button>
                  </td>
                  <td className="py-1 pr-2 text-slate-400 truncate max-w-[14rem]">{st.engine}</td>
                  <td className="py-1 pr-2 font-mono text-slate-500">:{st.line}</td>
                  <td className={`py-1 pr-2 ${IMPL[st.impl].cls}`}>{IMPL[st.impl].label}</td>
                  <td className="py-1 text-slate-400">{tests(st, verify.tests_run)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {verify.examples.length > 0 && (
        <div>
          <p className="text-xs font-medium text-slate-200 mb-1">Examples</p>
          <ul className="space-y-1">
            {verify.examples.map((ex) => (
              <li key={ex.name} className="text-xs">
                <div className="flex items-center gap-2">
                  <span className={`rounded px-1.5 ${TEST[ex.status]}`}>{ex.status}</span>
                  <span className="text-slate-200">{ex.name}</span>
                  <span className="font-mono text-slate-500">:{ex.line}</span>
                </div>
                {ex.failures.map((f, i) => <p key={i} className="ml-14 text-rose-300">{f}</p>)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {verify.findings.length > 0 && <FindingList findings={verify.findings} />}
    </div>
  )
}
