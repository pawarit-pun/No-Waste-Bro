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
