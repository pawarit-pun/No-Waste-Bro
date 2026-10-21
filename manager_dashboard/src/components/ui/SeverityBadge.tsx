import type { Severity } from '../../types/review'

const STYLES: Record<Severity, { cls: string; mark: string }> = {
  EXPIRED: { cls: 'bg-slate-800 text-white', mark: '✕' },
  CRITICAL: { cls: 'bg-red-50 text-red-700 ring-1 ring-red-200', mark: '●' },
  HIGH: { cls: 'bg-orange-50 text-orange-700 ring-1 ring-orange-200', mark: '▲' },
  MEDIUM: { cls: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200', mark: '◆' },
  LOW: { cls: 'bg-slate-100 text-slate-600 ring-1 ring-slate-200', mark: '○' },
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = STYLES[severity]
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-bold tracking-wide ${s.cls}`}>
      <span className="text-[8px]" aria-hidden="true">{s.mark}</span>
      {severity}
    </span>
  )
}
