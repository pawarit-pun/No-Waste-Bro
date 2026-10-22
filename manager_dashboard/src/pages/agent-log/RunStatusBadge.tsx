import type { RunStatus } from '../../types/pipeline'

const STYLES: Record<RunStatus, { cls: string; dot: string; label: string }> = {
  QUEUED: { cls: 'bg-amber-50 text-amber-700 ring-amber-200', dot: 'bg-amber-400', label: 'Queued' },
  RUNNING: { cls: 'bg-orange-50 text-brand ring-orange-200', dot: 'bg-brand animate-pulse', label: 'Running' },
  SUCCEEDED: { cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200', dot: 'bg-emerald-500', label: 'Succeeded' },
  FAILED: { cls: 'bg-red-50 text-red-700 ring-red-200', dot: 'bg-red-500', label: 'Failed' },
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const s = STYLES[status] ?? STYLES.QUEUED
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${s.cls}`}>
      <span className={`size-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  )
}
