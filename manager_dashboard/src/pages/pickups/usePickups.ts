import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet, errorMessage } from '../../lib/api'
import { useTableChanges } from '../../lib/supabase'
import type { PickupSchedule } from '../../types/pickups'

/** GET /pickup-schedule (วันนี้ + 6 วัน) โหลดใหม่เมื่อ task / plan เปลี่ยน และทุก 60 วินาที (สถานะรอบตามเวลา) */
export function usePickups(daysAhead = 6) {
  const [data, setData] = useState<PickupSchedule | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const latest = useRef(0)

  const load = useCallback(async () => {
    const ticket = ++latest.current
    setRefreshing(true)
    try {
      const res = await apiGet<PickupSchedule>(`/pickup-schedule?days_ahead=${daysAhead}`)
      if (ticket !== latest.current) return
      setData(res)
      setError(null)
    } catch (err) {
      if (ticket === latest.current) setError(errorMessage(err, 'Could not load the pickup schedule.'))
    } finally {
      if (ticket === latest.current) setRefreshing(false)
    }
  }, [daysAhead])

  useEffect(() => {
    void load()
    const t = setInterval(() => void load(), 60_000)
    return () => clearInterval(t)
  }, [load])

  useTableChanges('ai_recommended_tasks', load)
  useTableChanges('pending_tasks', load)

  return { data, error, refreshing, reload: load }
}
