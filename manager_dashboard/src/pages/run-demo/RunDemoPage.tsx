import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AgentWatchCard } from '../../components/agent/AgentWatchCard'
import { RunSteps } from '../../components/RunSteps'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/EmptyState'
import { PlayIcon, ResetIcon } from '../../components/ui/icons'
import { Select } from '../../components/ui/Select'
import { Toast, type ToastMessage } from '../../components/ui/Toast'
import { errorMessage } from '../../lib/api'
import { formatDuration, formatLongDate, formatWhen, secondsBetween } from '../../lib/format'
import type { StepName } from '../../types/pipeline'
import { RunStatusBadge } from '../agent-log/RunStatusBadge'
import { useRunReviewCounts } from '../agent-log/useRunReviewCounts'
import { useRunDemo } from './useRunDemo'

const STOP_OPTIONS: { value: StepName; label: string }[] = [
  { value: 'TASKS', label: 'Full run (scan → optimize → plans)' },
  { value: 'OPTIMIZE', label: 'Stop after optimizer' },
  { value: 'SCAN', label: 'Stop after risk scan' },
]

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2">
      <dt className="text-sm text-slate-500">{label}</dt>
      <dd className="text-right text-sm font-semibold text-slate-900">{children}</dd>
    </div>
  )
}

function Card({ title, children, className = '' }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl border border-slate-200 bg-white ${className}`}>
      <h2 className="border-b border-slate-200 px-5 py-3.5 font-semibold text-slate-900">{title}</h2>
      <div className="px-5 py-4">{children}</div>
    </section>
  )
}

export function RunDemoPage() {
  const { runs, runsError, latest, active, readiness, avgSeconds, start, reset } = useRunDemo()
  const [stopAfter, setStopAfter] = useState<StepName>('TASKS')
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [toast, setToast] = useState<ToastMessage | null>(null)
  const [, setTick] = useState(0)
  const waiting = useRunReviewCounts(latest?.run_id ?? null)?.waiting ?? 0
  const dismissToast = useCallback(() => setToast(null), [])

  // มีรอบกำลังรัน: นาฬิกาเดินทุกวินาที
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [active])

  const busy = !!active || starting || resetting
  const noLots = readiness?.idleLots === 0

  const handleStart = async () => {
    setStarting(true)
    setStartError(null)
    try {
      await start(stopAfter)
    } catch (err) {
      setStartError(errorMessage(err, 'Could not start the agent.'))
    } finally {
      setStarting(false)
    }
  }

  const handleReset = async () => {
    setResetting(true)
    try {
      const res = await reset()
      setConfirmReset(false)
      setToast({
        id: Date.now(), tone: 'success',
        text: `Demo data reset for ${res.demo_date}. All ${res.idle_lots} lots are IDLE and ready to scan.`,
      })
    } catch (err) {
      setToast({ id: Date.now(), tone: 'error', text: errorMessage(err, 'Reset failed.') })
    } finally {
      setResetting(false)
    }
  }

  const totalSeconds = latest && latest.status !== 'QUEUED' ? secondsBetween(latest.started_at ?? latest.requested_at, latest.finished_at) : null

  return (
    <div className="px-8 py-7">
      <h1 className="text-3xl font-bold tracking-tight text-slate-900">Run demo</h1>
      <p className="mt-1 text-[15px] text-slate-600">Start the AI pipeline and watch each step live.</p>

      {/* การ์ดเรียงลงมาคอลัมน์เดียว: Run the agent → Demo data → Latest run */}
      <div className="mt-6 space-y-5">
        <div className="space-y-5">
          <Card title="Run the agent">
            <dl className="divide-y divide-slate-100">
              <InfoRow label="System date">
                {readiness ? formatLongDate(readiness.referenceDate) : '—'}
              </InfoRow>
              <InfoRow label="Lots ready to scan">
                <span className={noLots ? 'text-red-600' : ''}>{readiness ? readiness.idleLots : '—'}</span>
              </InfoRow>
              <InfoRow label="Usually takes">{avgSeconds != null ? `~${formatDuration(avgSeconds)}` : '—'}</InfoRow>
            </dl>

            {noLots && (
              <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
                No lots are waiting to be scanned. Reset the demo data first.
              </p>
            )}

            <Select label="Run" value={stopAfter} onChange={(e) => setStopAfter(e.target.value as StepName)}
              disabled={busy} className="mt-4 w-full">
              {STOP_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </Select>

            <Button variant="primary" className="mt-3 h-12 w-full text-base" disabled={busy} onClick={handleStart}>
              <PlayIcon className="size-4" />
              {active ? 'Agent is running…' : starting ? 'Starting…' : 'Run agent now'}
            </Button>
            {active && <p className="mt-2 text-center text-xs text-slate-500">One run at a time. Wait for this run to finish.</p>}
            {startError && <p className="mt-2 text-sm text-red-600">{startError}</p>}
          </Card>

          <AgentWatchCard />

          <Card title="Demo data">
            <p className="text-sm text-slate-600">
              Put every lot back to its starting state (IDLE) so the agent can scan them again.
            </p>
            {!confirmReset ? (
              <Button variant="danger" className="mt-3 w-full" disabled={busy} onClick={() => setConfirmReset(true)}>
                <ResetIcon className="size-4" />
                Reset demo data
              </Button>
            ) : (
              <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3">
                <p className="text-sm font-semibold text-red-800">This deletes all data from previous runs:</p>
                <ul className="mt-1 list-disc pl-5 text-sm text-red-700">
                  <li>every plan in the review queue</li>
                  <li>every staff task, decision and scan result</li>
                  <li>lots created by the demo, and all kitchen bookings</li>
                  <li>Manager Agent notifications and proposals</li>
                </ul>
                <div className="mt-3 flex gap-2">
                  <Button size="sm" className="flex-1" disabled={resetting} onClick={() => setConfirmReset(false)}>Cancel</Button>
                  <Button size="sm" variant="danger" className="flex-1" disabled={resetting || !!active} onClick={handleReset}>
                    {resetting ? 'Resetting…' : 'Yes, reset'}
                  </Button>
                </div>
              </div>
            )}
          </Card>
        </div>

        {/* ---------- ติดตามรอบล่าสุดแบบ realtime ---------- */}
        <Card title={active ? 'Live progress' : 'Latest run'}>
          {runs === null && !runsError ? (
            <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="h-12 animate-pulse rounded-lg bg-slate-100" />)}</div>
          ) : runsError && runs === null ? (
            <EmptyState title="Could not load agent runs"><p>{runsError}</p></EmptyState>
          ) : !latest ? (
            <EmptyState title="No runs yet">Press “Run agent now” to start the first run.</EmptyState>
          ) : (
            <div>
              <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-slate-900">Run · {formatWhen(latest.requested_at)}</span>
                  <RunStatusBadge status={latest.status} />
                </div>
                <span className="font-mono text-sm text-slate-500">
                  {totalSeconds != null ? formatDuration(totalSeconds) : 'Waiting for worker…'}
                </span>
              </div>

              <RunSteps run={latest} live />

              {latest.status === 'SUCCEEDED' && (
                <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-emerald-50 px-4 py-3">
                  <p className="text-sm text-emerald-800">{latest.message ?? 'Run finished.'}</p>
                  {waiting > 0 && (
                    <Link to="/review-queue"
                      className="inline-flex h-9 items-center rounded-lg bg-brand px-3.5 text-sm font-semibold text-white hover:bg-[#d4551f]">
                      Open review queue ({waiting} waiting)
                    </Link>
                  )}
                </div>
              )}
              {latest.status === 'FAILED' && latest.error && (
                <div className="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3">
                  <p className="text-xs font-bold tracking-wide text-red-700 uppercase">
                    Failed{latest.current_step ? ` at ${latest.current_step}` : ''}
                  </p>
                  <pre className="mt-1 max-h-40 overflow-auto font-mono text-xs whitespace-pre-wrap text-red-800">{latest.error}</pre>
                </div>
              )}

              <Link to="/pipeline-runs" className="mt-4 inline-block text-sm font-semibold text-brand hover:underline">View all runs in Pipeline runs →</Link>
            </div>
          )}
        </Card>
      </div>

      <Toast toast={toast} onDismiss={dismissToast} />
    </div>
  )
}
