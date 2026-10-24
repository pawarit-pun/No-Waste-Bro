import type { PartnerType, SlotAlert } from '../../types/pickups'

export const PARTNER_LABEL: Record<PartnerType, string> = {
  DONATION: 'Donation', ANIMAL_FEED: 'Animal feed', COMPOSTING: 'Compost', ANAEROBIC_DIGESTION: 'Biogas', LANDFILL: 'Landfill',
}
/** สีตามทางของของ: บริจาค = ส้ม (ยังถึงคน), รีไซเคิล = เขียว, ฝังกลบ = เทา (กติกาเดียวกับ Overview) */
export const PARTNER_TONE: Record<PartnerType, { badge: string; bar: string }> = {
  DONATION: { badge: 'bg-orange-50 text-brand', bar: 'bg-brand' },
  ANIMAL_FEED: { badge: 'bg-emerald-50 text-emerald-700', bar: 'bg-emerald-500' },
  COMPOSTING: { badge: 'bg-emerald-50 text-emerald-700', bar: 'bg-emerald-500' },
  ANAEROBIC_DIGESTION: { badge: 'bg-emerald-50 text-emerald-700', bar: 'bg-emerald-500' },
  LANDFILL: { badge: 'bg-slate-100 text-slate-700', bar: 'bg-slate-500' },
}
export const ALERT_TEXT: Record<SlotAlert, string> = {
  OVER_CAPACITY: 'Over capacity',
  BELOW_MIN: 'Below minimum',
  NOT_READY: 'Not ready',
  WAITING_APPROVAL: 'Waiting approval',
}
export const DAY_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
export const hhmm = (t: string | null) => (t ? t.slice(0, 5) : '—')
export const kgText = (n: number) => `${Math.round(n * 10) / 10} kg`
/** "16 Oct" จาก "2026-10-16" */
export const dayLabel = (d: string) =>
  new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'Asia/Bangkok' }).format(new Date(`${d}T12:00:00+07:00`))
export const isoWeekday = (d: string) => ((new Date(`${d}T12:00:00+07:00`).getUTCDay() + 6) % 7) + 1
