import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/EmptyState'
import { RunDrawer } from './RunDrawer'
import { RunTable } from './RunTable'
import { useAgentRuns } from './useAgentRuns'

export function AgentLogPage() {
  const { runs, error, reload } = useAgentRuns()
  const [openId, setOpenId] = useState<string | null>(null)
  const [, setTick] = useState(0)

  // มีรอบที่กำลังรัน: ให้ระยะเวลาขยับทุก 5 วินาที
  const running = runs?.some((r) => r.status === 'RUNNING' || r.status === 'QUEUED') ?? false
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setTick((n) => n + 1), 5000)
    return () => clearInterval(t)
  }, [running])

  const openRun = runs?.find((r) => r.pipeline_run_id === openId) ?? null

  return (
    <div className="px-8 py-7">
      <h1 className="text-3xl font-bold tracking-tight text-slate-900">Pipeline runs</h1>
      <p className="mt-1 text-[15px] text-slate-600">Every AI run, from scan to the plans sent for review.</p>

      <section className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white">
        {runs === null && !error ? (
          <div className="space-y-3 px-5 py-6">
            {[0, 1, 2].map((i) => <div key={i} className="h-12 animate-pulse rounded-lg bg-slate-100" />)}
          </div>
        ) : error && runs === null ? (
          <EmptyState title="Could not load pipeline runs">
            <p>{error}</p>
            <Button className="mt-3" size="sm" onClick={() => void reload()}>Try again</Button>
          </EmptyState>
        ) : runs && runs.length === 0 ? (
          <EmptyState title="No pipeline runs yet">Runs appear here as soon as the AI pipeline starts.</EmptyState>
        ) : (
          <RunTable runs={runs ?? []} onOpen={(r) => setOpenId(r.pipeline_run_id)} />
        )}

        {runs && runs.length > 0 && (
          <div className="border-t border-slate-200 px-5 py-3 text-[13px] text-slate-500">
            {runs.length} most recent run{runs.length > 1 ? 's' : ''}
          </div>
        )}
      </section>

      <RunDrawer run={openRun} onClose={() => setOpenId(null)} />
    </div>
  )
}
