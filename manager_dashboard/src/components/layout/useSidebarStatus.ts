import { useCallback, useEffect, useState } from 'react'
import { supabase, useTableChanges } from '../../lib/supabase'

export interface PipelineStatus {
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'
  current_step: string | null
  requested_at: string
  finished_at: string | null
}

/** จำนวน plan ที่รออนุมัติ (badge) + สถานะรอบ pipeline ล่าสุด อ่านจาก Supabase ตรงๆ (anon อ่านได้) และอัปเดตแบบ realtime */
export function useSidebarStatus() {
  const [waiting, setWaiting] = useState<number | null>(null)
  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null)

  const loadWaiting = useCallback(async () => {
    if (!supabase) return
    const { count, error } = await supabase
      .from('pending_tasks')
      .select('review_id', { count: 'exact', head: true })
      .eq('review_status', 'WAITING')
    if (!error) setWaiting(count ?? 0)
  }, [])

  const loadPipeline = useCallback(async () => {
    if (!supabase) return
    const { data, error } = await supabase
      .from('pipeline_runs')
      .select('status, current_step, requested_at, finished_at')
      .order('requested_at', { ascending: false })
      .limit(1)
    if (!error) setPipeline((data?.[0] as PipelineStatus | undefined) ?? null)
  }, [])

  useEffect(() => {
    void loadWaiting()
    void loadPipeline()
  }, [loadWaiting, loadPipeline])

  useTableChanges('pending_tasks', loadWaiting)
  useTableChanges('pipeline_runs', loadPipeline)

  return { waiting, pipeline }
}
