const TZ = 'Asia/Bangkok'

const timeFmt = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const dayFmt = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, day: 'numeric', month: 'short' })
const isoDateFmt = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' })
const longDateFmt = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, weekday: 'long', day: 'numeric', month: 'short', year: 'numeric' })
const thbFmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

/** "14:05" เวลาไทย */
export const formatTime = (iso: string) => timeFmt.format(new Date(iso))

/** "16 Oct" */
export const formatDay = (iso: string) => dayFmt.format(new Date(iso))

/** "Friday 16 Oct 2026" จากวันที่ YYYY-MM-DD */
export const formatLongDate = (isoDate: string) => longDateFmt.format(new Date(`${isoDate}T12:00:00+07:00`))

/** วันที่ YYYY-MM-DD ตามเวลาไทย */
export const bkkDate = (d: Date = new Date()) => isoDateFmt.format(d)

/** เที่ยงคืนของวันนี้ (นาฬิกาจริง) ตามเวลาไทย ใช้กรอง "Approved today / Rejected today" */
export const bkkMidnightIso = () => `${bkkDate()}T00:00:00+07:00`

/**
 * "ตอนนี้" ของระบบ = วันที่ของระบบ (reference_date / DEMO_DATE จาก server) + เวลาปัจจุบันตามนาฬิกาไทย
 * เหมือน now_bkk() ฝั่ง server ใช้เทียบ deadline ของข้อมูล demo
 */
export function systemNow(referenceDate: string): Date {
  const hhmm = formatTime(new Date().toISOString())
  return new Date(`${referenceDate}T${hhmm}:00+07:00`)
}

/** "฿1,234" */
export const formatThb = (n: number) => `฿${thbFmt.format(Math.abs(n))}`

/** "+฿1,234" / "−฿358" */
export const formatImpact = (n: number) => (Math.round(n) === 0 ? '฿0' : `${n > 0 ? '+' : '−'}${formatThb(n)}`)

/** "Today 14:39" ถ้าเป็นวันนี้ตามปฏิทิน (นาฬิกาจริง) ไม่งั้น "21 Oct 14:39" */
export const formatWhen = (iso: string) =>
  `${bkkDate(new Date(iso)) === bkkDate() ? 'Today' : formatDay(iso)} ${formatTime(iso)}`

/** ระยะเวลาเป็นวินาที → "45s" / "2m 21s" / "1h 5m" */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${s % 60}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

/** วินาทีระหว่าง 2 เวลา (ไม่มีเวลาจบ = ถึงตอนนี้) */
export const secondsBetween = (from: string, to?: string | null) =>
  ((to ? new Date(to) : new Date()).getTime() - new Date(from).getTime()) / 1000
