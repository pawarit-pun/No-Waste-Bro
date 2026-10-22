import type { ActionType, RiskLevel } from './review'

export type RunStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'
export type StepName = 'SCAN' | 'OPTIMIZE' | 'TASKS'

/** สรุปของแต่ละขั้นที่ worker เขียนลง pipeline_runs.steps */
export interface StepInfo {
  status?: 'RUNNING' | 'OK' | 'FAILED' | string
  started_at?: string
  seconds?: number
  exit_code?: number
  summary?: ScanSummary & OptimizeSummary & TasksSummary
}

export interface ScanSummary {
  lots?: number
  at_risk_lots?: number
  levels?: Partial<Record<RiskLevel, number>>
}

export interface OptimizeSummary {
  decisions_created?: number
  actions?: Partial<Record<ActionType, number>>
}

export interface TasksSummary {
  decisions?: number
  llm_ok?: number
  template_fallback?: number
  plans_queued?: number
  tasks_created?: number
  failed_batches?: number
}

/** GET /ai/pipeline-runs (1 แถว = AI รัน 1 รอบ) */
export interface PipelineRun {
  pipeline_run_id: string
  status: RunStatus
  current_step: StepName | null
  stop_after: StepName
  run_id: string | null
  at_risk_lots: number | null
  decisions_created: number | null
  tasks_created: number | null
  failed_batches: number | null
  message: string | null
  error: string | null
  steps: Partial<Record<StepName, StepInfo>>
  requested_at: string
  started_at: string | null
  finished_at: string | null
}
