import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet, errorMessage } from '../../lib/api'
import { useTableChanges } from '../../lib/supabase'
import type { DailyReportList } from '../../types/daily'
import type { InventoryResponse } from '../../types/inventory'
import type { KitchenOverview } from '../../types/kitchen'
import type { PipelineRun } from '../../types/pipeline'
import type { ReviewListResponse } from '../../types/review'

/** task แบบย่อจาก GET /tasks (ใช้นับงานค้าง / เลยกำหนด) */
export interface TaskLite {
  task_id: string
  task_status: string
  due_by: string | null
}

export interface OverviewData {
  reports: DailyReportList
  inventory: InventoryResponse
  reviews: ReviewListResponse
  tasks: TaskLite[]
  kitchen: KitchenOverview | null
  lastRun: PipelineRun | null
}

/** หน้า Overview: รายงานประจำวันของ agent + ตัวเลขสดของร้าน โหลดใหม่เมื่อตารางที่เกี่ยวข้องเปลี่ยน และทุก 60 วินาที */
export function useOverview() {
  const [data, setData] = useState<OverviewData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const latest = useRef(0)

  const load = useCallback(async () => {
    const ticket = ++latest.current
    setRefreshing(true)
    try {
      const [reports, inventory, reviews, tasks, kitchen, runs] = await Promise.all([
        apiGet<DailyReportList>('/daily-reports?days=7'),
        apiGet<InventoryResponse>('/inventory-lots'),
        apiGet<ReviewListResponse>('/pending-tasks'),
        apiGet<TaskLite[]>('/tasks'),
        apiGet<KitchenOverview>('/kitchen-overview?days_ahead=0').catch(() => null),
        apiGet<PipelineRun[]>('/ai/pipeline-runs?limit=1'),
      ])
      if (ticket !== latest.current) return
      setData({ reports, inventory, reviews, tasks, kitchen, lastRun: runs[0] ?? null })
      setError(null)
    } catch (err) {
      if (ticket === latest.current) setError(errorMessage(err, 'Could not load the overview.'))
    } finally {
      if (ticket === latest.current) setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const t = setInterval(() => void load(), 60_000)
    return () => clearInterval(t)
  }, [load])

  useTableChanges('daily_reports', load)
  useTableChanges('pipeline_runs', load)
  useTableChanges('pending_tasks', load)
  useTableChanges('ai_recommended_tasks', load)

  return { data, error, refreshing, reload: load }
}
