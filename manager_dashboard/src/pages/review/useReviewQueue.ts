import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet, apiPost, errorMessage } from '../../lib/api'
import { bkkMidnightIso } from '../../lib/format'
import { useTableChanges } from '../../lib/supabase'
import type { ReviewListResponse, ReviewStatus } from '../../types/review'

interface ApproveResponse { approved: number; tasks: { task_id: string }[] }
interface RejectResponse { rejected: number; lots_reset: string[] }

/** คิวรออนุมัติของแท็บที่เลือก: ดึงจาก GET /pending-tasks และดึงใหม่เมื่อ pending_tasks เปลี่ยน (Realtime) */
export function useReviewQueue(tab: ReviewStatus, managerId: string | undefined) {
  const [data, setData] = useState<ReviewListResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const latest = useRef(0)

  const load = useCallback(async () => {
    const ticket = ++latest.current
    try {
      const qs = new URLSearchParams({ status: tab, reviewed_from: bkkMidnightIso() })
      const res = await apiGet<ReviewListResponse>(`/pending-tasks?${qs}`)
      if (ticket !== latest.current) return // มีคำขอใหม่กว่าแล้ว
      setData(res)
      setError(null)
    } catch (err) {
      if (ticket !== latest.current) return
      setError(errorMessage(err, 'Could not load the review queue.'))
    } finally {
      if (ticket === latest.current) setLoading(false)
    }
  }, [tab])

  useEffect(() => {
    setLoading(true)
    setData(null)
    void load()
  }, [load])

  useTableChanges('pending_tasks', load)

  const approve = useCallback(async (reviewIds: string[], note?: string) => {
    if (!managerId) throw new Error('No manager selected.')
    const res = await apiPost<ApproveResponse>('/pending-tasks/approve', {
      review_ids: reviewIds, manager_id: managerId, ...(note ? { review_note: note } : {}),
    })
    await load()
    return res
  }, [managerId, load])

  const reject = useCallback(async (reviewIds: string[], note: string) => {
    if (!managerId) throw new Error('No manager selected.')
    const res = await apiPost<RejectResponse>('/pending-tasks/reject', {
      review_ids: reviewIds, manager_id: managerId, review_note: note,
    })
    await load()
    return res
  }, [managerId, load])

  return { data, error, loading, reload: load, approve, reject }
}
