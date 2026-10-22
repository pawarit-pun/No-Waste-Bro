import type { RiskLevel } from './review'
import type { ProductCategory } from './staff'

export type LotAIStatus = 'IDLE' | 'PROCESSING' | 'CHECKED'
export type LotOrigin = 'SUPPLIER' | 'MARKDOWN_SPLIT' | 'KITCHEN_OUTPUT' | 'TASK_OUTPUT'

export interface InventoryLot {
  lot_id: string
  product_id: string
  received_date: string
  expiration_date: string
  initial_quantity: number
  current_quantity: number
  unit_cost: number | null
  location_aisle: string | null
  location_shelf: string | null
  ai_status: LotAIStatus
  current_selling_price: number
  source_task_id: string | null
  product: {
    product_id: string
    name: string
    category: ProductCategory
    unit_of_measure: string
    regular_price: number
    image_url: string | null
  } | null
  days_left: number
  origin: LotOrigin
  latest_assessment: { risk_level: RiskLevel; risk_score: number; days_to_expiry: number; assessed_at: string } | null
  waiting_plans: number
  open_tasks: number
}

/** GET /inventory-lots */
export interface InventoryResponse {
  reference_date: string
  items: InventoryLot[]
}
