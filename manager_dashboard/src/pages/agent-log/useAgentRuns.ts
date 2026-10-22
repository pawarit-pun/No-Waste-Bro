import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet, errorMessage } from '../../lib/api'
import { useTableChanges } from '../../lib/supabase'
import type { PipelineRun } from '../../types/pipeline'

/** รอบ AI ล่าสุด 50 รอบ (ใหม่สุดก่อน) ดึงใหม่เมื่อ pipeline_runs เปลี่ยน (Realtime) */
export function useAgentRuns(limit = 50) {
  const [runs, setRuns] = useState<PipelineRun[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const latest = useRef(0)

  const load = useCallback(async () => {
    const ticket = ++latest.current
    try {
      const res = await apiGet<PipelineRun[]>(`/ai/pipeline-runs?limit=${limit}`)
      if (ticket !== latest.current) return
      setRuns(res)
      setError(null)
    } catch (err) {
      if (ticket === latest.current) setError(errorMessage(err, 'Could not load agent runs.'))
    }
  }, [limit])

  useEffect(() => {
    void load()
  }, [load])

  useTableChanges('pipeline_runs', load)

  return { runs, error, reload: load }
}
