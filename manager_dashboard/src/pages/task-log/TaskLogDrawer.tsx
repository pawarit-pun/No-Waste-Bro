import type { ReactNode } from 'react'
import { Drawer } from '../../components/ui/Drawer'
import { MapPinIcon } from '../../components/ui/icons'
import { TaskStatusBadge } from '../../components/ui/TaskStatusBadge'
import { bkkDate, formatDay, formatImpact } from '../../lib/format'
import type { TaskEvent, TaskLogItem } from '../../types/taskLog'
import { AiBadge } from '../review/ReviewTable'
import { minutesText, shortWhen, taskHeadline } from './taskText'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mt-5">
      <p className="mb-1.5 text-[11px] font-bold tracking-[0.08em] text-slate-400 uppercase">{title}</p>
      {children}
    </div>
  )
}

interface Step { key: string; label: string; at: string | null; detail?: ReactNode; tone: 'done' | 'bad' | 'todo' }

/** timeline: อนุมัติ → ส่งให้พนักงาน → เริ่ม → เสร็จ / ปฏิเสธ (ขั้นที่ยังไม่ถึงแสดงเป็นสีเทา) */
function steps(t: TaskLogItem): Step[] {
  const ev = (type: TaskEvent['event_type']) => t.events.find((e) => e.event_type === type)
  const created = ev('CREATED')
  const started = ev('STARTED')
  const done = ev('COMPLETED')
  const rejected = ev('REJECTED')
  const staff = t.assigned_staff?.full_name ?? 'nobody (no staff covers this category)'
  const out: Step[] = []
  if (t.review) {
    out.push({
      key: 'approved', tone: 'done', at: t.review.reviewed_at,
      label: t.review.approved_by_agent ? `Approved by AI (rules of ${t.review.reviewer?.full_name ?? '—'})` : `Approved by ${t.review.reviewer?.full_name ?? '—'}`,
      detail: t.review.review_note,
    })
  }
  out.push({ key: 'sent', tone: 'done', at: created?.created_at ?? t.created_at, label: `Sent to ${staff}` })
  if (rejected) {
    out.push({ key: 'rejected', tone: 'bad', at: rejected.created_at, label: 'Rejected by staff',
      detail: rejected.note ?? t.rejection_reason })
    return out
  }
  out.push({ key: 'started', tone: started || t.task_status !== 'PENDING' ? 'done' : 'todo', at: started?.created_at ?? null,
    label: started ? 'Started' : t.task_status === 'PENDING' ? 'Not started yet' : 'Started (time not recorded)',
    detail: t.wait_minutes != null ? `${minutesText(t.wait_minutes)} after it was sent` : undefined })
  out.push({ key: 'done', tone: done || t.task_status === 'COMPLETED' ? 'done' : 'todo',
    at: done?.created_at ?? t.completed_at, label: done || t.task_status === 'COMPLETED' ? 'Completed' : 'Not completed yet',
    detail: (done || t.task_status === 'COMPLETED') ? (
      <>
        Handled <b className="font-mono">{done?.quantity ?? t.actual_quantity_handled ?? '—'}</b> of {t.action_quantity}
        {t.work_minutes != null && <> · took {minutesText(t.work_minutes)}</>}
      </>
    ) : undefined })
  return out
}

const DOT = { done: 'bg-emerald-500 ring-emerald-100', bad: 'bg-red-500 ring-red-100', todo: 'bg-white ring-slate-200' } as const

export function TaskLogDrawer({ task, referenceDate, eventsAvailable, onClose }: {
  task: TaskLogItem | null
  referenceDate: string
  eventsAvailable: boolean
  onClose: () => void
}) {
  if (!task) return null
  const t = task
  const today = bkkDate()
  const lot = t.lot
  return (
    <Drawer
      open
      onClose={onClose}
      title={
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-lg font-bold text-slate-900">{t.lot_id}</span>
            <TaskStatusBadge status={t.task_status} />
            {t.review?.approved_by_agent && <AiBadge />}
          </div>
          <p className="text-[15px] text-slate-700">{t.product?.name ?? t.product_id}</p>
          <p className="mt-1 font-semibold text-slate-900">{taskHeadline(t)}</p>
        </div>
      }
      subtitle={
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-slate-500">
          {lot && (
            <span className="inline-flex items-center gap-1">
              <MapPinIcon className="size-3.5" />{[lot.location_aisle, lot.location_shelf].filter(Boolean).join(' / ') || '—'}
            </span>
          )}
          {lot && <span>Expires {formatDay(`${lot.expiration_date}T12:00:00+07:00`)}</span>}
          {t.due_by && <span className={t.is_overdue ? 'font-semibold text-red-600' : ''}>Due {shortWhen(t.due_by, referenceDate)}{t.is_overdue && t.minutes_late != null ? ` · ${t.minutes_late} min late` : ''}</span>}
          <span>Priority P{t.priority}</span>
        </div>
      }
    >
      <Section title="Timeline">
        <ol className="relative ml-1.5 border-l border-slate-200">
          {steps(t).map((s) => (
            <li key={s.key} className="relative pb-4 pl-5 last:pb-0">
              <span className={`absolute top-1 -left-[7px] size-3 rounded-full ring-4 ${DOT[s.tone]} ${s.tone === 'todo' ? 'border border-slate-300' : ''}`} />
              <p className={`flex flex-wrap items-baseline justify-between gap-2 text-sm ${s.tone === 'todo' ? 'text-slate-400' : 'font-semibold text-slate-900'}`}>
                {s.label}
                {s.at && <span className="font-mono text-xs font-normal text-slate-500">{shortWhen(s.at, today)}</span>}
              </p>
              {s.detail && <p className={`mt-0.5 text-[13px] ${s.tone === 'bad' ? 'text-red-700' : 'text-slate-600'}`}>{s.detail}</p>}
            </li>
          ))}
        </ol>
        {!eventsAvailable && (
          <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
            Start and reject times are not recorded yet. Run <span className="font-mono">server/scripts/task_events.sql</span> to log every status change.
          </p>
        )}
      </Section>

      {t.expected_profit_impact != null && (
        <Section title="Expected impact">
          <p className={`font-mono font-semibold ${t.expected_profit_impact < 0 ? 'text-red-600' : 'text-slate-900'}`}>
            {formatImpact(t.expected_profit_impact)}
            <span className="ml-2 font-sans text-xs font-normal text-slate-500">optimizer estimate</span>
          </p>
        </Section>
      )}

      <Section title="What staff see">
        {t.staff_instructions && <p className="text-sm font-medium text-slate-800">{t.staff_instructions}</p>}
        {t.instruction_steps?.length ? (
          <ol className="mt-2 space-y-1.5">
            {t.instruction_steps.map((s, i) => (
              <li key={i} className="flex gap-2.5 text-sm">
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-orange-50 text-[11px] font-bold text-brand">{i + 1}</span>
                <span><span className="font-semibold text-slate-800">{s.title}</span> <span className="text-slate-600">{s.detail}</span></span>
              </li>
            ))}
          </ol>
        ) : !t.staff_instructions ? <p className="text-sm text-slate-500">—</p> : null}
      </Section>

      {t.ai_reasoning && (
        <Section title="Why the AI chose this">
          <p className="text-sm leading-relaxed text-slate-700">{t.ai_reasoning}</p>
        </Section>
      )}
    </Drawer>
  )
}
