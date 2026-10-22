import { formatImpact } from '../../lib/format'
import type { AgentArtifact } from '../../types/agent'

type WhatIf = Extract<AgentArtifact, { type: 'what_if' }>

const tone = (n: number) => (Math.round(n) === 0 ? 'text-slate-700' : n > 0 ? 'text-emerald-700' : 'text-red-600')

/** ผลจำลอง what-if: กำไรก่อน / หลัง + หน่วยที่ย้ายวิธี + lot ที่เปลี่ยน (ตัวเลขทั้งหมดจาก Optimizer) */
export function WhatIfCard({ data }: { data: WhatIf }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <div className="border-b border-slate-100 px-3.5 py-2.5">
        <p className="text-[11px] font-bold tracking-[0.08em] text-slate-400">จำลองสถานการณ์ · ไม่เปลี่ยนแผนจริง</p>
        <p className="mt-0.5 text-sm font-semibold text-slate-800">{data.scenario.join(' + ')}</p>
      </div>

      <div className="grid grid-cols-3 gap-2 px-3.5 py-3 text-center">
        <div>
          <p className="text-[11px] text-slate-500">แผนจริง</p>
          <p className={`font-mono text-sm font-semibold ${tone(data.net_profit_before_thb)}`}>{formatImpact(data.net_profit_before_thb)}</p>
        </div>
        <div>
          <p className="text-[11px] text-slate-500">ถ้าเป็นแบบนี้</p>
          <p className={`font-mono text-sm font-semibold ${tone(data.net_profit_after_thb)}`}>{formatImpact(data.net_profit_after_thb)}</p>
        </div>
        <div className="rounded-lg bg-slate-50 py-0.5">
          <p className="text-[11px] text-slate-500">ส่วนต่าง</p>
          <p className={`font-mono text-sm font-bold ${tone(data.net_profit_change_thb)}`}>{formatImpact(data.net_profit_change_thb)}</p>
        </div>
      </div>

      {data.units_by_method.length > 0 && (
        <div className="border-t border-slate-100 px-3.5 py-2.5">
          <p className="mb-1 text-[11px] font-semibold text-slate-500">หน่วยที่เปลี่ยนวิธีจัดการ</p>
          <ul className="space-y-0.5 text-[13px]">
            {data.units_by_method.map((u) => (
              <li key={u.method} className="flex justify-between gap-2">
                <span className="text-slate-700">{u.method}</span>
                <span className="font-mono text-slate-600">
                  {u.before} → {u.after}{' '}
                  <span className={u.change > 0 ? 'text-slate-900' : 'text-slate-400'}>({u.change > 0 ? '+' : ''}{u.change})</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.changed_lots.length > 0 && (
        <details className="border-t border-slate-100 px-3.5 py-2.5">
          <summary className="cursor-pointer text-[12px] font-semibold text-brand">
            lot ที่แผนเปลี่ยน {data.changed_lots_total} lot
            {data.changed_lots_total > data.changed_lots.length && ` (แสดง ${data.changed_lots.length} lot ที่กระทบมากสุด)`}
          </summary>
          <ul className="mt-2 space-y-2">
            {data.changed_lots.map((c) => (
              <li key={c.lot_id} className="text-[12px] leading-snug">
                <p className="flex justify-between gap-2">
                  <span><span className="font-mono font-semibold text-slate-900">{c.lot_id}</span> <span className="text-slate-600">{c.name}</span></span>
                  <span className={`font-mono ${tone(c.net_profit_change_thb)}`}>{formatImpact(c.net_profit_change_thb)}</span>
                </p>
                <p className="text-slate-500">เดิม: {c.before}</p>
                <p className="text-slate-700">ใหม่: {c.after}</p>
              </li>
            ))}
          </ul>
        </details>
      )}

      {data.unresolved_units_after > data.unresolved_units_before && (
        <p className="border-t border-slate-100 px-3.5 py-2 text-[12px] font-semibold text-red-600">
          มี {data.unresolved_units_after} หน่วยที่ไม่มีทางไป (ต้องทิ้งเองในร้าน)
        </p>
      )}
    </div>
  )
}
