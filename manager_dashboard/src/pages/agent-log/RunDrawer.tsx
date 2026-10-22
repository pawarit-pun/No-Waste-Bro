import { Link } from 'react-router-dom'
import { RunSteps } from '../../components/RunSteps'
import { Drawer } from '../../components/ui/Drawer'
import { formatDuration, formatWhen } from '../../lib/format'
import type { PipelineRun } from '../../types/pipeline'
import { RunStatusBadge } from './RunStatusBadge'
import { runDuration } from './RunTable'
import { useRunReviewCounts } from './useRunReviewCounts'

function ReviewOutcome({ runId }: { runId: string | null }) {
  const counts = useRunReviewCounts(runId)
  if (!runId) return <p className="text-sm text-slate-500">This run did not reach the scan result.</p>
  if (!counts) return <p className="text-sm text-slate-400">Loading…</p>
  const total = counts.waiting + counts.approved + counts.rejected
  if (total === 0) return <p className="text-sm text-slate-500">No plans from this run in the review queue.</p>
  const boxes = [
    { label: 'Waiting', value: counts.waiting, cls: 'text-brand' },
    { label: 'Approved', value: counts.approved, cls: 'text-emerald-700' },
    { label: 'Rejected', value: counts.rejected, cls: 'text-red-700' },
  ]
  return (
    <div>
      <div className="grid grid-cols-3 gap-2">
        {boxes.map((b) => (
          <div key={b.label} className="rounded-xl border border-slate-200 px-3 py-2.5">
            <p className="text-xs text-slate-500">{b.label}</p>
            <p className={`font-mono text-xl font-semibold ${b.cls}`}>{b.value}</p>
          </div>
        ))}
      </div>
      {counts.waiting > 0 && (
        <Link to="/review-queue" className="mt-2 inline-block text-sm font-semibold text-brand hover:underline">Open review queue →</Link>
      )}
    </div>
  )
}

export function RunDrawer({ run, onClose }: { run: PipelineRun | null; onClose: () => void }) {
  if (!run) return null
  const duration = runDuration(run)
  return (
    <Drawer
      open
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <span className="text-lg font-bold text-slate-900">Run · {formatWhen(run.requested_at)}</span>
          <RunStatusBadge status={run.status} />
        </div>
      }
      subtitle={
        <p className="text-[13px] text-slate-500">
          {duration != null && <>Duration {formatDuration(duration)} · </>}
          <span className="font-mono">{run.pipeline_run_id.slice(0, 8)}</span>
        </p>
      }
    >
      <p className="mb-3 text-[11px] font-bold tracking-[0.08em] text-slate-400 uppercase">Steps</p>
      <div className="mb-5"><RunSteps run={run} /></div>

      {run.message && run.status !== 'FAILED' && (
        <p className="mb-4 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">{run.message}</p>
      )}
      {run.error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2">
          <p className="text-xs font-bold tracking-wide text-red-700 uppercase">Error</p>
          <pre className="mt-1 max-h-48 overflow-auto font-mono text-xs whitespace-pre-wrap text-red-800">{run.error}</pre>
        </div>
      )}

      <p className="mb-2 text-[11px] font-bold tracking-[0.08em] text-slate-400 uppercase">Manager review of this run</p>
      <ReviewOutcome runId={run.run_id} />
    </Drawer>
  )
}
