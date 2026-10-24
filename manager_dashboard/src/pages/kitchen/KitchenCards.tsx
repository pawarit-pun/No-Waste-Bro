import { ChefHatIcon } from '../../components/ui/icons'
import { formatDay } from '../../lib/format'
import type { KitchenDay, KitchenDepartment, KitchenJob, WorkloadStatus } from '../../types/kitchen'

const STATUS_STYLE: Record<WorkloadStatus, string> = {
  AVAILABLE: 'bg-emerald-50 text-emerald-700',
  BUSY: 'bg-amber-50 text-amber-700',
  FULL: 'bg-red-50 text-red-700',
}

const hrs = (n: number) => `${Math.round(n * 100) / 100}h`

/** แถบชั่วโมงครัว: จองแล้ว (สีเข้ม) + plan ที่รออนุมัติ (ลายทาง ยังไม่ได้จอง) / ความจุทั้งวัน */
function CapacityBar({ day, waitingHrs, small = false }: { day: KitchenDay; waitingHrs: number; small?: boolean }) {
  const cap = day.available_hrs || 1
  const booked = Math.min(day.booked_hrs / cap, 1) * 100
  const waiting = Math.min(waitingHrs / cap, Math.max(0, 1 - day.booked_hrs / cap)) * 100
  const over = day.booked_hrs + waitingHrs > day.available_hrs
  return (
    <div className={`flex w-full overflow-hidden rounded-full bg-slate-100 ${small ? 'h-1.5' : 'h-3'}`}
      role="img" aria-label={`${hrs(day.booked_hrs)} booked of ${hrs(day.available_hrs)}`}>
      <div className={`${day.booked_hrs >= cap ? 'bg-red-500' : 'bg-brand'}`} style={{ width: `${booked}%` }} />
      {waitingHrs > 0 && (
        <div className={over ? 'bg-red-300' : 'bg-brand/35'} style={{
          width: `${waiting}%`,
          backgroundImage: 'repeating-linear-gradient(45deg, transparent 0 4px, rgba(255,255,255,.55) 4px 8px)',
        }} />
      )}
    </div>
  )
}

export function KitchenCard({ dept, jobs, today }: { dept: KitchenDepartment; jobs: KitchenJob[]; today: string }) {
  const todayRow = dept.days.find((d) => d.capacity_date === today)
  const next = dept.days.filter((d) => d.capacity_date > today)
  const mine = jobs.filter((j) => j.department_id === dept.department_id)
  const waitingHrs = (date: string) =>
    mine.filter((j) => j.kind === 'WAITING_APPROVAL' && j.date === date).reduce((n, j) => n + (j.hours ?? 0), 0)
  const todayJobs = mine.filter((j) => j.date === today && j.kind === 'TASK' && j.status !== 'REJECTED')
  const count = (s: KitchenJob['status']) => todayJobs.filter((j) => j.status === s).length
  const waitingToday = mine.filter((j) => j.date === today && j.kind === 'WAITING_APPROVAL').length
  const name = dept.department_name ?? dept.department_id

  return (
    <section className="rounded-2xl border border-slate-200 bg-white px-5 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-xl bg-orange-50 text-brand">
            <ChefHatIcon className="size-5" />
          </span>
          <div>
            <p className="font-semibold text-slate-900">{name}</p>
            <p className="font-mono text-xs text-slate-500">{dept.department_id}</p>
          </div>
        </div>
        {todayRow?.workload_status && (
          <span className={`rounded-md px-2 py-0.5 text-xs font-semibold ${STATUS_STYLE[todayRow.workload_status]}`}>
            {todayRow.workload_status.charAt(0) + todayRow.workload_status.slice(1).toLowerCase()}
          </span>
        )}
      </div>

      {todayRow ? (
        <div className="mt-4">
          <div className="mb-1.5 flex items-baseline justify-between text-sm">
            <span className="font-semibold text-slate-700">Today</span>
            <span className="font-mono text-slate-600">
              <span className="font-semibold text-slate-900">{hrs(todayRow.booked_hrs)}</span> booked
              {' · '}{hrs(todayRow.remaining_hrs ?? todayRow.available_hrs - todayRow.booked_hrs)} free of {hrs(todayRow.available_hrs)}
            </span>
          </div>
          <CapacityBar day={todayRow} waitingHrs={waitingHrs(today)} />
          {waitingHrs(today) > 0 && (
            <p className={`mt-1 text-xs ${todayRow.booked_hrs + waitingHrs(today) > todayRow.available_hrs ? 'font-semibold text-red-600' : 'text-slate-500'}`}>
              +{hrs(waitingHrs(today))} more if the waiting plans are approved
              {todayRow.booked_hrs + waitingHrs(today) > todayRow.available_hrs && ' (more than the kitchen has left)'}
            </p>
          )}
        </div>
      ) : (
        <p className="mt-4 text-sm text-slate-500">No capacity row for today.</p>
      )}

      {next.map((d) => (
        <div key={d.capacity_date} className="mt-3">
          <div className="mb-1 flex justify-between text-xs text-slate-500">
            <span>{formatDay(`${d.capacity_date}T12:00:00+07:00`)}</span>
            <span className="font-mono">{hrs(d.booked_hrs)} / {hrs(d.available_hrs)}</span>
          </div>
          <CapacityBar day={d} waitingHrs={waitingHrs(d.capacity_date)} small />
        </div>
      ))}

      <div className="mt-4 grid grid-cols-4 gap-2 border-t border-slate-100 pt-3 text-center">
        {([['To do', count('PENDING')], ['Cooking', count('IN_PROGRESS')], ['Done', count('COMPLETED')],
           ['Waiting approval', waitingToday]] as const).map(([label, n]) => (
          <div key={label}>
            <p className="font-mono text-lg font-semibold text-slate-900">{n}</p>
            <p className="text-[11px] leading-tight text-slate-500">{label}</p>
          </div>
        ))}
      </div>
    </section>
  )
}
