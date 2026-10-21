export type StaffRole = 'MANAGER' | 'STAFF'

export type ProductCategory = 'DAIRY' | 'BAKERY' | 'MEAT' | 'SEAFOOD' | 'PRODUCE' | 'READY_TO_EAT'

/** พนักงาน 1 คน จาก GET /staff (ตรงกับ StaffRow ฝั่ง server) */
export interface Staff {
  staff_id: string
  full_name: string
  role: StaffRole
  responsible_categories: ProductCategory[]
  image_url: string | null
  is_active: boolean
}
