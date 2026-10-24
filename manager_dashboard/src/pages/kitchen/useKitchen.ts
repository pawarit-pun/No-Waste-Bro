import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet, errorMessage } from '../../lib/api'
import { useTableChanges } from '../../lib/supabase'
import type { KitchenOverview } from '../../types/kitchen'

/**
 * ข้อมูลหน้า Kitchen จาก GET /kitchen-overview
 * ตารางครัวไม่ได้อยู่ใน Realtime จึงใช้ event ของ task / plan / pipeline เป็นสัญญาณให้ดึงใหม่ + โหลดใหม่ทุก 60 วินาที
 */
export function useKitchen(daysAhead = 1) {
  const [data, setData] = useState<KitchenOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const latest = useRef(0)

  const load = useCallback(async () => {
    const ticket = ++latest.current
    setRefreshing(true)
    try {
      const res = await apiGet<KitchenOverview>(`/kitchen-overview?days_ahead=${daysAhead}`)
      if (ticket !== latest.current) return
      setData(res)
      setError(null)
    } catch (err) {
      if (ticket === latest.current) setError(errorMessage(err, 'Could not load the kitchens.'))
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
  useTableChanges('pipeline_runs', load)

  return { data, error, refreshing, reload: load }
}
