// POST /agent/ask (server/schemas/agent.py)

export type AgentPage = 'overview' | 'inventory' | 'risk-monitor' | 'review' | 'run-demo' | 'pipeline-runs'

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
