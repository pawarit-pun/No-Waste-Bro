import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AskAgentButton } from '../../components/agent/AskAgentButton'
import { formatImpact, formatWhen } from '../../lib/format'
import type { Anomaly, DailyReport } from '../../types/daily'

const SEV: Record<Anomaly['severity'], string> = {
  CRITICAL: 'border-red-200 bg-red-50 text-red-800',
  WARNING: 'border-amber-200 bg-amber-50 text-amber-800',
  INFO: 'border-slate-200 bg-slate-50 text-slate-700',
}
const kg = (n?: number) => `${Math.round((n ?? 0) * 10) / 10} kg`

function Card({ title, sub, children, action }: { title: string; sub?: ReactNode; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-200 px-5 py-3.5">
        <div>
          <h2 className="font-semibold text-slate-900">{title}</h2>
          {sub && <p className="text-[12px] text-slate-500">{sub}</p>}
        </div>
        {action}
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  )
}

/** แถบ kg 3 ส่วน: ขายต่อ / ครัว / บริจาค (ส้ม), อาหารสัตว์ / ปุ๋ย / ก๊าซชีวภาพ (เขียว), ฝังกลบ / ทิ้ง (เทา) */
function KgSplit({ rescued = 0, recycled = 0, disposal = 0, verb }: { rescued?: number; recycled?: number; disposal?: number; verb: string }) {
  const total = rescued + recycled + disposal
  if (total <= 0) return null
  const pct = (n: number) => `${(n / total) * 100}%`
  return (
    <div className="mt-4">
      <div className="flex h-3 overflow-hidden rounded-full bg-slate-100">
        <div className="bg-brand" style={{ width: pct(rescued) }} />
        <div className="bg-emerald-500" style={{ width: pct(recycled) }} />
        <div className="bg-slate-400" style={{ width: pct(disposal) }} />
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-[12px]">
        <p><span className="mr-1 inline-block size-2 rounded-full bg-brand" />Sold / cooked / donated <b className="block font-mono text-sm text-slate-900">{kg(rescued)}</b></p>
        <p><span className="mr-1 inline-block size-2 rounded-full bg-emerald-500" />Feed / compost / biogas <b className="block font-mono text-sm text-slate-900">{kg(recycled)}</b></p>
        <p><span className="mr-1 inline-block size-2 rounded-full bg-slate-400" />Landfill / discard <b className="block font-mono text-sm text-slate-900">{kg(disposal)}</b></p>
      </div>
      <p className="mt-1 text-[11px] text-slate-400">{verb}, weight from each product’s net content</p>
    </div>
  )
}

function Anomalies({ items }: { items: Anomaly[] }) {
  if (!items.length) return <p className="mt-3 text-sm text-emerald-700">No anomalies found.</p>
  return (
    <ul className="mt-3 space-y-1.5">
      {items.map((a, i) => (
        <li key={i} className={`rounded-lg border px-3 py-2 text-[13px] ${SEV[a.severity]}`}>
          {a.text}
          {a.lot_ids?.length ? <span className="ml-1 font-mono text-[11px] opacity-75">({a.lot_ids.slice(0, 5).join(', ')}{a.lot_ids.length > 5 ? ' …' : ''})</span> : null}
        </li>
      ))}
    </ul>
  )
}

export function MorningCard({ report }: { report: DailyReport | null }) {
  if (!report) {
    return (
      <Card title="Morning brief">
        <p className="text-sm text-slate-500">
          Not made yet today. The agent starts the pipeline at 07:30 and writes the brief when it finishes. For a demo,
          run the pipeline or press “Morning brief now” on the Run demo page.
        </p>
      </Card>
    )
  }
  const m = report.metrics
  return (
    <Card title="Morning brief" sub={`Updated ${formatWhen(report.updated_at)}${report.model_used === 'TEMPLATE' ? ' · template text' : ''}`}
      action={<AskAgentButton label="ถาม AI" question="สรุปแผนวันนี้ให้หน่อย มีอะไรต้องระวังบ้าง" />}>
      {report.message && <p className="text-[15px] leading-relaxed text-slate-800">{report.message}</p>}
      <Anomalies items={report.anomalies} />

      {!!m.actions?.length && (
        <table className="mt-4 w-full text-sm">
          <thead>
            <tr className="text-left text-[12px] text-slate-500">
              <th className="pb-1.5 font-semibold">Plan</th>
              <th className="pb-1.5 text-right font-semibold">Units</th>
              <th className="pb-1.5 text-right font-semibold">kg</th>
              <th className="pb-1.5 text-right font-semibold">Expected profit</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {m.actions.map((a) => (
              <tr key={a.action_type}>
                <td className="py-1.5 text-slate-800">{a.label ?? a.action_type}</td>
                <td className="py-1.5 text-right font-mono">{a.units}</td>
                <td className="py-1.5 text-right font-mono">{a.kg}</td>
                <td className={`py-1.5 text-right font-mono ${a.expected_profit_thb < 0 ? 'text-red-600' : ''}`}>{formatImpact(a.expected_profit_thb)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <KgSplit rescued={m.rescued_kg} recycled={m.recycled_kg} disposal={m.planned_disposal_kg} verb="Planned" />

      {m.auto_approved && (
        <p className="mt-3 rounded-lg bg-violet-50 px-3 py-2 text-[13px] text-violet-900">
          AI auto-approve {m.auto_approved.enabled ? 'is on' : 'is off'}: <b className="font-mono">{m.auto_approved.approved}</b> plan(s) in{' '}
          <b className="font-mono">{m.auto_approved.lots}</b> lot(s) approved by the AI today
          {m.auto_approved.approved > 0 && <> · <Link to="/review-queue?tab=APPROVED" className="font-semibold underline">review or undo</Link></>}
        </p>
      )}

      {m.improvement_vs_baseline_thb != null && (
        <p className="mt-3 rounded-lg bg-orange-50 px-3 py-2 text-[13px] text-slate-700">
          Plan is <b className="font-mono">{formatImpact(m.improvement_vs_baseline_thb)}</b> vs selling at regular price then sending the rest to
          landfill (optimizer estimate, not sales data).
        </p>
      )}
    </Card>
  )
}

export function EveningCard({ report }: { report: DailyReport | null }) {
  if (!report) {
    return (
      <Card title="Evening summary">
        <p className="text-sm text-slate-500">Made at 21:30 from the tasks staff really completed. Press “Evening summary now” on the Run demo page to make it earlier.</p>
      </Card>
    )
  }
  const m = report.metrics
  const t = m.tasks
  return (
    <Card title="Evening summary" sub={`Updated ${formatWhen(report.updated_at)}`}>
      {report.message && <p className="text-[15px] leading-relaxed text-slate-800">{report.message}</p>}
      {t && (
        <div className="mt-3 grid grid-cols-5 gap-2 text-center">
          {([['Tasks', t.total], ['Done', t.completed], ['Open', t.open], ['Overdue', t.overdue], ['Rejected', t.rejected]] as const).map(([l, n]) => (
            <div key={l} className="rounded-lg bg-slate-50 py-2">
              <p className={`font-mono text-lg font-semibold ${l === 'Overdue' && n ? 'text-red-600' : 'text-slate-900'}`}>{n}</p>
              <p className="text-[11px] text-slate-500">{l}</p>
            </div>
          ))}
        </div>
      )}
      <Anomalies items={report.anomalies} />
      <KgSplit rescued={m.rescued_kg} recycled={m.recycled_kg} disposal={m.disposal_kg} verb="Really handled" />
    </Card>
  )
}
