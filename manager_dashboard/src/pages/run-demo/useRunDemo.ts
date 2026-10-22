import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiGet, apiPost } from '../../lib/api'
import { secondsBetween } from '../../lib/format'
import type { PipelineRun, StepName } from '../../types/pipeline'
import { useAgentRuns } from '../agent-log/useAgentRuns'

interface ScanInputs {
  reference_date: string
  inventory_lots: unknown[]
}

export interface DemoResetResponse {
  demo_date: string
  reset: { tasks_deleted: number; decisions_deleted: number; assessments_deleted: number; lots_restored: number }
  idle_lots: number
}

export interface Readiness {
  referenceDate: string
  idleLots: number
}

/** สั่งรัน AI pipeline, ติดตามรอบล่าสุดแบบ realtime, จำนวน lot ที่พร้อมสแกน และ reset ข้อมูล demo */
export function useRunDemo() {
  const { runs, error: runsError, reload } = useAgentRuns(20)
  const [readiness, setReadiness] = useState<Readiness | null>(null)

  // lot ที่ยัง IDLE (scan-inputs อ่านอย่างเดียว history_days=0 = ไม่ส่งยอดขายย้อนหลัง)
  const loadReadiness = useCallback(async () => {
    try {
      const res = await apiGet<ScanInputs>('/ai/scan-inputs?history_days=0')
      setReadiness({ referenceDate: res.reference_date, idleLots: res.inventory_lots.length })
    } catch {
      setReadiness(null)
    }
  }, [])

  const latest = runs?.[0] ?? null
  const active = runs?.find((r) => r.status === 'QUEUED' || r.status === 'RUNNING') ?? null

  // โหลดใหม่ตอนเปิดหน้า และทุกครั้งที่รอบล่าสุดเปลี่ยนสถานะ (สแกนเสร็จ lot จะไม่ IDLE แล้ว)
  useEffect(() => {
    void loadReadiness()
  }, [latest?.pipeline_run_id, latest?.status, loadReadiness])

  /** เวลาเฉลี่ยของรอบที่สำเร็จครบ 3 ขั้น (5 รอบล่าสุด) */
  const avgSeconds = useMemo(() => {
    const done = (runs ?? []).filter((r) => r.status === 'SUCCEEDED' && r.steps.TASKS?.status === 'OK' && r.started_at && r.finished_at)
      .slice(0, 5)
    if (!done.length) return null
    return done.reduce((sum, r) => sum + secondsBetween(r.started_at as string, r.finished_at), 0) / done.length
  }, [runs])

  /** stopAfter: SCAN = สแกนอย่างเดียว, OPTIMIZE = สแกน + decision, TASKS = ครบ 3 ขั้น (ค่าเริ่มต้น) */
  const start = useCallback(async (stopAfter: StepName = 'TASKS') => {
    const run = await apiPost<PipelineRun>('/ai/pipeline-runs', { stop_after: stopAfter })
    await reload()
    return run
  }, [reload])

  const reset = useCallback(async () => {
    const res = await apiPost<DemoResetResponse>('/demo/reset', {})
    await Promise.all([reload(), loadReadiness()])
    return res
  }, [reload, loadReadiness])

  return { runs, runsError, latest, active, readiness, avgSeconds, start, reset }
}
