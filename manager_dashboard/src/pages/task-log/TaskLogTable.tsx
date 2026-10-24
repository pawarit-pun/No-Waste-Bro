import { TaskStatusBadge } from '../../components/ui/TaskStatusBadge'
import { bkkDate, formatImpact } from '../../lib/format'
import { AiBadge, SortableTh } from '../review/ReviewTable'
import type { TaskLogItem } from '../../types/taskLog'
import { lastUpdate, shortWhen, taskHeadline } from './taskText'

const TH = 'px-4 py-3 text-left text-[13px] font-semibold text-slate-600 whitespace-nowrap'
const TD = 'px-4 py-3.5 align-top'

export type TaskSortColumn = 'status' | 'due'
export interface TaskSort { column: TaskSortColumn; dir: 'asc' | 'desc' }

export function TaskLogTable({ items, referenceDate, sort, onSort, onOpen }: {
  items: TaskLogItem[]
  referenceDate: string
  sort: TaskSort
  onSort: (column: TaskSortColumn) => void
  onOpen: (t: TaskLogItem) => void
}) {
  const today = bkkDate()
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead className="border-y border-slate-200 bg-slate-50">
          <tr>
            <th className={`${TH} pl-5`}>Lot · Product</th>
            <th className={TH}>Task</th>
            <th className={TH}>Staff</th>
            <th className={TH}>Approved by</th>
            <SortableTh<TaskSortColumn> label="Status" column="status" sort={sort} onSort={onSort} />
            <SortableTh<TaskSortColumn> label="Due" column="due" sort={sort} onSort={onSort} />
            <th className={`${TH} pr-5`}>Last update</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((t) => (
            <tr key={t.task_id} onClick={() => onOpen(t)}
              className={`cursor-pointer transition-colors hover:bg-orange-50/40 ${t.is_overdue ? 'bg-red-50/40' : ''}`}>
              <td className={`${TD} pl-5`}>
                <p className="font-mono text-sm font-bold text-slate-900">{t.lot_id}</p>
                <p className="max-w-56 truncate text-sm text-slate-600" title={t.product?.name}>{t.product?.name ?? t.product_id}</p>
              </td>
              <td className={TD}>
                <p className="text-sm font-medium text-slate-900">{taskHeadline(t)}</p>
                {t.expected_profit_impact != null && (
                  <p className={`font-mono text-xs ${t.expected_profit_impact < 0 ? 'text-red-600' : 'text-slate-500'}`}>
                    {formatImpact(t.expected_profit_impact)} expected
                  </p>
                )}
              </td>
              <td className={`${TD} text-sm text-slate-700`}>{t.assigned_staff?.full_name ?? <span className="text-slate-400">Unassigned</span>}</td>
              <td className={`${TD} text-sm text-slate-700`}>
                {t.review?.approved_by_agent ? (
                  <AiBadge />
                ) : (t.review?.reviewer?.full_name ?? '—')}
              </td>
              <td className={TD}><TaskStatusBadge status={t.task_status} /></td>
              <td className={`${TD} font-mono text-sm whitespace-nowrap ${t.is_overdue ? 'font-semibold text-red-600' : 'text-slate-700'}`}>
                {t.due_by ? shortWhen(t.due_by, referenceDate) : '—'}
                {t.is_overdue && t.minutes_late != null && <span className="block font-sans text-[11px]">{t.minutes_late} min late</span>}
              </td>
              <td className={`${TD} pr-5 text-sm whitespace-nowrap text-slate-600`}>{lastUpdate(t, today)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
