import { Link } from 'react-router-dom'
import { formatDay } from '../../lib/format'
import { aiStatusLabels, categoryLabels, formatQuantity, originLabels } from '../../lib/labels'
import type { InventoryLot, LotAIStatus } from '../../types/inventory'

const TH = 'px-4 py-3 text-left text-[13px] font-semibold text-slate-600 whitespace-nowrap'
const TD = 'px-4 py-3.5 align-top'

export type InvSortColumn = 'expires' | 'qty'
export interface InvSort {
  column: InvSortColumn
  dir: 'asc' | 'desc'
}

/** asc: expires = ใกล้หมดอายุก่อน, qty = น้อยก่อน (desc = กลับกัน) */
export function sortLots(lots: InventoryLot[], sort: InvSort): InventoryLot[] {
  const sign = sort.dir === 'asc' ? 1 : -1
  return [...lots].sort((a, b) => {
    const diff = sort.column === 'qty' ? a.current_quantity - b.current_quantity : a.days_left - b.days_left
    return sign * diff || a.lot_id.localeCompare(b.lot_id)
  })
}

function SortableTh({ label, column, sort, onSort, align = 'left' }: {
  label: string
  column: InvSortColumn
  sort: InvSort
  onSort: (c: InvSortColumn) => void
  align?: 'left' | 'right'
}) {
  const active = sort.column === column
  return (
    <th className={`${TH} ${align === 'right' ? 'text-right' : ''}`}
      aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" onClick={() => onSort(column)}
        className={`inline-flex items-center gap-1 hover:text-slate-900 ${active ? 'text-slate-900' : ''}`}>
        {label}
        {active && <span className="text-[10px] text-slate-900" aria-hidden="true">{sort.dir === 'asc' ? '▲' : '▼'}</span>}
      </button>
    </th>
  )
}

// AI status เป็นตัวอักษรธรรมดา (ไม่มีกรอบ/พื้นหลัง) แยกด้วยสีตัวอักษร
const AI_STATUS_STYLE: Record<LotAIStatus, string> = {
  IDLE: 'text-slate-500',
  PROCESSING: 'text-brand',
  CHECKED: 'text-emerald-700',
}

function ExpiresCell({ lot }: { lot: InventoryLot }) {
  const d = lot.days_left
  if (d < 0) {
    return (
      <div className="text-red-600">
        <p className="text-sm font-semibold">Expired</p>
        <p className="text-xs">{formatDay(`${lot.expiration_date}T12:00:00+07:00`)}</p>
      </div>
    )
  }
  const label = d === 0 ? 'Today' : d === 1 ? 'Tomorrow' : formatDay(`${lot.expiration_date}T12:00:00+07:00`)
  return (
    <div className={d <= 1 ? 'text-red-600' : d <= 2 ? 'text-orange-600' : 'text-slate-700'}>
      <p className="text-sm font-semibold">{label}</p>
      <p className="text-xs text-slate-500">{d === 0 ? 'last day' : `${d} days left`}</p>
    </div>
  )
}

function PriceCell({ lot }: { lot: InventoryLot }) {
  const regular = lot.product?.regular_price
  const pct = regular && lot.current_selling_price < regular ? Math.round((1 - lot.current_selling_price / regular) * 100) : 0
  return (
    <div className="text-right">
      <p className="font-mono text-sm font-semibold text-slate-900">฿{lot.current_selling_price.toFixed(2)}</p>
      {pct > 0 && regular && (
        <p className="text-xs">
          <span className="text-slate-400 line-through">฿{regular.toFixed(2)}</span>{' '}
          <span className="font-semibold text-brand">−{pct}%</span>
        </p>
      )}
    </div>
  )
}

/** คำถามของปุ่ม "ถาม AI": lot ที่เสี่ยง = ถามเหตุผลของแผน, lot อื่น = ถามสถานะ */
export function InventoryTable({ lots, sort, onSort }: { lots: InventoryLot[]; sort: InvSort; onSort: (c: InvSortColumn) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead className="border-y border-slate-200 bg-slate-50">
          <tr>
            <th className={`${TH} pl-5`}>Lot</th>
            <th className={TH}>Product</th>
            <th className={TH}>Location</th>
            <SortableTh label="Qty" column="qty" sort={sort} onSort={onSort} align="right" />
            <SortableTh label="Expires" column="expires" sort={sort} onSort={onSort} />
            <th className={`${TH} text-right`}>Price</th>
            <th className={TH}>AI status</th>
            <th className={`${TH} pr-5`}>Activity</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {lots.map((lot) => {
            const unit = lot.product?.unit_of_measure
            const empty = lot.current_quantity === 0
            return (
              <tr key={lot.lot_id} className={`transition-colors hover:bg-orange-50/40 ${empty ? 'opacity-60' : ''}`}>
                <td className={`${TD} pl-5`}>
                  <p className="font-mono text-sm font-bold text-slate-900">{lot.lot_id}</p>
                  {lot.origin !== 'SUPPLIER' && (
                    <span className="mt-0.5 inline-block rounded bg-orange-50 px-1.5 py-0.5 text-[11px] font-semibold text-brand">
                      {originLabels[lot.origin] ?? lot.origin}
                    </span>
                  )}
                </td>
                <td className={TD}>
                  <p className="max-w-64 truncate text-sm font-medium text-slate-900" title={lot.product?.name}>{lot.product?.name ?? lot.product_id}</p>
                  <p className="text-xs text-slate-500">{lot.product ? categoryLabels[lot.product.category] : ''}</p>
                </td>
                <td className={`${TD} font-mono text-sm whitespace-nowrap text-slate-600`}>
                  {[lot.location_aisle, lot.location_shelf].filter(Boolean).join(' / ') || '—'}
                </td>
                <td className={`${TD} text-right whitespace-nowrap`}>
                  <p className="text-sm font-semibold text-slate-900">{formatQuantity(lot.current_quantity, unit)}</p>
                  <p className="text-xs text-slate-500">of {lot.initial_quantity}</p>
                </td>
                <td className={TD}><ExpiresCell lot={lot} /></td>
                <td className={TD}><PriceCell lot={lot} /></td>
                <td className={TD}>
                  <span className={`text-sm font-semibold ${AI_STATUS_STYLE[lot.ai_status]}`}>
                    {aiStatusLabels[lot.ai_status] ?? lot.ai_status}
                  </span>
                </td>
                <td className={`${TD} pr-5 text-sm whitespace-nowrap`}>
                  {lot.waiting_plans === 0 && lot.open_tasks === 0 && <span className="text-slate-400">—</span>}
                  {lot.waiting_plans > 0 && (
                    <Link to="/review-queue" className="block font-semibold text-brand hover:underline">
                      {lot.waiting_plans} waiting review
                    </Link>
                  )}
                  {lot.open_tasks > 0 && <p className="text-slate-600">{lot.open_tasks} open task{lot.open_tasks > 1 ? 's' : ''}</p>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
