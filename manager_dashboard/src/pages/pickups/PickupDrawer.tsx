import { Link } from 'react-router-dom'
import { Drawer } from '../../components/ui/Drawer'
import { TaskStatusBadge } from '../../components/ui/TaskStatusBadge'
import { formatThb, formatTime } from '../../lib/format'
import { actionLabels, formatQuantity } from '../../lib/labels'
import type { ActionType } from '../../types/review'
import type { TaskStatus } from '../../types/taskLog'
import type { PickupPartner, PickupSlot } from '../../types/pickups'
import { ALERT_TEXT, dayLabel, hhmm, kgText } from './pickupText'

export function PickupDrawer({ slot, partner, onClose }: { slot: PickupSlot | null; partner: PickupPartner | null; onClose: () => void }) {
  if (!slot || !partner) return null
  const total = slot.kg_confirmed + slot.kg_waiting
  return (
    <Drawer
      open
      onClose={onClose}
      title={
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-bold text-slate-900">{partner.name}</span>
          </div>
          <p className="text-[15px] text-slate-700">
            {dayLabel(slot.date)} · {hhmm(partner.pickup_time_start)}–{hhmm(partner.pickup_time_end)}
            {slot.state === 'OPEN' && <span className="ml-2 font-semibold text-brand">Pickup window is open</span>}
            {slot.state === 'PAST' && <span className="ml-2 text-slate-500">Window has passed</span>}
            {!slot.on_schedule && <span className="ml-2 font-semibold text-red-600">Not a regular pickup day</span>}
          </p>
        </div>
      }
      subtitle={
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-slate-500">
          {partner.contact_name && <span>{partner.contact_name}</span>}
          {partner.contact_phone && <a href={`tel:${partner.contact_phone}`} className="font-semibold text-brand hover:underline">{partner.contact_phone}</a>}
          <span>Takes {partner.accepted_categories.join(', ').toLowerCase()}</span>
        </div>
      }
    >
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="rounded-lg bg-slate-50 py-2.5">
          <p className="font-mono text-lg font-semibold text-slate-900">{kgText(total)}</p>
          <p className="text-[11px] text-slate-500">of {slot.capacity_kg ?? '—'} kg capacity</p>
        </div>
        <div className="rounded-lg bg-slate-50 py-2.5">
          <p className="font-mono text-lg font-semibold text-slate-900">{slot.tasks_done}/{slot.tasks_total}</p>
          <p className="text-[11px] text-slate-500">tasks done</p>
        </div>
        <div className="rounded-lg bg-slate-50 py-2.5">
          <p className="font-mono text-lg font-semibold text-slate-900">{slot.costs ? formatThb(slot.costs.net_cost_thb) : '—'}</p>
          <p className="text-[11px] text-slate-500">estimated cost</p>
        </div>
      </div>

      {slot.alerts.length > 0 && (
        <ul className="mt-3 space-y-1">
          {slot.alerts.map((a) => (
            <li key={a} className={`rounded-lg px-3 py-2 text-[13px] ${a === 'WAITING_APPROVAL' ? 'bg-amber-50 text-amber-800' : 'bg-red-50 text-red-800'}`}>
              <b>{ALERT_TEXT[a]}</b>{' — '}
              {a === 'OVER_CAPACITY' && `${kgText(total)} is more than one trip can take (${slot.capacity_kg} kg).`}
              {a === 'BELOW_MIN' && `Less than the ${slot.min_kg} kg minimum per trip.`}
              {a === 'NOT_READY' && 'The pickup window has started but some tasks are not done yet.'}
              {a === 'WAITING_APPROVAL' && <>Some items are still plans. <Link to="/review-queue" className="font-semibold underline">Review queue</Link></>}
            </li>
          ))}
        </ul>
      )}

      <p className="mt-5 mb-1.5 text-[11px] font-bold tracking-[0.08em] text-slate-400 uppercase">Items for this pickup</p>
      {slot.items.length === 0 ? (
        <p className="text-sm text-slate-500">Nothing is planned for this pickup. No need to call the partner.</p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200">
          {slot.items.map((it) => (
            <li key={it.task_id ?? it.review_id} className="flex items-start justify-between gap-3 px-3.5 py-2.5">
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-900">
                  <span className="font-mono">{it.lot_id}</span> · {it.product_name ?? '—'}
                </p>
                <p className="text-[12px] text-slate-500">
                  {actionLabels[it.action_type as ActionType] ?? it.action_type} · {formatQuantity(it.quantity, it.unit_of_measure)} · {kgText(it.kg)}
                  {it.location && <> · {it.location}</>} · ready by {formatTime(it.due_by)}
                </p>
                {it.staff_name && <p className="text-[12px] text-slate-500">{it.staff_name}</p>}
              </div>
              <div className="shrink-0 text-right">
                {it.source === 'TASK' ? (
                  <>
                    <TaskStatusBadge status={it.status as TaskStatus} />
                    <Link to={`/task-log?task=${it.task_id}`} className="mt-1 block text-[12px] font-semibold text-brand hover:underline">Task log</Link>
                  </>
                ) : (
                  <span className="rounded-md bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-800 ring-1 ring-amber-200">Waiting approval</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {slot.costs && (
        <p className="mt-3 text-[12px] text-slate-500">
          Trip {formatThb(slot.costs.trip_cost_thb)} + handling {formatThb(slot.costs.handling_thb)}
          {slot.costs.buyback_thb > 0 && <> − buyback {formatThb(slot.costs.buyback_thb)}</>} (estimate, same formula as the optimizer).
          {' '}Quantities for leftovers are expected units; staff hand over what is really left.
        </p>
      )}
    </Drawer>
  )
}
