export type PartnerType = 'DONATION' | 'ANIMAL_FEED' | 'COMPOSTING' | 'ANAEROBIC_DIGESTION' | 'LANDFILL'
export type SlotState = 'UPCOMING' | 'OPEN' | 'PAST'
export type SlotAlert = 'OVER_CAPACITY' | 'BELOW_MIN' | 'NOT_READY' | 'WAITING_APPROVAL'

export interface PickupPartner {
  partner_id: string
  name: string
  partner_type: PartnerType
  accepted_categories: string[]
  pickup_days: number[]
  pickup_time_start: string | null
  pickup_time_end: string | null
  max_capacity_kg_per_pickup: number | null
  min_kg_per_pickup: number | null
  contact_name: string | null
  contact_phone: string | null
  min_days_before_expiry: number | null
}

export interface PickupItem {
  source: 'TASK' | 'PLAN'
  task_id: string | null
  review_id: string | null
  lot_id: string
  product_name: string | null
  unit_of_measure: string | null
  action_type: string
  quantity: number
  kg: number
  status: string
  staff_name: string | null
  due_by: string
  location: string | null
}

export interface PickupSlot {
  slot_id: string
  partner_id: string
  date: string
  window_start: string
  window_end: string
  state: SlotState
  on_schedule: boolean
  items: PickupItem[]
  kg_confirmed: number
  kg_waiting: number
  capacity_kg: number | null
  min_kg: number
  tasks_done: number
  tasks_total: number
  alerts: SlotAlert[]
  costs: { trip_cost_thb: number; handling_thb: number; buyback_thb: number; net_cost_thb: number } | null
}

/** GET /pickup-schedule */
export interface PickupSchedule {
  reference_date: string
  now: string
  days_ahead: number
  partners: PickupPartner[]
  slots: PickupSlot[]
}
