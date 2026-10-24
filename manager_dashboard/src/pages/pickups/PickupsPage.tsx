import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/EmptyState'
import { ResetIcon } from '../../components/ui/icons'
import { formatLongDate } from '../../lib/format'
import { PickupDrawer } from './PickupDrawer'
import { PickupGrid } from './PickupGrid'
import { usePickups } from './usePickups'

export function PickupsPage() {
  const { data, error, refreshing, reload } = usePickups(6)
  const [openId, setOpenId] = useState<string | null>(null)

  const slot = data?.slots.find((s) => s.slot_id === openId) ?? null
  const partner = slot ? data?.partners.find((p) => p.partner_id === slot.partner_id) ?? null : null

  return (
    <div className="px-8 py-7">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">Pickups</h1>
          <p className="mt-1 text-[15px] text-slate-600">
            When each partner comes to collect donations, feed, compost, biogas and landfill, and what has to be ready
            {data && <> · {formatLongDate(data.reference_date)}</>}
          </p>
        </div>
        <Button size="sm" onClick={() => void reload()} disabled={refreshing}>
          <ResetIcon className={`size-4 ${refreshing ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {error && !data ? (
        <section className="mt-6 rounded-2xl border border-slate-200 bg-white">
          <EmptyState title="Could not load the pickup schedule">
            <p>{error}</p>
            <Button className="mt-3" size="sm" onClick={() => void reload()}>Try again</Button>
          </EmptyState>
        </section>
      ) : !data ? (
        <div className="mt-6 h-96 animate-pulse rounded-2xl bg-slate-100" />
      ) : (
        <>
          <section className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white">
            <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3.5">
              <h2 className="font-semibold text-slate-900">Next 7 days</h2>
              <p className="flex items-center gap-3 text-[12px] text-slate-500">
                <span className="inline-flex items-center gap-1"><span className="inline-block h-1.5 w-4 rounded-full bg-slate-500" />Approved</span>
                <span className="inline-flex items-center gap-1"><span className="inline-block h-1.5 w-4 rounded-full bg-amber-300" />Waiting approval</span>
                <span className="inline-flex items-center gap-1"><span className="inline-block size-3 rounded bg-slate-50 ring-1 ring-slate-200" />Partner does not come</span>
              </p>
            </div>
            <PickupGrid data={data} onOpen={setOpenId} />
            <p className="border-t border-slate-200 px-5 py-3 text-[12px] text-slate-500">
              Items appear once the pipeline plans them for that day. Later pickups the optimizer only pencils in are not stored, so most future days show the partner’s schedule only.
            </p>
          </section>
        </>
      )}

      <PickupDrawer slot={slot} partner={partner} onClose={() => setOpenId(null)} />
    </div>
  )
}
