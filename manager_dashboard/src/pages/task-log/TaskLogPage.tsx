import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/EmptyState'
import { ResetIcon } from '../../components/ui/icons'
import { Select } from '../../components/ui/Select'
import { ACTION_ORDER, actionLabels } from '../../lib/labels'
import type { ActionType } from '../../types/review'
import type { TaskLogCounts, TaskLogItem, TaskStatus } from '../../types/taskLog'
import { TaskLogDrawer } from './TaskLogDrawer'
import { TaskLogTable, type TaskSort, type TaskSortColumn } from './TaskLogTable'
import { useTaskLog, type TaskLogRange } from './useTaskLog'

type StatusFilter = 'ALL' | 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'REJECTED' | 'OVERDUE'
const CHIPS: { id: StatusFilter; label: string; count: (c: TaskLogCounts) => number; tone: string }[] = [
  { id: 'ALL', label: 'All', count: (c) => c.total, tone: 'text-slate-900' },
  { id: 'PENDING', label: 'Pending', count: (c) => c.pending, tone: 'text-slate-700' },
  { id: 'IN_PROGRESS', label: 'In progress', count: (c) => c.in_progress, tone: 'text-brand' },
  { id: 'COMPLETED', label: 'Completed', count: (c) => c.completed, tone: 'text-emerald-700' },
  { id: 'REJECTED', label: 'Rejected', count: (c) => c.rejected, tone: 'text-red-700' },
  { id: 'OVERDUE', label: 'Overdue', count: (c) => c.overdue, tone: 'text-red-600' },
]
// ยังไม่จบอยู่บน จบแล้วอยู่ล่าง
const STATUS_RANK: Record<TaskStatus, number> = { PENDING: 0, IN_PROGRESS: 1, COMPLETED: 2, REJECTED: 3 }
const dueMs = (t: TaskLogItem) => (t.due_by ? new Date(t.due_by).getTime() : null)

/** เรียงตามคอลัมน์ที่เลือก งานที่ไม่มี due_by อยู่ท้ายเสมอ สถานะเดียวกันเรียงตาม due ใกล้ก่อน */
function sortTasks(items: TaskLogItem[], sort: TaskSort): TaskLogItem[] {
  const sign = sort.dir === 'asc' ? 1 : -1
  const byDue = (a: TaskLogItem, b: TaskLogItem, s: number) => {
    const x = dueMs(a), y = dueMs(b)
    if (x === y) return 0
    if (x === null) return 1
    if (y === null) return -1
    return (x - y) * s
  }
  return [...items].sort((a, b) =>
    sort.column === 'status'
      ? (STATUS_RANK[a.task_status] - STATUS_RANK[b.task_status]) * sign || byDue(a, b, 1)
      : byDue(a, b, sign) || STATUS_RANK[a.task_status] - STATUS_RANK[b.task_status])
}

const isStatus = (v: string | null): v is StatusFilter => !!v && CHIPS.some((c) => c.id === v)

export function TaskLogPage() {
  const [params, setParams] = useSearchParams()
  const status: StatusFilter = isStatus(params.get('status')) ? (params.get('status') as StatusFilter) : 'ALL'
  const [range, setRange] = useState<TaskLogRange>('today')
  const [action, setAction] = useState<ActionType | 'ALL'>('ALL')
  const [staff, setStaff] = useState<string>('ALL')
  const [sort, setSort] = useState<TaskSort>({ column: 'status', dir: 'asc' })
  const cycleSort = (column: TaskSortColumn) =>
    setSort((s) => (s.column === column && s.dir === 'asc' ? { column, dir: 'desc' } : { column, dir: 'asc' }))
  const [openId, setOpenId] = useState<string | null>(params.get('task'))
  const { data, error, loading, reload } = useTaskLog(range)

  const staffOptions = useMemo(() => {
    const m = new Map<string, string>()
    for (const t of data?.items ?? []) if (t.assigned_staff) m.set(t.assigned_staff.staff_id, t.assigned_staff.full_name)
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]))
  }, [data])

  const items = useMemo(() => (data?.items ?? []).filter((t) =>
    (status === 'ALL' || (status === 'OVERDUE' ? t.is_overdue : t.task_status === status)) &&
    (action === 'ALL' || t.action_type === action) &&
    (staff === 'ALL' || t.assigned_staff_id === staff)), [data, status, action, staff])
  const sorted = useMemo(() => sortTasks(items, sort), [items, sort])

  const open = data?.items.find((t) => t.task_id === openId) ?? null
  const setStatus = (id: StatusFilter) => setParams(id === 'ALL' ? {} : { status: id })

  return (
    <div className="px-8 py-7">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">Task log</h1>
          <p className="mt-1 text-[15px] text-slate-600">
            Every approved task and where it is now: sent to staff, started, done or rejected. Updates live from the staff app.
          </p>
        </div>
        <Button size="sm" onClick={() => void reload()}>
          <ResetIcon className="size-4" /> Refresh
        </Button>
      </div>

      <div className="mt-6 grid grid-cols-3 gap-3 lg:grid-cols-6">
        {CHIPS.map((c) => (
          <button key={c.id} type="button" onClick={() => setStatus(c.id)}
            className={`rounded-xl border bg-white px-4 py-3 text-left transition-colors ${status === c.id ? 'border-brand ring-1 ring-brand' : 'border-slate-200 hover:border-brand/40'}`}>
            <p className="text-[12px] text-slate-500">{c.label}</p>
            <p className={`font-mono text-2xl font-semibold ${c.tone}`}>{data ? c.count(data.counts) : '—'}</p>
          </button>
        ))}
      </div>

      <section className="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 px-5 py-3.5">
          <Select label="Created" value={range} onChange={(e) => setRange(e.target.value as TaskLogRange)}>
            <option value="today">Today</option>
            <option value="week">Last 7 days</option>
          </Select>
          <Select label="Action" value={action} onChange={(e) => setAction(e.target.value as ActionType | 'ALL')}>
            <option value="ALL">All actions</option>
            {ACTION_ORDER.map((a) => <option key={a} value={a}>{actionLabels[a]}</option>)}
          </Select>
          <Select label="Staff" value={staff} onChange={(e) => setStaff(e.target.value)}>
            <option value="ALL">Everyone</option>
            {staffOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </Select>
          <p className="ml-auto text-[12px] text-slate-500">Open tasks from earlier days are always included</p>
        </div>

        {loading && !data ? (
          <div className="space-y-3 border-t border-slate-200 px-5 py-6">
            {[0, 1, 2].map((i) => <div key={i} className="h-12 animate-pulse rounded-lg bg-slate-100" />)}
          </div>
        ) : error && !data ? (
          <div className="border-t border-slate-200">
            <EmptyState title="Could not load the task log">
              <p>{error}</p>
              <Button className="mt-3" size="sm" onClick={() => void reload()}>Try again</Button>
            </EmptyState>
          </div>
        ) : items.length === 0 ? (
          <div className="border-t border-slate-200">
            <EmptyState title="No tasks here">
              Tasks appear after a plan is approved in the Review queue (by you or by AI auto-approve).
            </EmptyState>
          </div>
        ) : (
          <TaskLogTable items={sorted} referenceDate={data?.reference_date ?? ''} sort={sort} onSort={cycleSort} onOpen={(t) => setOpenId(t.task_id)} />
        )}
      </section>

      <TaskLogDrawer task={open} referenceDate={data?.reference_date ?? ''} eventsAvailable={data?.events_available ?? true}
        onClose={() => setOpenId(null)} />
    </div>
  )
}
