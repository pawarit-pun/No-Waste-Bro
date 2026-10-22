import { formatDay, formatImpact, formatTime } from '../../lib/format'
import type { AgentArtifact, ExplainPortion } from '../../types/agent'

type Explain = Extract<AgentArtifact, { type: 'lot_explain' }>

function PortionRow({ p }: { p: ExplainPortion }) {
  const extra = [
    p.discount_pct != null && p.unit_price != null ? `ลด ${p.discount_pct}% เหลือ ฿${p.unit_price.toFixed(2)}` : null,
    p.recipe ? `${p.recipe}${p.batches ? ` ${p.batches} batch` : ''}` : null,
    p.partner ? `${p.partner}${p.pickup_at ? ` · รับ ${formatDay(p.pickup_at)} ${formatTime(p.pickup_at)}` : ''}` : null,
  ].filter(Boolean)
  return (
    <li className="flex items-start justify-between gap-3 text-[13px]">
      <div className="min-w-0">
        <p className="font-semibold text-slate-800">
          {p.method} · {p.units}
          {p.provisional && <span className="ml-1.5 rounded bg-amber-50 px-1 py-0.5 text-[10px] font-semibold text-amber-700">แผนชั่วคราว</span>}
        </p>
        {extra.length > 0 && <p className="text-slate-500">{extra.join(' · ')}</p>}
      </div>
      <span className={`shrink-0 font-mono ${p.net_profit_thb < 0 ? 'text-red-600' : 'text-slate-700'}`}>{formatImpact(p.net_profit_thb)}</span>
    </li>
  )
}

/** เหตุผลของ Optimizer สำหรับ lot หนึ่ง: แผนแบ่งส่วน ราคาแต่ละระดับ ทางเลือกที่ถูกตัด */
export function LotExplainCard({ data }: { data: Explain }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <div className="flex items-start justify-between gap-2 border-b border-slate-100 px-3.5 py-2.5">
        <div className="min-w-0">
          <p className="font-mono text-sm font-bold text-slate-900">{data.lot_id}</p>
          <p className="truncate text-[13px] text-slate-600">{data.name} · {data.quantity} หน่วย · {data.risk_level}</p>
        </div>
        <span className={`shrink-0 font-mono text-sm font-semibold ${data.lot_net_profit_thb < 0 ? 'text-red-600' : 'text-slate-900'}`}>
          {formatImpact(data.lot_net_profit_thb)}
        </span>
      </div>

      <ul className="space-y-1.5 px-3.5 py-2.5">{data.plan.map((p, i) => <PortionRow key={i} p={p} />)}</ul>

      {data.price_options.length > 1 && (
        <div className="border-t border-slate-100 px-3.5 py-2.5">
          <p className="mb-1 text-[11px] font-semibold text-slate-500">ราคาแต่ละระดับ (กำไรทั้ง lot)</p>
          <div className="flex flex-wrap gap-1.5">
            {data.price_options.map((o) => (
              <span key={o.discount_pct}
                className={`rounded-md border px-2 py-1 text-[12px] ${o.chosen ? 'border-brand bg-orange-50 text-slate-900' : 'border-slate-200 text-slate-600'}`}>
                {o.discount_pct === 0 ? 'ราคาปกติ' : `ลด ${o.discount_pct}%`}
                <span className="ml-1 font-mono">{formatImpact(o.lot_net_profit_thb)}</span>
                {o.chosen && <span className="ml-1 font-semibold text-brand">✓</span>}
              </span>
            ))}
          </div>
        </div>
      )}

      {data.excluded_options.length > 0 && (
        <details className="border-t border-slate-100 px-3.5 py-2.5">
          <summary className="cursor-pointer text-[12px] font-semibold text-brand">ทางเลือกที่ทำไม่ได้ {data.excluded_options.length} ทาง</summary>
          <ul className="mt-1.5 space-y-1">
            {data.excluded_options.map((e) => (
              <li key={e.option} className="text-[12px] text-slate-600">
                <span className="font-mono text-slate-800">{e.option}</span> — {e.reasons.join(' · ')}
              </li>
            ))}
          </ul>
        </details>
      )}

      {data.saved_decisions.length > 0 && (
        <p className="border-t border-slate-100 px-3.5 py-2 text-[12px] text-slate-500">
          ที่บันทึกตอนรัน pipeline: {data.saved_decisions.map((d) => `${d.action} ${d.quantity}${d.status ? ` (${d.status})` : ''}`).join(', ')}
        </p>
      )}
    </div>
  )
}
