// GET /kitchen-overview (server/services/kitchen_overview.py)

export type WorkloadStatus = 'AVAILABLE' | 'BUSY' | 'FULL'

export interface KitchenDay {
  department_id: string
  capacity_date: string
  available_hrs: number
  booked_hrs: number
  remaining_hrs: number | null
  workload_status: WorkloadStatus | null
}

export interface KitchenDepartment {
  department_id: string
  department_name: string | null
  daily_processing_capacity_hrs: number | null
  days: KitchenDay[]
}

export type KitchenJobStatus = 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'REJECTED' | 'WAITING'

export interface KitchenJob {
  kind: 'TASK' | 'WAITING_APPROVAL'
  id: string
  status: KitchenJobStatus
  department_id: string | null
  department_name: string | null
  date: string | null
  hours: number | null
  due_by: string | null
  recipe_id: string | null
  recipe_name: string | null
  batch_count: number | null
  expected_output: number | null
  output_name: string | null
  output_unit: string | null
  lot_id: string | null
  ingredient_name: string | null
  ingredient_quantity: number | null
  ingredient_unit: string | null
  location: string | null
  priority: number | null
  staff: { staff_id: string; full_name: string; image_url: string | null } | null
  completed_at: string | null
  actual_quantity_handled: number | null
  rejection_reason: string | null
  review_deadline: string | null
}

export interface MenuDemand {
  recipe_id: string
  recipe_name: string | null
  department_id: string | null
  department_name: string | null
  output_name: string | null
  output_unit: string | null
  window_from: string
  window_to: string
  gross_demand: number
  current_stock: number
  menu_qty: number
  low_qty: number
  high_qty: number
  expected_revenue: number
  batch_output: number | null
  prep_time_mins: number | null
}

export interface KitchenOverview {
  reference_date: string
  departments: KitchenDepartment[]
  jobs: KitchenJob[]
  menu_demand: MenuDemand[]
  menu_demand_run: { run_id: string; reference_date: string; created_at: string } | null
}
