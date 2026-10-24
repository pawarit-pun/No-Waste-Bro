import { useMemo, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/EmptyState'
import { ResetIcon } from '../../components/ui/icons'
import { Tabs } from '../../components/ui/Tabs'
import { formatLongDate, formatWhen, systemNow } from '../../lib/format'
import { KitchenCard } from './KitchenCards'
import { KitchenJobsTable } from './KitchenJobsTable'
import { MenuDemandTable } from './MenuDemandTable'
import { useKitchen } from './useKitchen'

type DayTab = 'TODAY' | 'TOMORROW'

export function KitchenPage() {
  const { data, error, refreshing, reload } = useKitchen(1)
  const [dept, setDept] = useState<string>('ALL')
  const [day, setDay] = useState<DayTab>('TODAY')

  const today = data?.reference_date ?? ''
  const tomorrow = useMemo(() => {
    if (!today) return ''
    const d = new Date(`${today}T12:00:00+07:00`)
    d.setDate(d.getDate() + 1)
    return d.toISOString().slice(0, 10)
  }, [today])
  const now = today ? systemNow(today) : new Date()

  const jobs = useMemo(() => (data?.jobs ?? []).filter((j) =>
    (dept === 'ALL' || j.department_id === dept) && j.date === (day === 'TODAY' ? today : tomorrow)),
  [data, dept, day, today, tomorrow])

  const deptTabs = [{ id: 'ALL', label: 'All kitchens' },
    ...(data?.departments ?? []).map((d) => ({ id: d.department_id, label: d.department_name ?? d.department_id }))]
  const dayCount = (date: string) => (data?.jobs ?? []).filter((j) => j.date === date && (dept === 'ALL' || j.department_id === dept)).length

  return (
    <div className="px-8 py-7">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">Kitchen</h1>
          <p className="mt-1 text-[15px] text-slate-600">
            Kitchen hours, the repurposing jobs the AI planned, and the menu demand behind them
            {today && <> · {formatLongDate(today)}</>}
          </p>
        </div>
        <Button size="sm" onClick={() => void reload()} disabled={refreshing}>
          <ResetIcon className={`size-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {error && !data ? (
        <section className="mt-6 rounded-2xl border border-slate-200 bg-white">
          <EmptyState title="Could not load the kitchens">
            <p>{error}</p>
            <Button className="mt-3" size="sm" onClick={() => void reload()}>Try again</Button>
          </EmptyState>
        </section>
      ) : !data ? (
        <div className="mt-6 grid gap-5 lg:grid-cols-2">
          {[0, 1].map((i) => <div key={i} className="h-64 animate-pulse rounded-2xl bg-slate-100" />)}
        </div>
      ) : (
        <>
          <div className="mt-6 grid gap-5 lg:grid-cols-2">
            {data.departments.map((d) => <KitchenCard key={d.department_id} dept={d} jobs={data.jobs} today={today} />)}
          </div>

          <section className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white">
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4">
              <h2 className="font-semibold text-slate-900">Kitchen jobs</h2>
              <div className="flex rounded-lg border border-slate-200 p-0.5 text-sm">
                {(['TODAY', 'TOMORROW'] as const).map((t) => (
                  <button key={t} type="button" onClick={() => setDay(t)}
                    className={`rounded-md px-3 py-1 font-semibold ${day === t ? 'bg-brand text-white' : 'text-slate-600 hover:bg-slate-50'}`}>
                    {t === 'TODAY' ? 'Today' : 'Tomorrow'}
                    <span className={`ml-1 ${day === t ? 'text-white/80' : 'text-slate-400'}`}>{dayCount(t === 'TODAY' ? today : tomorrow)}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-2 px-5"><Tabs items={deptTabs} value={dept} onChange={setDept} /></div>
            {jobs.length === 0 ? (
              <EmptyState title="No kitchen jobs">
                Jobs appear here when the optimizer sends at-risk ingredients to a kitchen and the plan reaches the review queue.
              </EmptyState>
            ) : (
              <KitchenJobsTable jobs={jobs} now={now} />
            )}
            <p className="border-t border-slate-200 px-5 py-3 text-[13px] text-slate-500">
              Hours = prep time per batch × batches, the same rule used to book the kitchen. Plans waiting for approval are not booked yet;
              rejected jobs gave their hours back.
            </p>
          </section>

          <section className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white">
            <div className="px-5 pt-4 pb-3">
              <h2 className="font-semibold text-slate-900">Menu demand</h2>
              <p className="text-[13px] text-slate-500">
                Forecast from the latest scan{data.menu_demand_run && <> ({formatWhen(data.menu_demand_run.created_at)})</>}.
                The optimizer only cooks up to “Make more”, so ingredients are not turned into menus nobody will buy.
              </p>
            </div>
            {data.menu_demand.length === 0 ? (
              <EmptyState title="No forecast yet">Run the AI pipeline to forecast menu demand.</EmptyState>
            ) : (
              <MenuDemandTable rows={data.menu_demand} />
            )}
          </section>
        </>
      )}
    </div>
  )
}
