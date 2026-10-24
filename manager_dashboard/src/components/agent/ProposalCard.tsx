import { useState } from 'react'
import { Link } from 'react-router-dom'
import { dismissProposal, executeProposal } from '../../lib/agent'
import { errorMessage } from '../../lib/api'
import { formatTime } from '../../lib/format'
import { useSession } from '../../lib/session'
import type { AgentProposal } from '../../types/agent'
import { CheckIcon } from '../ui/icons'

const STATUS_LABEL: Record<AgentProposal['status'], { text: string; cls: string }> = {
  PROPOSED: { text: 'รอยืนยัน', cls: 'bg-orange-50 text-brand' },
  EXECUTED: { text: 'ทำแล้ว', cls: 'bg-emerald-50 text-emerald-700' },
  DISMISSED: { text: 'ไม่ทำ', cls: 'bg-slate-100 text-slate-500' },
  FAILED: { text: 'ทำไม่สำเร็จ', cls: 'bg-red-50 text-red-700' },
  EXPIRED: { text: 'หมดอายุ', cls: 'bg-slate-100 text-slate-500' },
}

/** ผลที่ server ทำหลังกดยืนยัน เป็นข้อความสั้นภาษาไทย */
function resultText(p: AgentProposal): string | null {
  const r = p.result
  if (!r) return null
  if (typeof r.error === 'string') return r.error
  const parts: string[] = []
  if (Array.isArray(r.released)) parts.push(`คืนเป็น IDLE ${r.released.length} lot`)
  if (Array.isArray(r.skipped) && r.skipped.length) parts.push(`ข้าม ${r.skipped.length} lot (มีงานหรือ plan ใหม่แล้ว)`)
  if (typeof r.hours_blocked === 'number') parts.push(`ปิดครัว ${r.hours_blocked} ชั่วโมง`)
  if (typeof r.pipeline_run_id === 'string') parts.push('เริ่ม pipeline แล้ว')
  if (typeof r.pipeline_error === 'string') parts.push(`เริ่ม pipeline ไม่ได้: ${r.pipeline_error}`)
  return parts.join(' · ') || null
}

/** การ์ดข้อเสนอของ agent: ผู้จัดการกด "ยืนยัน" แล้ว server ทำ (agent ทำเองไม่ได้) */
export function ProposalCard({ proposal, onChanged }: { proposal: AgentProposal; onChanged?: (p: AgentProposal) => void }) {
  const { manager } = useSession()
  const [p, setP] = useState(proposal)
  const [busy, setBusy] = useState<'execute' | 'dismiss' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const current = proposal.status !== 'PROPOSED' ? proposal : p   // Realtime โหลดสถานะใหม่มา = ใช้อันนั้น
  const label = STATUS_LABEL[current.status]
  const result = resultText(current)

  const act = async (kind: 'execute' | 'dismiss') => {
    if (!manager) return
    setBusy(kind)
    setError(null)
    try {
      const next = kind === 'execute'
        ? await executeProposal(current.proposal_id, manager.staff_id)
        : await dismissProposal(current.proposal_id, manager.staff_id)
      setP(next)
      onChanged?.(next)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="rounded-xl border border-orange-200 bg-white px-3.5 py-3">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[11px] font-bold tracking-[0.08em] text-slate-400">ข้อเสนอของผู้ช่วย AI</p>
        <span className={`shrink-0 rounded px-1.5 py-0.5 text-[11px] font-semibold ${label.cls}`}>{label.text}</span>
      </div>
      <p className="mt-0.5 text-sm font-semibold text-slate-900">{current.title}</p>
      {current.reason && <p className="mt-0.5 text-[13px] text-slate-600">{current.reason}</p>}

      {current.status === 'PROPOSED' ? (
        <div className="mt-2.5 flex gap-2">
          <button type="button" disabled={!!busy || !manager} onClick={() => void act('execute')}
            className="inline-flex h-8 items-center gap-1 rounded-lg bg-brand px-3 text-[13px] font-semibold text-white hover:bg-[#d4551f] disabled:opacity-50">
            <CheckIcon className="size-3.5" />
            {busy === 'execute' ? 'กำลังทำ…' : 'ยืนยัน'}
          </button>
          <button type="button" disabled={!!busy || !manager} onClick={() => void act('dismiss')}
            className="h-8 rounded-lg border border-slate-300 px-3 text-[13px] font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-50">
            {busy === 'dismiss' ? '…' : 'ไม่ทำ'}
          </button>
        </div>
      ) : (
        <p className={`mt-1.5 text-[12px] ${current.status === 'FAILED' ? 'text-red-600' : 'text-slate-500'}`}>
          {result}
          {current.decided_at && <span className="text-slate-400"> · {formatTime(current.decided_at)}</span>}
          {typeof current.result?.pipeline_run_id === 'string' && (
            <> · <Link to="/run-demo" className="font-semibold text-brand hover:underline">ดูความคืบหน้า</Link></>
          )}
        </p>
      )}
      {error && <p className="mt-1.5 text-[12px] text-red-600">{error}</p>}
    </div>
  )
}

/** การ์ดข้อเสนอจากแชทที่ server บันทึกไม่ได้ (เช่น ยังไม่ได้สร้างตาราง agent_proposals) */
export function UnsavedProposal({ title }: { title?: string }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white px-3.5 py-3 text-[13px] text-slate-500">
      <p className="font-semibold text-slate-700">{title ?? 'ข้อเสนอ'}</p>
      บันทึกข้อเสนอไม่สำเร็จ จึงกดยืนยันจากที่นี่ไม่ได้
    </div>
  )
}
