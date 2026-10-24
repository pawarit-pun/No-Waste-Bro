import { StaffAvatar } from '../../components/StaffAvatar'
import { formatDay, formatTime } from '../../lib/format'
import { formatQuantity } from '../../lib/labels'
import type { KitchenJob, KitchenJobStatus } from '../../types/kitchen'

const TH = 'px-4 py-3 text-left text-[13px] font-semibold text-slate-600 whitespace-nowrap'
const TD = 'px-4 py-3.5 align-top'

const STATUS: Record<KitchenJobStatus, { label: string; cls: string }> = {
  WAITING: { label: 'Waiting approval', cls: 'bg-slate-100 text-slate-600' },
  PENDING: { label: 'To do', cls: 'bg-orange-50 text-brand' },
  IN_PROGRESS: { label: 'Cooking', cls: 'bg-amber-50 text-amber-700' },
  COMPLETED: { label: 'Done', cls: 'bg-emerald-50 text-emerald-700' },
  REJECTED: { label: 'Rejected', cls: 'bg-red-50 text-red-700' },
}

function DueCell({ job, now }: { job: KitchenJob; now: Date }) {
  if (!job.due_by) return <span className="text-slate-400">—</span>
  const late = (job.status === 'PENDING' || job.status === 'IN_PROGRESS') && new Date(job.due_by) < now
  return (
    <div className={late ? 'text-red-600' : 'text-slate-800'}>
      <p className="font-mono text-sm font-semibold">{formatTime(job.due_by)}</p>
      <p className="text-xs text-slate-500">{late ? 'overdue' : formatDay(job.due_by)}</p>
    </div>
  )
}

export function KitchenJobsTable({ jobs, now }: { jobs: KitchenJob[]; now: Date }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead className="border-y border-slate-200 bg-slate-50">
          <tr>
            <th className={`${TH} pl-5`}>Due</th>
            <th className={TH}>Menu</th>
            <th className={TH}>Ingredient lot</th>
            <th className={TH}>Kitchen</th>
            <th className={`${TH} text-right`}>Batches · hours</th>
            <th className={TH}>Staff</th>
            <th className={`${TH} pr-5`}>Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {jobs.map((j) => {
            const muted = j.kind === 'WAITING_APPROVAL' || j.status === 'REJECTED'
            return (
              <tr key={`${j.kind}-${j.id}`} className={`transition-colors hover:bg-orange-50/40 ${muted ? 'bg-slate-50/60' : ''}`}>
                <td className={`${TD} pl-5`}><DueCell job={j} now={now} /></td>
                <td className={TD}>
                  <p className="text-sm font-medium text-slate-900">{j.recipe_name ?? j.recipe_id ?? '—'}</p>
                  {j.expected_output != null && (
                    <p className="text-xs text-slate-500">
                      ~{formatQuantity(j.expected_output, j.output_unit)}{j.output_name ? ` ${j.output_name}` : ''}
                    </p>
                  )}
                </td>
                <td className={TD}>
                  <p className="font-mono text-sm font-semibold text-slate-900">{j.lot_id ?? '—'}</p>
                  <p className="text-xs text-slate-500">
                    {j.ingredient_name}{j.ingredient_quantity != null ? ` · ${formatQuantity(j.ingredient_quantity, j.ingredient_unit)}` : ''}
                  </p>
                  {j.location && <p className="font-mono text-[11px] text-slate-400">{j.location}</p>}
                </td>
                <td className={`${TD} text-sm whitespace-nowrap text-slate-700`}>{j.department_name ?? j.department_id ?? '—'}</td>
                <td className={`${TD} text-right whitespace-nowrap`}>
                  <p className="font-mono text-sm font-semibold text-slate-900">{j.batch_count ?? '—'}</p>
                  <p className={`font-mono text-xs ${j.status === 'REJECTED' ? 'text-slate-400 line-through' : 'text-slate-500'}`}>
                    {j.hours != null ? `${j.hours}h` : '—'}
                  </p>
                </td>
                <td className={TD}>
                  {j.staff ? (
                    <div className="flex items-center gap-2">
                      <StaffAvatar name={j.staff.full_name} imageUrl={j.staff.image_url} size={26} />
                      <span className="text-sm text-slate-700">{j.staff.full_name}</span>
                    </div>
                  ) : (
                    <span className="text-sm text-slate-400">{j.kind === 'WAITING_APPROVAL' ? 'assigned on approval' : '—'}</span>
                  )}
                </td>
                <td className={`${TD} pr-5`}>
                  <span className={`inline-block rounded-md px-2 py-0.5 text-xs font-semibold whitespace-nowrap ${STATUS[j.status].cls}`}>
                    {STATUS[j.status].label}
                  </span>
                  {j.status === 'COMPLETED' && j.completed_at && (
                    <p className="mt-0.5 text-[11px] text-slate-500">at {formatTime(j.completed_at)}</p>
                  )}
                  {j.status === 'REJECTED' && j.rejection_reason && (
                    <p className="mt-0.5 max-w-48 text-[11px] text-red-600">“{j.rejection_reason}”</p>
                  )}
                  {j.kind === 'WAITING_APPROVAL' && j.review_deadline && (
                    <p className="mt-0.5 text-[11px] text-slate-500">approve by {formatTime(j.review_deadline)}</p>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
