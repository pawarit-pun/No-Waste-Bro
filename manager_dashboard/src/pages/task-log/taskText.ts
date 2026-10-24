import { formatQuantity, actionLabels } from '../../lib/labels'
import { formatDay, formatTime } from '../../lib/format'
import type { TaskLogItem } from '../../types/taskLog'

/** "Markdown −20% · 10 pieces" */
export function taskHeadline(t: TaskLogItem): string {
  const label = actionLabels[t.action_type] ?? t.action_type
  const qty = formatQuantity(t.action_quantity, t.product?.unit_of_measure)
  if (t.action_type === 'MARKDOWN' && t.discount_pct != null) return `${label} −${Math.round(t.discount_pct)}% · ${qty}`
  return `${label} · ${qty}`
}

/** เวลาแบบสั้น: วันนี้ = "10:12" วันอื่น = "21 Oct 10:12" */
export function shortWhen(iso: string, todayIso: string): string {
  return iso.slice(0, 10) === todayIso ? formatTime(iso) : `${formatDay(iso)} ${formatTime(iso)}`
}

export const minutesText = (m: number | null) =>
  m == null ? null : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`

/** สิ่งที่เกิดล่าสุดของ task เช่น "Started 10:12" / "Done 11:05 · 8/10" */
export function lastUpdate(t: TaskLogItem, todayIso: string): string {
  const e = t.last_event
  if (!e) return '—'
  const at = shortWhen(e.created_at, todayIso)
  switch (e.event_type) {
    case 'STARTED': return `Started ${at}`
    case 'COMPLETED': return `Done ${at}${e.quantity != null ? ` · ${e.quantity}/${t.action_quantity}` : ''}`
    case 'REJECTED': return `Rejected ${at}`
    case 'CREATED': return `Sent to staff ${at}`
    default: return `${e.to_status} ${at}`
  }
}
