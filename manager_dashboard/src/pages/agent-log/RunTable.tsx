import { Button } from '../../components/ui/Button'
import { formatDuration, formatWhen, secondsBetween } from '../../lib/format'
import type { PipelineRun } from '../../types/pipeline'
import { RunStatusBadge } from './RunStatusBadge'

const TH = 'px-4 py-3 text-left text-[13px] font-semibold text-slate-600 whitespace-nowrap'
const TD = 'px-4 py-4 align-top'

export const runDuration = (r: PipelineRun) =>
  r.status === 'QUEUED' ? null : secondsBetween(r.started_at ?? r.requested_at, r.finished_at)

const num = (v: number | null | undefined) => (v == null ? '—' : v.toLocaleString('en-US'))

export function RunTable({ runs, onOpen }: { runs: PipelineRun[]; onOpen: (run: PipelineRun) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead className="border-y border-slate-200 bg-slate-50">
          <tr>
            <th className={`${TH} pl-5`}>Started</th>
            <th className={TH}>Status</th>
            <th className={TH}>Duration</th>
            <th className={`${TH} text-right`}>Lots → at risk</th>
            <th className={`${TH} text-right`}>Decisions</th>
            <th className={`${TH} text-right`}>Plans to review</th>
            <th className={TH}>Message</th>
            <th className="w-24" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {runs.map((r) => {
            const scan = r.steps.SCAN?.summary
            const duration = runDuration(r)
            const plans = r.steps.TASKS?.summary?.plans_queued ?? r.tasks_created
            return (
              <tr key={r.pipeline_run_id} onClick={() => onOpen(r)}
                className="cursor-pointer transition-colors hover:bg-orange-50/40">
                <td className={`${TD} pl-5 font-mono text-sm whitespace-nowrap text-slate-700`}>{formatWhen(r.requested_at)}</td>
                <td className={TD}><RunStatusBadge status={r.status} /></td>
                <td className={`${TD} font-mono text-sm text-slate-700`}>{duration == null ? '—' : formatDuration(duration)}</td>
                <td className={`${TD} text-right font-mono text-sm text-slate-900`}>
                  {scan?.lots != null ? `${num(scan.lots)} → ${num(scan.at_risk_lots ?? r.at_risk_lots)}` : '—'}
                </td>
                <td className={`${TD} text-right font-mono text-sm text-slate-900`}>{num(r.decisions_created)}</td>
                <td className={`${TD} text-right font-mono text-sm text-slate-900`}>{num(plans)}</td>
                <td className={`${TD} max-w-96`}>
                  {r.status === 'FAILED' && r.error ? (
                    <p className="line-clamp-2 text-sm text-red-600">{r.error}</p>
                  ) : r.status === 'RUNNING' ? (
                    <p className="text-sm text-slate-600">Running step {r.current_step ?? '…'}</p>
                  ) : (
                    <p className="line-clamp-2 text-sm text-slate-600">{r.message ?? '—'}</p>
                  )}
                </td>
                <td className="py-4 pr-5 text-right align-top">
                  <Button size="sm" variant="neutral" onClick={(e) => { e.stopPropagation(); onOpen(r) }}>View</Button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
