// GET /daily-reports (metrics คำนวณใน AI/manager_agent/daily.py)

export interface MorningAction {
  action_type: string
  label: string | null
  decisions: number
  units: number
  kg: number
  expected_profit_thb: number
}

export interface EveningAction {
  action_type: string
  label: string | null
  tasks: number
  completed: number
  rejected: number
  open: number
  overdue: number
  units_planned: number
  units_handled: number
  kg_handled: number
  expected_profit_completed_thb: number
}

export interface MorningMetrics {
  pipeline_run_id?: string
  computed_at?: string
  at_risk?: Record<string, number>
  decisions?: number
  actions?: MorningAction[]
  rescued_kg?: number
  recycled_kg?: number
  planned_disposal_kg?: number
  disposal_kg_avg_prev?: number
  expected_net_profit_thb?: number
  plan_net_profit_thb?: number
  baseline_regular_then_landfill_thb?: number
  improvement_vs_baseline_thb?: number
  plans_waiting?: number
  plans_due_within_60min?: number
  /** Phase 4: plan ที่ AI อนุมัติเองวันนี้ (null = ปิด Auto-approve และวันนี้ยังไม่มี) */
  auto_approved?: { enabled: boolean; approved: number; lots: number; remaining: number } | null
  kitchen?: { department_id: string; name: string | null; available_hrs: number; booked_hrs: number; remaining_hrs: number; waiting_hrs: number }[]
}

export interface EveningMetrics {
  computed_at?: string
  tasks?: { total: number; completed: number; rejected: number; open: number; overdue: number }
  actions?: EveningAction[]
  rescued_kg?: number
  recycled_kg?: number
  disposal_kg?: number
  expected_profit_completed_thb?: number
  plans_waiting?: number
  morning_planned_units?: Record<string, number> | null
}

export interface Anomaly {
  code: string
  severity: 'INFO' | 'WARNING' | 'CRITICAL'
  text: string
  lot_ids?: string[]
}

export interface DailyReport {
  report_id: string
  report_date: string
  kind: 'MORNING' | 'EVENING'
  metrics: MorningMetrics & EveningMetrics
  anomalies: Anomaly[]
  message: string | null
  model_used: string | null
  created_at: string
  updated_at: string
}

export interface DailyReportList {
  reference_date: string
  items: DailyReport[]
}
