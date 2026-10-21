import type { ProductCategory } from './staff'

export type ReviewStatus = 'WAITING' | 'APPROVED' | 'REJECTED'
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type ActionType =
  | 'MARKDOWN'
  | 'KITCHEN_REPURPOSE'
  | 'DONATE'
  | 'ANIMAL_FEED'
  | 'COMPOST'
  | 'ANAEROBIC_DIGESTION'
  | 'LANDFILL'
  | 'DISCARD'

export interface InstructionStep {
  title: string
  detail: string
}

/** ทางเลือกอื่นของ Optimizer: แบบมีตัวเลข หรือแบบถูกตัดพร้อมเหตุผล */
export interface Alternative {
  action_type?: ActionType
  discount_pct?: number
  new_recommended_price?: number
  partner_id?: string
  disposal_method?: string
  expected_profit_impact?: number
  note?: string
  option?: string
  rejected_because?: string[]
}

export interface PendingDecision {
  action_type: ActionType
  action_quantity: number
  discount_pct: number | null
  new_recommended_price: number | null
  target_recipe_id: string | null
  batch_count: number | null
  target_partner_id: string | null
  due_by: string | null
  expected_profit_impact: number | null
  decision_score?: number | null
  alternatives?: Alternative[] | null
  optimizer_version?: string | null
}

export interface ReviewLot {
  lot_id: string
  current_quantity: number
  expiration_date: string
  location_aisle: string | null
  location_shelf: string | null
}

export interface ReviewProduct {
  product_id: string
  name: string
  category: ProductCategory
  unit_of_measure: string
  image_url: string | null
}

export interface ReviewAssessment {
  assessment_id: string
  days_to_expiry: number
  quantity_at_assessment: number
  predicted_leftover_units: number
  risk_score: number
  risk_level: RiskLevel
}

export interface ReviewItem {
  review_id: string
  decision_id: string
  run_id: string
  assessment_id: string
  lot_id: string
  priority: number
  ai_reasoning: string | null
  staff_instructions: string | null
  instruction_steps: InstructionStep[] | null
  model_used: string | null
  review_status: ReviewStatus
  review_deadline: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
  task_id: string | null
  created_at: string
  decision: PendingDecision | null
  lot: ReviewLot | null
  lot_expired: boolean
  product: ReviewProduct | null
  assessment: ReviewAssessment | null
  recipe: { recipe_id: string; name: string; department_name?: string | null } | null
  partner: { partner_id: string; name: string; partner_type: string } | null
  reviewer: { staff_id: string; full_name: string; image_url: string | null } | null
}

export interface ReviewCounts {
  waiting: number
  approved: number
  rejected: number
}

/** GET /pending-tasks */
export interface ReviewListResponse {
  reference_date: string
  counts: ReviewCounts
  items: ReviewItem[]
}

export type Severity = RiskLevel | 'EXPIRED'
