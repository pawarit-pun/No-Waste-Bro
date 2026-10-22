import { useCallback, useEffect, useState } from 'react'
import { supabase, useTableChanges } from '../../lib/supabase'
import type { ReviewCounts } from '../../types/review'

/** จำนวน plan ของรอบสแกนนี้ใน pending_tasks แยกตามสถานะ (anon อ่านได้) อัปเดตแบบ realtime */
export function useRunReviewCounts(runId: string | null) {
  const [counts, setCounts] = useState<ReviewCounts | null>(null)

  const load = useCallback(async () => {
    if (!supabase || !runId) {
      setCounts(null)
      return
    }
    const { data, error } = await supabase.from('pending_tasks').select('review_status').eq('run_id', runId)
    if (error) return
    const next: ReviewCounts = { waiting: 0, approved: 0, rejected: 0 }
    for (const row of (data ?? []) as { review_status: string }[]) {
      if (row.review_status === 'WAITING') next.waiting += 1
      else if (row.review_status === 'APPROVED') next.approved += 1
      else if (row.review_status === 'REJECTED') next.rejected += 1
    }
    setCounts(next)
  }, [runId])

  useEffect(() => {
    void load()
  }, [load])

  useTableChanges('pending_tasks', load)

  return counts
}
