import type { ActionType, PendingDecision, ReviewItem, Severity } from '../types/review'
import type { ProductCategory, StaffRole } from '../types/staff'

/** ข้อความแสดงผล (ภาษาอังกฤษตามดีไซน์ ตรงกับ staff mobile app) */
export const categoryLabels: Record<ProductCategory, string> = {
  MEAT: 'Meat',
  SEAFOOD: 'Seafood',
  BAKERY: 'Bakery',
  DAIRY: 'Dairy',
  READY_TO_EAT: 'Deli',
  PRODUCE: 'Produce',
}

/** ["MEAT", "SEAFOOD"] → "Meat & Seafood" */
export const zoneLabel = (categories: ProductCategory[]) =>
  categories.map((c) => categoryLabels[c] ?? c).join(' & ')

export const roleLabel = (role: StaffRole) => (role === 'MANAGER' ? 'Manager' : 'Staff')

/** "Meat & Seafood · Staff" หรือ "Manager" ถ้าไม่มีหมวดที่ดูแล */
export const staffSubtitle = (categories: ProductCategory[], role: StaffRole) => {
  const zone = zoneLabel(categories)
  return zone ? `${zone} · ${roleLabel(role)}` : roleLabel(role)
}

/** ยังไม่มีข้อมูลสาขาใน DB จึงใส่ค่าตายตัว (เหมือน staff mobile app) */
export const STORE_LABEL = 'Store 014'

// ---------- Review queue ----------


export const actionLabels: Record<ActionType, string> = {
  MARKDOWN: 'Markdown',
  KITCHEN_REPURPOSE: 'Kitchen',
  DONATE: 'Donation',
  ANIMAL_FEED: 'Animal feed',
  COMPOST: 'Compost',
  ANAEROBIC_DIGESTION: 'Biogas',
  LANDFILL: 'Landfill',
  DISCARD: 'Discard',
}

export const ACTION_ORDER: ActionType[] = [
  'MARKDOWN', 'KITCHEN_REPURPOSE', 'DONATE', 'ANIMAL_FEED', 'COMPOST', 'ANAEROBIC_DIGESTION', 'LANDFILL', 'DISCARD',
]

export const SEVERITY_ORDER: Severity[] = ['EXPIRED', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']

/** ข้อความสั้นของ action เช่น "Markdown −20% · 13" */
export function actionHeadline(d: PendingDecision): string {
  const label = actionLabels[d.action_type] ?? d.action_type
  if (d.action_type === 'MARKDOWN' && d.discount_pct != null) return `${label} −${Math.round(d.discount_pct)}% · ${d.action_quantity}`
  return `${label} · ${d.action_quantity}`
}

/** รายละเอียดรองของ action (สูตร / partner / ราคาใหม่) */
export function actionDetail(item: ReviewItem): string | null {
  const d = item.decision
  if (!d) return null
  if (d.action_type === 'MARKDOWN' && d.new_recommended_price != null) return `New price ฿${d.new_recommended_price.toFixed(2)}`
  if (d.action_type === 'KITCHEN_REPURPOSE') {
    const recipe = item.recipe?.name ?? d.target_recipe_id ?? 'recipe'
    return d.batch_count ? `${recipe} · ${d.batch_count} batch` : recipe
  }
  if (item.partner) return item.partner.name
  return d.target_partner_id
}

export const managerRoleLabel = 'Store manager'
