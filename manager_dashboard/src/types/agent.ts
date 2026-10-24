// POST /agent/ask (server/schemas/agent.py)

export type AgentPage = 'overview' | 'inventory' | 'kitchen' | 'review' | 'run-demo' | 'pipeline-runs'

export interface AgentContext {
  page?: AgentPage
  lot_id?: string
}

export interface AgentTurn {
  role: 'user' | 'assistant'
  text: string
}

export interface AgentToolCall {
  name: string
  args: unknown
  ms: number
  ok: boolean
}

export interface ExplainPortion {
  method: string
  units: number
  net_profit_thb: number
  discount_pct?: number
  unit_price?: number
  expected_sold?: number
  partner?: string
  pickup_at?: string
  when?: string
  provisional?: string
  recipe?: string
  batches?: number
  kitchen_due_by?: string
}

export interface PriceOption {
  discount_pct: number
  price: number
  expected_sold: number
  lot_net_profit_thb: number
  chosen: boolean
}

export interface WhatIfLotChange {
  lot_id: string
  name: string
  before: string
  after: string
  net_profit_before_thb: number
  net_profit_after_thb: number
  net_profit_change_thb: number
}

/** การ์ดข้อมูลที่ agent แนบมากับคำตอบ (ตัวเลขมาจาก tool ไม่ใช่จากโมเดล) */
export type AgentArtifact =
  | { type: 'snapshot'; lots_in_stock: number; lots_by_risk_level: Record<string, number>; plans_waiting_approval: number; open_tasks: number; overdue_tasks: number }
  | { type: 'lot_list'; lots: { lot_id: string; name: string | null; risk_level: string | null; days_left: number | null; quantity: number | null; unit: string | null }[] }
  | { type: 'lot'; lot_id: string }
  | { type: 'task_list'; tasks: { task_id: string; lot_id: string | null; name: string | null; action: string; quantity: number; status: string; staff: string; overdue: boolean }[] }
  | {
      type: 'lot_explain'
      lot_id: string
      name: string
      quantity: number
      risk_level: string
      plan: ExplainPortion[]
      lot_net_profit_thb: number
      price_options: PriceOption[]
      other_feasible_options: { action: string; discount_pct?: number | null; expected_profit_impact_thb: number; note?: string | null }[]
      excluded_options: { option: string; reasons: string[] }[]
      saved_decisions: { action: string; quantity: number; status: string | null }[]
    }
  | {
      type: 'what_if'
      scenario: string[]
      net_profit_before_thb: number
      net_profit_after_thb: number
      net_profit_change_thb: number
      unresolved_units_before: number
      unresolved_units_after: number
      units_by_method: { method: string; before: number; after: number; change: number }[]
      changed_lots_total: number
      changed_lots: WhatIfLotChange[]
      new_warnings: string[]
    }
  | { type: 'sources'; docs: string[] }
  /** ข้อเสนอจากแชท: server บันทึกแล้วแทนด้วยแถวจริง (proposal) ถ้าบันทึกไม่ได้จะเหลือแค่ title / kind */
  | { type: 'proposal'; proposal?: AgentProposal; kind?: ProposalKind; title?: string; reason?: string }

export interface AgentAnswer {
  answer: string
  model_used: string
  tool_calls: AgentToolCall[]
  artifacts: AgentArtifact[]
  warnings: string[]
  latency_ms: number
}

/** ข้อความในแผงแชท (เก็บใน sessionStorage) */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  at: string
  lotId?: string
  answer?: Omit<AgentAnswer, 'answer'>
  error?: boolean
}

// ---------- Phase 2: แจ้งเตือน + ข้อเสนอ ----------

export type ProposalKind = 'RUN_PIPELINE' | 'RELEASE_LOTS' | 'BLOCK_KITCHEN'
export type ProposalStatus = 'PROPOSED' | 'EXECUTED' | 'DISMISSED' | 'FAILED' | 'EXPIRED'

export interface AgentProposal {
  proposal_id: string
  kind: ProposalKind
  params: Record<string, unknown>
  title: string
  reason: string | null
  status: ProposalStatus
  source: 'CHAT' | 'EVENT' | 'SCHEDULE'
  expires_at: string | null
  decided_by: string | null
  decided_at: string | null
  result: Record<string, unknown> | null
  created_at: string
}

export type NotificationSeverity = 'INFO' | 'WARNING' | 'CRITICAL'

export interface AgentNotification {
  notification_id: string
  severity: NotificationSeverity
  title: string
  message: string
  event_type: string | null
  lot_id: string | null
  task_id: string | null
  read_at: string | null
  created_at: string
  proposal: AgentProposal | null
}

/** GET /agent/notifications */
export interface NotificationList {
  unread: number
  items: AgentNotification[]
}

// ---------- Phase 4: Auto-approve ----------

export type AutoAction = 'MARKDOWN' | 'DONATE' | 'ANIMAL_FEED' | 'COMPOST' | 'ANAEROBIC_DIGESTION'

export interface AutoApproveParams {
  actions: AutoAction[]
  max_discount_pct: number
  max_value_thb: number
  min_minutes_before_deadline: number
  daily_limit: number
  undo_minutes: number
}

/** GET / PUT /agent/policies/auto-approve */
export interface AutoApprovePolicy {
  policy_id: 'AUTO_APPROVE'
  enabled: boolean
  params: AutoApproveParams
  owner_staff_id: string | null
  owner: { staff_id: string; full_name: string; image_url?: string | null } | null
  updated_at: string | null
  allowed_actions: AutoAction[]
  today: { approved: number; lots: number; remaining: number }
}

/** POST /pending-tasks/{review_id}/undo-auto */
export interface UndoAutoResult {
  undone: number
  lot_id: string
  review_ids: string[]
  deleted_task_ids: string[]
  undone_by: string
}
