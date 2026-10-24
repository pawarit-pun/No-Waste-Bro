import { formatDay, formatThb } from '../../lib/format'
import type { MenuDemand } from '../../types/kitchen'

const TH = 'px-4 py-3 text-left text-[13px] font-semibold text-slate-600 whitespace-nowrap'
const TD = 'px-4 py-3.5 align-top'
const one = (n: number) => Math.round(n * 10) / 10

function windowText(m: MenuDemand) {
  const from = formatDay(`${m.window_from}T12:00:00+07:00`)
  return m.window_from === m.window_to ? from : `${from} – ${formatDay(`${m.window_to}T12:00:00+07:00`)}`
}

/** ความต้องการเมนูของรอบพยากรณ์ล่าสุด: เหตุผลที่ Optimizer ส่งวัตถุดิบเข้าครัว (ทำได้ไม่เกิน "Make more") */
export function MenuDemandTable({ rows }: { rows: MenuDemand[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead className="border-y border-slate-200 bg-slate-50">
          <tr>
            <th className={`${TH} pl-5`}>Menu</th>
            <th className={TH}>Kitchen</th>
            <th className={TH}>Sells within</th>
            <th className={`${TH} text-right`}>Forecast demand</th>
            <th className={`${TH} text-right`}>On shelf</th>
            <th className={`${TH} text-right`}>Make more</th>
            <th className={`${TH} pr-5 text-right`}>Expected revenue</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((m) => (
            <tr key={m.recipe_id} className="hover:bg-orange-50/40">
              <td className={`${TD} pl-5`}>
                <p className="text-sm font-medium text-slate-900">{m.recipe_name ?? m.recipe_id}</p>
                <p className="text-xs text-slate-500">
                  {m.batch_output != null && `${m.batch_output} per batch`}
                  {m.prep_time_mins != null && ` · ${m.prep_time_mins} min`}
                </p>
              </td>
              <td className={`${TD} text-sm whitespace-nowrap text-slate-700`}>{m.department_name ?? m.department_id ?? '—'}</td>
              <td className={`${TD} text-sm whitespace-nowrap text-slate-700`}>{windowText(m)}</td>
              <td className={`${TD} text-right whitespace-nowrap`}>
                <p className="font-mono text-sm font-semibold text-slate-900">{one(m.gross_demand)}</p>
                <p className="font-mono text-xs text-slate-500">{one(m.low_qty)}–{one(m.high_qty)}</p>
              </td>
              <td className={`${TD} text-right font-mono text-sm text-slate-700`}>{m.current_stock}</td>
              <td className={`${TD} text-right`}>
                <span className={`font-mono text-sm font-semibold ${m.menu_qty > 0 ? 'text-brand' : 'text-slate-400'}`}>{one(m.menu_qty)}</span>
              </td>
              <td className={`${TD} pr-5 text-right font-mono text-sm text-slate-900`}>{formatThb(m.expected_revenue)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
