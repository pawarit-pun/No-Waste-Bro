import { useMemo, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/EmptyState'
import { ResetIcon } from '../../components/ui/icons'
import { formatDay, formatLongDate, formatWhen, systemNow } from '../../lib/format'
import type { DailyReport } from '../../types/daily'
import { EveningCard, MorningCard } from './ReportCards'
import { useOverview } from './useOverview'

function Stat({ label, value, sub, to }: { label: string; value: ReactNode; sub?: ReactNode; to?: string }) {
  const body = (
    <div className="h-full rounded-2xl border border-slate-200 bg-white px-5 py-4 transition-colors hover:border-brand/40">
      <p className="text-[13px] text-slate-500">{label}</p>
      <p className="mt-1 font-mono text-2xl font-semibold text-slate-900">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </div>
  )
  return to ? <Link to={to}>{body}</Link> : body
}

const one = (n?: number) => (n == null ? '—' : `${Math.round(n * 10) / 10}`)

export function OverviewPage() {
  const { data, error, refreshing, reload } = useOverview()
  const today = data?.reports.reference_date ?? data?.inventory.reference_date ?? ''

  const stats = useMemo(() => {
    if (!data) return null
    const onHand = data.inventory.items.filter((l) => l.current_quantity > 0)
    const level = (lv: string) => onHand.filter((l) => l.latest_assessment?.risk_level === lv).length
    const now = systemNow(data.inventory.reference_date)
    const overdue = data.tasks.filter((t) => t.due_by && new Date(t.due_by) < now).length
    const days = (data.kitchen?.departments ?? []).flatMap((d) => d.days.filter((x) => x.capacity_date === data.inventory.reference_date))
    return {
      critical: level('CRITICAL'), high: level('HIGH'),
      waiting: data.reviews.counts.waiting, open: data.tasks.length, overdue,
      booked: days.reduce((n, d) => n + d.booked_hrs, 0), available: days.reduce((n, d) => n + d.available_hrs, 0),
    }
  }, [data])

  const byDate = useMemo(() => {
    const map = new Map<string, { MORNING?: DailyReport; EVENING?: DailyReport }>()
    for (const r of data?.reports.items ?? []) map.set(r.report_date, { ...map.get(r.report_date), [r.kind]: r })
    return [...map.entries()].sort((a, b) => b[0].localeCompare(a[0]))
  }, [data])
  const todayReports = byDate.find(([d]) => d === today)?.[1] ?? {}

  return (
    <div className="px-8 py-7">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">Overview</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-[15px] text-slate-600">
            {today ? formatLongDate(today) : 'Today'}
            {data?.lastRun && (
              <>
                <span className="text-slate-300">·</span>
                Last pipeline run {formatWhen(data.lastRun.requested_at)}
              </>
            )}
          </p>
        </div>
        <Button size="sm" onClick={() => void reload()} disabled={refreshing}>
          <ResetIcon className={`size-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {error && !data ? (
        <section className="mt-6 rounded-2xl border border-slate-200 bg-white">
          <EmptyState title="Could not load the overview">
            <p>{error}</p>
            <Button className="mt-3" size="sm" onClick={() => void reload()}>Try again</Button>
          </EmptyState>
        </section>
      ) : !data || !stats ? (
        <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <div key={i} className="h-24 animate-pulse rounded-2xl bg-slate-100" />)}
        </div>
      ) : (
        <>
          <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="Lots at risk" value={stats.critical + stats.high} sub={`${stats.critical} critical · ${stats.high} high`} to="/inventory" />
            <Stat label="Plans waiting approval" value={stats.waiting} sub="in the review queue" to="/review-queue" />
            <Stat label="Open staff tasks" value={stats.open} to="/task-log"
              sub={stats.overdue ? <span className="font-semibold text-red-600">{stats.overdue} overdue</span> : 'none overdue'} />
            <Stat label="Kitchen hours today" value={`${one(stats.booked)} / ${one(stats.available)}`} sub="booked / available" to="/kitchen" />
          </div>

          <div className="mt-6 grid gap-5 xl:grid-cols-2">
            <MorningCard report={todayReports.MORNING ?? null} />
            <EveningCard report={todayReports.EVENING ?? null} />
          </div>

          <section className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white">
            <div className="px-5 pt-4 pb-3">
              <h2 className="font-semibold text-slate-900">Last 7 days</h2>
              <p className="text-[13px] text-slate-500">
                From the agent’s daily reports. With a fixed DEMO_DATE every run writes the same day, so the demo shows one row.
              </p>
            </div>
            {byDate.length === 0 ? (
              <EmptyState title="No daily reports yet">Reports appear after the first pipeline run of the day.</EmptyState>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead className="border-y border-slate-200 bg-slate-50 text-[13px] text-slate-600">
                    <tr>
                      <th className="px-5 py-3 text-left font-semibold">Date</th>
                      <th className="px-4 py-3 text-right font-semibold">Decisions</th>
                      <th className="px-4 py-3 text-right font-semibold">Planned disposal kg</th>
                      <th className="px-4 py-3 text-right font-semibold">vs baseline</th>
                      <th className="px-4 py-3 text-right font-semibold">Tasks done</th>
                      <th className="px-4 py-3 text-right font-semibold">Rescued kg</th>
                      <th className="px-5 py-3 text-right font-semibold">Disposal kg</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 font-mono">
                    {byDate.map(([date, r]) => {
                      const m = r.MORNING?.metrics
                      const e = r.EVENING?.metrics
                      return (
                        <tr key={date}>
                          <td className="px-5 py-3 font-sans text-slate-800">{formatDay(`${date}T12:00:00+07:00`)}</td>
                          <td className="px-4 py-3 text-right">{m?.decisions ?? '—'}</td>
                          <td className="px-4 py-3 text-right">{one(m?.planned_disposal_kg)}</td>
                          <td className="px-4 py-3 text-right">{m?.improvement_vs_baseline_thb != null ? `฿${Math.round(m.improvement_vs_baseline_thb).toLocaleString()}` : '—'}</td>
                          <td className="px-4 py-3 text-right">{e?.tasks ? `${e.tasks.completed}/${e.tasks.total}` : '—'}</td>
                          <td className="px-4 py-3 text-right">{one(e?.rescued_kg)}</td>
                          <td className="px-5 py-3 text-right">{one(e?.disposal_kg)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
