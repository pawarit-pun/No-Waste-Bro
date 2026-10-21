import { SEVERITY_ORDER } from '../../lib/labels'
import type { ReviewItem, ReviewStatus, Severity } from '../../types/review'

/** plan ทุกตัวของ lot เดียวกัน (assessment เดียวกัน) ในสถานะเดียวกัน = 1 แถวในตาราง */
export interface ReviewGroup {
  key: string
  status: ReviewStatus
  items: ReviewItem[]
  lotId: string
  productName: string
  severity: Severity
  receivedAt: string
  reviewedAt: string | null
  deadline: string | null
  impact: number
}

export const severityOf = (item: ReviewItem): Severity =>
  item.lot_expired ? 'EXPIRED' : (item.assessment?.risk_level ?? 'LOW')

export function groupReviews(items: ReviewItem[]): ReviewGroup[] {
  const map = new Map<string, ReviewItem[]>()
  for (const item of items) {
    const key = `${item.assessment_id}:${item.review_status}`
    map.set(key, [...(map.get(key) ?? []), item])
  }
  return [...map.entries()].map(([key, group]) => {
    const first = group[0]
    const deadlines = group.map((g) => g.review_deadline).filter((d): d is string => !!d).sort()
    const reviewed = group.map((g) => g.reviewed_at).filter((d): d is string => !!d).sort()
    return {
      key,
      status: first.review_status,
      items: group,
      lotId: first.lot_id,
      productName: first.product?.name ?? first.lot_id,
      severity: group.map(severityOf).sort((a, b) => SEVERITY_ORDER.indexOf(a) - SEVERITY_ORDER.indexOf(b))[0],
      receivedAt: group.map((g) => g.created_at).sort()[0],
      reviewedAt: reviewed.at(-1) ?? null,
      deadline: deadlines[0] ?? null,
      impact: group.reduce((sum, g) => sum + (g.decision?.expected_profit_impact ?? 0), 0),
    }
  })
}

export type SortKey = 'oldest' | 'deadline' | 'severity'

export function sortGroups(groups: ReviewGroup[], sort: SortKey): ReviewGroup[] {
  const byTime = (a: string | null, b: string | null) => (a ?? '9999').localeCompare(b ?? '9999')
  return [...groups].sort((a, b) => {
    if (sort === 'deadline') return byTime(a.deadline, b.deadline) || byTime(a.receivedAt, b.receivedAt)
    if (sort === 'severity')
      return SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity) || byTime(a.receivedAt, b.receivedAt)
    return byTime(a.receivedAt, b.receivedAt) || a.lotId.localeCompare(b.lotId)
  })
}

/** สถานะ deadline เทียบกับ "ตอนนี้" ของระบบ (วัน demo + เวลาจริง) */
export function deadlineState(deadline: string | null, now: Date): 'overdue' | 'soon' | 'ok' | 'none' {
  if (!deadline) return 'none'
  const diff = new Date(deadline).getTime() - now.getTime()
  if (diff < 0) return 'overdue'
  if (diff < 2 * 60 * 60 * 1000) return 'soon'
  return 'ok'
}
