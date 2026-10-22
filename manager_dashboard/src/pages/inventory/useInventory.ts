import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet, errorMessage } from '../../lib/api'
import { useTableChanges } from '../../lib/supabase'
import type { InventoryResponse } from '../../types/inventory'

/**
 * lot ปัจจุบันจาก GET /inventory-lots
 * inventory_lots ไม่ได้อยู่ใน Realtime จึงใช้ event ของตารางที่เกี่ยวข้องเป็นสัญญาณให้ดึงใหม่
 * (agent สแกน/วางแผน, ผู้จัดการอนุมัติ, staff ทำงานเสร็จ)
 */
export function useInventory(includeEmpty: boolean) {
  const [data, setData] = useState<InventoryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const latest = useRef(0)

  const load = useCallback(async () => {
    const ticket = ++latest.current
    setRefreshing(true)
    try {
      const res = await apiGet<InventoryResponse>(`/inventory-lots?include_empty=${includeEmpty}`)
      if (ticket !== latest.current) return
      setData(res)
      setError(null)
    } catch (err) {
      if (ticket === latest.current) setError(errorMessage(err, 'Could not load inventory.'))
    } finally {
      if (ticket === latest.current) setRefreshing(false)
    }
  }, [includeEmpty])

  useEffect(() => {
    void load()
  }, [load])

  useTableChanges('pipeline_runs', load)
  useTableChanges('pending_tasks', load)
  useTableChanges('ai_recommended_tasks', load)

  return { data, error, refreshing, reload: load }
}
