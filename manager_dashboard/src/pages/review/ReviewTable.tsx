import { Button } from '../../components/ui/Button'
import { SeverityBadge } from '../../components/ui/SeverityBadge'
import { bkkDate, formatDay, formatImpact, formatTime } from '../../lib/format'
import { actionDetail, actionHeadline } from '../../lib/labels'
import type { ReviewStatus } from '../../types/review'
import { deadlineState, type ReviewGroup, type SortColumn, type SortState } from './groups'

const TH = 'px-4 py-3 text-left text-[13px] font-semibold text-slate-600 whitespace-nowrap'
const TD = 'px-4 py-4 align-top'

/** "Today 22:00" ถ้าเป็นวันเดียวกับวันของระบบ (reference_date) ไม่งั้น "17 Oct 08:45" */
function formatDeadline(iso: string, referenceDate: string) {
  return `${bkkDate(new Date(iso)) === referenceDate ? 'Today' : formatDay(iso)} ${formatTime(iso)}`
}

/** หัวคอลัมน์ที่กดเรียงได้ (▲ น้อยไปมาก / ▼ มากไปน้อย) ลูกศรแสดงเฉพาะคอลัมน์ที่กำลังใช้เรียง */
function SortableTh({ label, column, sort, onSort, align = 'left' }: {
  label: string
  column: SortColumn
  sort: SortState | null
  onSort: (column: SortColumn) => void
  align?: 'left' | 'right'
}) {
  const active = sort?.column === column
  return (
    <th className={`${TH} ${align === 'right' ? 'text-right' : ''}`}
      aria-sort={active ? (sort?.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" onClick={() => onSort(column)}
        className={`inline-flex items-center gap-1 hover:text-slate-900 ${active ? 'text-slate-900' : ''}`}>
        {label}
        {active && (
          <span className="text-[10px] text-slate-900" aria-hidden="true">{sort?.dir === 'asc' ? '▲' : '▼'}</span>
        )}
      </button>
    </th>
  )
}

function ImpactCell({ value }: { value: number }) {
  return (
    <span className={`font-mono text-[15px] font-semibold ${value < 0 ? 'text-red-600' : 'text-slate-900'}`}>
      {formatImpact(value)}
    </span>
  )
}

function LotCell({ group }: { group: ReviewGroup }) {
  return (
    <div className="min-w-44 max-w-60">
      <p className="font-mono text-sm font-bold text-slate-900">{group.lotId}</p>
      <p className="truncate text-sm text-slate-600" title={group.productName}>{group.productName}</p>
    </div>
  )
}

function ActionsCell({ group }: { group: ReviewGroup }) {
  return (
    <div className="min-w-44 space-y-1">
      {group.items.map((item) => (
        <div key={item.review_id} className="leading-tight">
          <p className="text-sm font-medium text-slate-900">
            {item.decision ? actionHeadline(item.decision, item.product?.unit_of_measure) : '—'}
          </p>
          {actionDetail(item) && <p className="truncate text-xs text-slate-500">{actionDetail(item)}</p>}
        </div>
      ))}
    </div>
  )
}

export function ReviewTable({ tab, groups, referenceDate, now, selected, sort, onSort, onToggle, onToggleAll, onReview }: {
  tab: ReviewStatus
  sort: SortState | null
  onSort: (column: SortColumn) => void
  groups: ReviewGroup[]
  referenceDate: string
  now: Date
  selected: Set<string>
  onToggle: (key: string) => void
  onToggleAll: () => void
  onReview: (group: ReviewGroup) => void
}) {
  const waiting = tab === 'WAITING'
  const allSelected = groups.length > 0 && groups.every((g) => selected.has(g.key))

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead className="border-y border-slate-200 bg-slate-50">
          <tr>
            {waiting && (
              <th className="w-10 py-3 pl-5">
                <input type="checkbox" aria-label="Select all" checked={allSelected} onChange={onToggleAll}
                  className="size-4 cursor-pointer accent-[#e8622c]" />
              </th>
            )}
            <th className={TH}>{waiting ? 'Received' : 'Reviewed'}</th>
            <SortableTh label="Severity" column="severity" sort={sort} onSort={onSort} />
            <th className={TH}>Lot · Product</th>
            <th className={TH}>Proposed action</th>
            <SortableTh label="Exp. impact" column="impact" sort={sort} onSort={onSort} align="right" />
            {waiting ? <SortableTh label="Deadline" column="deadline" sort={sort} onSort={onSort} /> : <th className={TH}>By</th>}
            {waiting ? <th className="w-28" /> : <th className={TH}>{tab === 'REJECTED' ? 'Reason' : 'Note'}</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {groups.map((g) => {
            const first = g.items[0]
            const state = deadlineState(g.deadline, now)
            return (
              <tr key={g.key} className={`transition-colors hover:bg-orange-50/40 ${selected.has(g.key) ? 'bg-orange-50/60' : ''}`}>
                {waiting && (
                  <td className="py-4 pl-5 align-top">
                    <input type="checkbox" aria-label={`Select ${g.lotId}`} checked={selected.has(g.key)}
                      onChange={() => onToggle(g.key)} className="mt-1 size-4 cursor-pointer accent-[#e8622c]" />
                  </td>
                )}
                <td className={`${TD} font-mono text-sm text-slate-600`}>
                  {formatTime(waiting ? g.receivedAt : (g.reviewedAt ?? g.receivedAt))}
                </td>
                <td className={TD}><SeverityBadge severity={g.severity} /></td>
                <td className={TD}><LotCell group={g} /></td>
                <td className={TD}><ActionsCell group={g} /></td>
                <td className={`${TD} text-right`}><ImpactCell value={g.impact} /></td>
                {waiting ? (
                  <td className={`${TD} font-mono text-sm whitespace-nowrap ${state === 'overdue' || state === 'soon' ? 'font-semibold text-red-600' : 'text-slate-700'}`}>
                    {g.deadline ? formatDeadline(g.deadline, referenceDate) : '—'}
                    {state === 'overdue' && <span className="block font-sans text-[11px] font-semibold">Past due</span>}
                  </td>
                ) : (
                  <td className={`${TD} text-sm text-slate-700`}>{first.reviewer?.full_name ?? first.reviewed_by ?? '—'}</td>
                )}
                {waiting ? (
                  <td className="py-4 pr-5 text-right align-top">
                    <Button size="sm" variant="neutral" onClick={() => onReview(g)}>Review</Button>
                  </td>
                ) : (
                  <td className={`${TD} max-w-72 text-sm text-slate-600`}>
                    <p className="line-clamp-2">{first.review_note ?? (tab === 'APPROVED' ? `${g.items.length} task(s) sent to staff` : '—')}</p>
                    <button type="button" onClick={() => onReview(g)} className="mt-0.5 text-xs font-semibold text-brand hover:underline">
                      View details
                    </button>
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
