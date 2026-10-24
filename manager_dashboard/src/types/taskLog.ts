import type { ActionType } from './review'

export type TaskStatus = 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'REJECTED'
export type TaskEventType = 'CREATED' | 'STARTED' | 'COMPLETED' | 'REJECTED' | 'STATUS_CHANGED'

export interface TaskEvent {
  event_type: TaskEventType
  from_status: string | null
  to_status: string
  staff_id: string | null
  quantity: number | null
  note: string | null
  backfilled: boolean
  created_at: string
}

export interface StaffRef { staff_id: string; full_name: string; image_url: string | null }

export interface TaskLogItem {
  task_id: string
  lot_id: string
  product_id: string
  action_type: ActionType
  action_quantity: number
  discount_pct: number | null
  new_recommended_price: number | null
  original_price: number | null
  expected_profit_impact: number | null
  task_status: TaskStatus
  priority: number
  due_by: string | null
  created_at: string
  completed_at: string | null
  actual_quantity_handled: number | null
  rejection_reason: string | null
  staff_instructions: string | null
  instruction_steps: { title: string; detail: string }[] | null
  ai_reasoning: string | null
  assigned_staff_id: string | null
  assigned_staff: StaffRef | null
  product: { product_id: string; name: string; category: string; unit_of_measure: string; image_url: string | null } | null
  lot: { lot_id: string; current_quantity: number; expiration_date: string; location_aisle: string | null; location_shelf: string | null } | null
  recipe: { recipe_id: string; name: string } | null
  events: TaskEvent[]
  review: { review_id: string; reviewed_at: string | null; review_note: string | null; approved_by_agent: boolean; reviewer: StaffRef | null } | null
  is_overdue: boolean
  minutes_late: number | null
  started_at: string | null
  finished_at: string | null
  wait_minutes: number | null
  work_minutes: number | null
  last_event: TaskEvent | null
}

export interface TaskLogCounts {
  pending: number
  in_progress: number
  completed: number
  rejected: number
  overdue: number
  total: number
}

/** GET /task-log */
export interface TaskLogResponse {
  reference_date: string
  since: string
  events_available: boolean
  counts: TaskLogCounts
  items: TaskLogItem[]
}
