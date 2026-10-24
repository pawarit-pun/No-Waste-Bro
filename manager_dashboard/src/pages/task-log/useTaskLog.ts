import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet, errorMessage } from '../../lib/api'
import { bkkMidnightIso } from '../../lib/format'
import { useTableChanges } from '../../lib/supabase'
import type { TaskLogResponse } from '../../types/taskLog'

export type TaskLogRange = 'today' | 'week'

/** เริ่มช่วงเวลา: เที่ยงคืนวันนี้ หรือ 6 วันก่อนหน้า (รวมวันนี้ = 7 วัน) ตามเวลาไทย */
function rangeStart(range: TaskLogRange): string {
  const today = bkkMidnightIso()
  if (range === 'today') return today
  const d = new Date(new Date(today).getTime() - 6 * 86_400_000)
  return d.toISOString()
}

/** GET /task-log (ทุกสถานะ กรองในหน้า) โหลดใหม่เมื่อ task / task_events เปลี่ยน และทุก 60 วินาที (นับเวลาเลยกำหนด) */
export function useTaskLog(range: TaskLogRange) {
  const [data, setData] = useState<TaskLogResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const latest = useRef(0)

  const load = useCallback(async () => {
    const ticket = ++latest.current
    try {
      const res = await apiGet<TaskLogResponse>(`/task-log?${new URLSearchParams({ created_from: rangeStart(range) })}`)
      if (ticket !== latest.current) return
      setData(res)
      setError(null)
    } catch (err) {
      if (ticket === latest.current) setError(errorMessage(err, 'Could not load the task log.'))
    } finally {
      if (ticket === latest.current) setLoading(false)
    }
  }, [range])

  useEffect(() => {
    setLoading(true)
    void load()
    const t = setInterval(() => void load(), 60_000)
    return () => clearInterval(t)
  }, [load])

  useTableChanges('ai_recommended_tasks', load)
  useTableChanges('task_events', load)

  return { data, error, loading, reload: load }
}
