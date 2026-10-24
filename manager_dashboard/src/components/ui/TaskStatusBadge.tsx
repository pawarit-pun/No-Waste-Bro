import type { TaskStatus } from '../../types/taskLog'

const STYLES: Record<TaskStatus, { cls: string; dot: string; label: string }> = {
  PENDING: { cls: 'bg-slate-50 text-slate-700 ring-slate-200', dot: 'bg-slate-400', label: 'Pending' },
  IN_PROGRESS: { cls: 'bg-orange-50 text-brand ring-orange-200', dot: 'bg-brand animate-pulse', label: 'In progress' },
  COMPLETED: { cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200', dot: 'bg-emerald-500', label: 'Completed' },
  REJECTED: { cls: 'bg-red-50 text-red-700 ring-red-200', dot: 'bg-red-500', label: 'Rejected' },
}

/** ป้ายสถานะ task (+ Overdue ถ้ายังไม่จบและเลยกำหนด) */
export function TaskStatusBadge({ status, overdue = false }: { status: TaskStatus; overdue?: boolean }) {
  const s = STYLES[status] ?? STYLES.PENDING
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${s.cls}`}>
        <span className={`size-1.5 rounded-full ${s.dot}`} />
        {s.label}
      </span>
      {overdue && (
        <span className="rounded-md bg-red-600 px-1.5 py-0.5 text-[11px] font-bold text-white">Overdue</span>
      )}
    </span>
  )
}
