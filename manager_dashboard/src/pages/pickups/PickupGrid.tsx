import type { PickupPartner, PickupSchedule, PickupSlot } from '../../types/pickups'
import { DAY_SHORT, PARTNER_TONE, dayLabel, hhmm, isoWeekday, kgText } from './pickupText'

function SlotCell({ slot, partner, onOpen }: { slot: PickupSlot; partner: PickupPartner; onOpen: () => void }) {
  const total = slot.kg_confirmed + slot.kg_waiting
  const cap = slot.capacity_kg ?? Math.max(total, 1)
  const pct = (n: number) => `${Math.min(100, (n / cap) * 100)}%`
  const problem = slot.alerts.some((a) => a === 'OVER_CAPACITY' || a === 'NOT_READY')
  const empty = slot.items.length === 0
  return (
    <button type="button" onClick={onOpen}
      className={`h-full w-full rounded-lg border px-2.5 py-2 text-left transition-colors hover:border-brand
        ${problem ? 'border-red-300 bg-red-50/60' : slot.state === 'OPEN' ? 'border-brand/50 bg-orange-50/50' : 'border-slate-200 bg-white'}
        ${slot.state === 'PAST' ? 'opacity-60' : ''}`}>
      <p className="flex items-center justify-between gap-1 font-mono text-[11px] text-slate-500">
        {hhmm(partner.pickup_time_start)}–{hhmm(partner.pickup_time_end)}
        {slot.state === 'OPEN' && <span className="font-sans font-bold text-brand">Now</span>}
      </p>
      {empty ? (
        <p className="mt-1.5 text-[12px] text-slate-400">No load</p>
      ) : (
        <>
          <p className="mt-1 font-mono text-sm font-semibold text-slate-900">
            {kgText(total)}{slot.capacity_kg ? <span className="font-normal text-slate-400"> / {slot.capacity_kg}</span> : null}
          </p>
          <div className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-slate-100">
            <div className={PARTNER_TONE[partner.partner_type].bar} style={{ width: pct(slot.kg_confirmed) }} />
            <div className="bg-amber-300" style={{ width: pct(slot.kg_waiting) }} />
          </div>
          <p className="mt-1 text-[11px] text-slate-500">
            {slot.items.length} item{slot.items.length > 1 ? 's' : ''}
            {slot.tasks_total > 0 && <> · {slot.tasks_done}/{slot.tasks_total} ready</>}
          </p>
          {problem && <p className="text-[11px] font-semibold text-red-600">{slot.alerts.includes('OVER_CAPACITY') ? 'Over capacity' : 'Not ready'}</p>}
        </>
      )}
    </button>
  )
}

/** ตาราง partner × วัน: ช่องว่างสีเทา = วันที่ partner ไม่มารับ */
export function PickupGrid({ data, onOpen }: { data: PickupSchedule; onOpen: (slotId: string) => void }) {
  const days = Array.from({ length: data.days_ahead + 1 }, (_, i) => {
    const d = new Date(`${data.reference_date}T12:00:00+07:00`)
    d.setUTCDate(d.getUTCDate() + i)
    return d.toISOString().slice(0, 10)
  })
  const slotOf = new Map(data.slots.map((s) => [`${s.partner_id}@${s.date}`, s]))
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[960px] table-fixed border-collapse">
        <colgroup><col className="w-60" />{days.map((d) => <col key={d} />)}</colgroup>
        <thead className="border-y border-slate-200 bg-slate-50">
          <tr>
            <th className="px-5 py-3 text-left text-[13px] font-semibold text-slate-600">Partner</th>
            {days.map((d, i) => (
              <th key={d} className={`px-1.5 py-3 text-center text-[13px] font-semibold ${i === 0 ? 'text-brand' : 'text-slate-600'}`}>
                {i === 0 ? 'Today' : DAY_SHORT[isoWeekday(d) - 1]}
                <span className="block text-[11px] font-normal text-slate-400">{dayLabel(d)}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {data.partners.map((p) => (
            <tr key={p.partner_id}>
              <td className="px-5 py-3 align-top">
                <p className="text-sm font-semibold text-slate-900">{p.name}</p>
                <p className="mt-1 text-[12px] text-slate-500">
                  {p.pickup_days.map((n) => DAY_SHORT[n - 1]).join(' ')} · {hhmm(p.pickup_time_start)}–{hhmm(p.pickup_time_end)}
                </p>
                {p.contact_phone && <p className="text-[12px] text-slate-500">{p.contact_name} · {p.contact_phone}</p>}
              </td>
              {days.map((d, i) => {
                const s = slotOf.get(`${p.partner_id}@${d}`)
                return (
                  <td key={d} className={`h-28 px-1.5 py-2 align-top ${i === 0 ? 'bg-orange-50/30' : ''}`}>
                    {s ? <SlotCell slot={s} partner={p} onOpen={() => onOpen(s.slot_id)} />
                      : <div className="h-full rounded-lg bg-slate-50" aria-label="No pickup" />}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
