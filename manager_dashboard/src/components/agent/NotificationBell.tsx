import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { markAllNotificationsRead, markNotificationRead, watchNow } from '../../lib/agent'
import { formatWhen } from '../../lib/format'
import type { AgentNotification } from '../../types/agent'
import { BellIcon, SearchCheckIcon } from '../ui/icons'
import { AskAgentButton } from './AskAgentButton'
import { ProposalCard } from './ProposalCard'
import { useNotifications } from './useNotifications'

const SEVERITY_DOT: Record<AgentNotification['severity'], string> = {
  CRITICAL: 'bg-red-500', WARNING: 'bg-orange-400', INFO: 'bg-slate-300',
}

function NotificationItem({ n, onRead }: { n: AgentNotification; onRead: (id: string) => void }) {
  const unread = !n.read_at
  return (
    <li className={`px-4 py-3 ${unread ? 'bg-orange-50/40' : ''}`} onClick={() => unread && onRead(n.notification_id)}>
      <div className="flex items-start gap-2.5">
        <span className={`mt-1.5 size-2 shrink-0 rounded-full ${SEVERITY_DOT[n.severity]}`} aria-label={n.severity} />
        <div className="min-w-0 flex-1">
          <p className="flex items-baseline justify-between gap-2">
            <span className={`text-sm ${unread ? 'font-semibold text-slate-900' : 'font-medium text-slate-700'}`}>{n.title}</span>
            <span className="shrink-0 text-[11px] text-slate-400">{formatWhen(n.created_at)}</span>
          </p>
          <p className="mt-0.5 text-[13px] leading-relaxed text-slate-600">{n.message}</p>
          {n.proposal && <div className="mt-2"><ProposalCard proposal={n.proposal} /></div>}
          {n.event_type === 'AUTO_APPROVE' && (
            <Link to="/review-queue?tab=APPROVED" className="mt-1 inline-block text-[12px] font-semibold text-brand hover:underline">
              Open approved plans (undo here)
            </Link>
          )}
          {n.lot_id && (
            <div className="-ml-1.5 mt-1">
              <AskAgentButton compact lotId={n.lot_id} label="ถาม AI" question={`${n.lot_id} ตอนนี้เป็นยังไง ควรทำอะไรต่อ`} />
            </div>
          )}
        </div>
      </div>
    </li>
  )
}

/** กระดิ่งแจ้งเตือนของ Manager Agent ใน header (อัปเดตแบบ realtime) */
export function NotificationBell() {
  const { data, error, reload } = useNotifications()
  const [open, setOpen] = useState(false)
  const [checking, setChecking] = useState(false)
  const [checkNote, setCheckNote] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const unread = data?.unread ?? 0

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false)
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const read = async (id: string) => {
    await markNotificationRead(id).catch(() => undefined)
    void reload()
  }
  const readAll = async () => {
    await markAllNotificationsRead().catch(() => undefined)
    void reload()
  }
  const check = async () => {
    setChecking(true)
    try {
      const r = await watchNow()
      setCheckNote(r.started ? 'กำลังตรวจ… แจ้งเตือนใหม่จะขึ้นภายในไม่กี่วินาที' : 'ยังไม่ได้เปิดใช้ผู้ช่วย AI บน server นี้')
    } catch {
      setCheckNote('สั่งตรวจไม่สำเร็จ ลองใหม่อีกครั้ง')
    } finally {
      setChecking(false)
    }
  }

  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-label={`แจ้งเตือน${unread ? ` ${unread} รายการใหม่` : ''}`}
        aria-expanded={open}
        className={`relative rounded-lg p-2 transition-colors ${open ? 'bg-orange-50 text-brand' : 'text-slate-500 hover:bg-orange-50 hover:text-brand'}`}>
        <BellIcon className="size-5" />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[18px] rounded-full bg-red-500 px-1 text-center text-[11px] leading-[18px] font-bold text-white">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute top-full right-0 z-50 mt-2 flex max-h-[75vh] w-[420px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl">
          <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
            <p className="font-semibold text-slate-900">แจ้งเตือนจากผู้ช่วย AI</p>
            <div className="flex items-center gap-1">
              <button type="button" onClick={() => void check()} disabled={checking}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] font-semibold text-brand hover:bg-orange-50 disabled:opacity-50">
                <SearchCheckIcon className="size-3.5" />
                {checking ? 'กำลังสั่ง…' : 'ตรวจตอนนี้'}
              </button>
              {unread > 0 && (
                <button type="button" onClick={() => void readAll()}
                  className="rounded-md px-2 py-1 text-[12px] font-semibold text-slate-500 hover:bg-slate-100">อ่านทั้งหมด</button>
              )}
            </div>
          </div>
          {checkNote && <p className="border-b border-slate-100 bg-slate-50 px-4 py-2 text-[12px] text-slate-600">{checkNote}</p>}
          <div className="flex-1 overflow-y-auto">
            {data === null && !error ? (
              <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <div key={i} className="h-14 animate-pulse rounded-lg bg-slate-100" />)}</div>
            ) : error && !data ? (
              <p className="p-4 text-sm text-red-600">{error}</p>
            ) : !data?.items.length ? (
              <p className="p-6 text-center text-sm text-slate-500">ยังไม่มีแจ้งเตือน ผู้ช่วยตรวจร้านทุก 1 ชั่วโมง และแจ้งทันทีเมื่อมีงานถูกปฏิเสธ ครัวเต็ม หรือ pipeline ล้ม</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {data.items.map((n) => <NotificationItem key={n.notification_id} n={n} onRead={(id) => void read(id)} />)}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
