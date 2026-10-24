import { Link } from 'react-router-dom'
import { formatTime } from '../../lib/format'
import type { AgentArtifact, ChatMessage } from '../../types/agent'
import { LotExplainCard } from './LotExplainCard'
import { ProposalCard, UnsavedProposal } from './ProposalCard'
import { WhatIfCard } from './WhatIfCard'

const TOOL_LABELS: Record<string, string> = {
  get_store_snapshot: 'ภาพรวมร้าน',
  list_at_risk_lots: 'lot เสี่ยง',
  get_lot: 'ข้อมูล lot',
  list_tasks: 'task',
  get_plan: 'แผน Optimizer',
  explain_decision: 'เหตุผลของแผน',
  what_if: 'จำลอง what-if',
  search_sop: 'SOP',
}

const RISK_DOT: Record<string, string> = { CRITICAL: 'bg-red-500', HIGH: 'bg-orange-500', MEDIUM: 'bg-amber-400', LOW: 'bg-slate-300' }

function ArtifactView({ a }: { a: AgentArtifact }) {
  switch (a.type) {
    case 'what_if':
      return <WhatIfCard data={a} />
    case 'lot_explain':
      return <LotExplainCard data={a} />
    case 'snapshot':
      return (
        <div className="grid grid-cols-3 gap-2 rounded-xl border border-slate-200 bg-white p-3 text-center">
          <div><p className="text-lg font-bold text-red-600">{a.lots_by_risk_level.CRITICAL ?? 0}</p><p className="text-[11px] text-slate-500">CRITICAL</p></div>
          <div><p className="text-lg font-bold text-slate-900">{a.plans_waiting_approval}</p><p className="text-[11px] text-slate-500">รออนุมัติ</p></div>
          <div><p className={`text-lg font-bold ${a.overdue_tasks ? 'text-red-600' : 'text-slate-900'}`}>{a.overdue_tasks}</p><p className="text-[11px] text-slate-500">งานเลยกำหนด</p></div>
        </div>
      )
    case 'lot_list':
      return (
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
          {a.lots.slice(0, 6).map((l) => (
            <li key={l.lot_id} className="flex items-center gap-2 px-3 py-2 text-[13px]">
              <span className={`size-2 shrink-0 rounded-full ${RISK_DOT[l.risk_level ?? ''] ?? 'bg-slate-300'}`} />
              <span className="font-mono font-semibold text-slate-900">{l.lot_id}</span>
              <span className="min-w-0 flex-1 truncate text-slate-600">{l.name}</span>
              <span className="shrink-0 text-slate-500">
                {l.days_left == null ? '' : l.days_left < 0 ? 'หมดอายุแล้ว' : l.days_left === 0 ? 'หมดวันนี้' : `อีก ${l.days_left} วัน`}
              </span>
            </li>
          ))}
        </ul>
      )
    case 'task_list':
      return (
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
          {a.tasks.slice(0, 6).map((t) => (
            <li key={t.task_id} className="px-3 py-2 text-[13px]">
              <p className="flex justify-between gap-2">
                <span className="font-semibold text-slate-800">{t.action} · {t.quantity} <span className="font-mono font-normal text-slate-500">{t.lot_id}</span></span>
                {t.overdue && <span className="shrink-0 text-[11px] font-semibold text-red-600">เลยกำหนด</span>}
              </p>
              <p className="text-slate-500">{t.staff} · {t.status}</p>
            </li>
          ))}
        </ul>
      )
    case 'lot':
      return (
        <Link to="/inventory" className="inline-block text-[13px] font-semibold text-brand hover:underline">
          ดู {a.lot_id} ในหน้า Inventory →
        </Link>
      )
    case 'proposal':
      return a.proposal ? <ProposalCard proposal={a.proposal} /> : <UnsavedProposal title={a.title} />
    case 'sources':
      return a.docs.length ? <p className="text-[12px] text-slate-500">อ้างอิง: {a.docs.join(', ')}</p> : null
    default:
      return null
  }
}

export function AgentMessage({ msg, onRetry }: { msg: ChatMessage; onRetry?: () => void }) {
  if (msg.role === 'user') {
    return (
      <div className="flex flex-col items-end">
        {msg.lotId && <span className="mb-1 font-mono text-[11px] text-slate-400">{msg.lotId}</span>}
        <p className="max-w-[85%] rounded-2xl rounded-br-md bg-brand px-3.5 py-2 text-sm whitespace-pre-line text-white">{msg.text}</p>
      </div>
    )
  }

  if (msg.error) {
    return (
      <div className="max-w-[92%] rounded-2xl rounded-bl-md border border-red-200 bg-red-50 px-3.5 py-2.5 text-sm text-red-700">
        {msg.text}
        {onRetry && (
          <button type="button" onClick={onRetry} className="mt-1 block text-[13px] font-semibold text-red-700 underline">ถามใหม่</button>
        )}
      </div>
    )
  }

  const meta = msg.answer
  const tools = [...new Set((meta?.tool_calls ?? []).map((t) => TOOL_LABELS[t.name] ?? t.name))]
  return (
    <div className="max-w-[92%] space-y-2">
      <p className="rounded-2xl rounded-bl-md border border-slate-200 bg-white px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-line text-slate-800">
        {msg.text}
      </p>
      {meta?.artifacts.map((a, i) => <ArtifactView key={i} a={a} />)}
      <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 px-1 text-[11px] text-slate-400">
        <span>{formatTime(msg.at)}</span>
        {tools.length > 0 && <span>· ข้อมูลจาก {tools.join(', ')}</span>}
        {meta?.model_used === 'TEMPLATE' && <span className="rounded bg-amber-50 px-1 text-amber-700">ข้อความสำเร็จรูป</span>}
      </p>
    </div>
  )
}
