import { useMemo, useState, type ReactNode } from 'react'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/EmptyState'
import { ResetIcon } from '../../components/ui/icons'
import { Select } from '../../components/ui/Select'
import { formatLongDate, formatThb } from '../../lib/format'
import { aiStatusLabels, CATEGORY_ORDER, categoryLabels } from '../../lib/labels'
import type { InventoryLot, LotAIStatus } from '../../types/inventory'
import type { ProductCategory } from '../../types/staff'
import { InventoryTable, sortLots, type InvSort, type InvSortColumn } from './InventoryTable'
import { useInventory } from './useInventory'

type ExpiryFilter = 'ALL' | 'TODAY' | 'SOON' | 'EXPIRED'
const AI_STATUSES: LotAIStatus[] = ['IDLE', 'PROCESSING', 'CHECKED']

function StatCard({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-5 py-4">
      <p className="text-[13px] text-slate-500">{label}</p>
      <p className="mt-1 font-mono text-2xl font-semibold text-slate-900">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </div>
  )
}

const matchesExpiry = (lot: InventoryLot, f: ExpiryFilter) =>
  f === 'ALL' ||
  (f === 'TODAY' && lot.days_left === 0) ||
  (f === 'SOON' && lot.days_left >= 0 && lot.days_left <= 2) ||
  (f === 'EXPIRED' && lot.days_left < 0)

export function InventoryPage() {
  const [showEmpty, setShowEmpty] = useState(false)
  const { data, error, refreshing, reload } = useInventory(showEmpty)
  const [category, setCategory] = useState<ProductCategory | 'ALL'>('ALL')
  const [aiStatus, setAiStatus] = useState<LotAIStatus | 'ALL'>('ALL')
  const [expiry, setExpiry] = useState<ExpiryFilter>('ALL')
  const [sort, setSort] = useState<InvSort>({ column: 'expires', dir: 'asc' })

  // กดหัวคอลัมน์อื่น: เริ่มที่น้อยไปมาก, กดคอลัมน์เดิม: สลับ น้อยไปมาก ⇄ มากไปน้อย
  const onSort = (column: InvSortColumn) =>
    setSort((s) => (s.column === column && s.dir === 'asc' ? { column, dir: 'desc' } : { column, dir: 'asc' }))

  const items = useMemo(() => data?.items ?? [], [data])
  const lots = useMemo(() => sortLots(items.filter((l) =>
    (category === 'ALL' || l.product?.category === category) &&
    (aiStatus === 'ALL' || l.ai_status === aiStatus) &&
    matchesExpiry(l, expiry)), sort), [items, category, aiStatus, expiry, sort])

  // ตัวเลขสรุปนับเฉพาะ lot ที่ยังมีของ ไม่ขึ้นกับตัวกรอง
  const stats = useMemo(() => {
    const onHand = items.filter((l) => l.current_quantity > 0)
    const status = Object.fromEntries(AI_STATUSES.map((s) => [s, onHand.filter((l) => l.ai_status === s).length]))
    return {
      lots: onHand.length,
      units: onHand.reduce((n, l) => n + l.current_quantity, 0),
      today: onHand.filter((l) => l.days_left === 0).length,
      soon: onHand.filter((l) => l.days_left >= 0 && l.days_left <= 2).length,
      expired: onHand.filter((l) => l.days_left < 0).length,
      value: onHand.reduce((n, l) => n + l.current_quantity * (l.unit_cost ?? 0), 0),
      status,
    }
  }, [items])

  const filtersOn = category !== 'ALL' || aiStatus !== 'ALL' || expiry !== 'ALL'

  return (
    <div className="px-8 py-7">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">Inventory</h1>
          <p className="mt-1 text-[15px] text-slate-600">
            Every lot on the shelf right now{data ? ` · system date ${formatLongDate(data.reference_date)}` : ''}.
          </p>
        </div>
        <Button size="sm" variant="neutral" disabled={refreshing} onClick={() => void reload()}>
          <ResetIcon className={`size-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {data && (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Lots on hand" value={stats.lots} sub={`${stats.units.toLocaleString('en-US')} units`} />
          <StatCard label="Expiring today" value={<span className={stats.today ? 'text-red-600' : ''}>{stats.today}</span>}
            sub={`${stats.soon} within 2 days${stats.expired ? ` · ${stats.expired} expired` : ''}`} />
          <StatCard label="Stock value (at cost)" value={formatThb(stats.value)} />
          <StatCard label="AI status" value={`${stats.status.IDLE ?? 0} / ${stats.status.PROCESSING ?? 0} / ${stats.status.CHECKED ?? 0}`}
            sub="Idle / Processing / Checked" />
        </div>
      )}

      <section className="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 px-5 py-3.5">
          <Select label="Category" value={category} onChange={(e) => setCategory(e.target.value as ProductCategory | 'ALL')}>
            <option value="ALL">All</option>
            {CATEGORY_ORDER.map((c) => <option key={c} value={c}>{categoryLabels[c]}</option>)}
          </Select>
          <Select label="AI status" value={aiStatus} onChange={(e) => setAiStatus(e.target.value as LotAIStatus | 'ALL')}>
            <option value="ALL">All</option>
            {AI_STATUSES.map((s) => <option key={s} value={s}>{aiStatusLabels[s]}</option>)}
          </Select>
          <Select label="Expiry" value={expiry} onChange={(e) => setExpiry(e.target.value as ExpiryFilter)}>
            <option value="ALL">All</option>
            <option value="TODAY">Today</option>
            <option value="SOON">Within 2 days</option>
            <option value="EXPIRED">Expired</option>
          </Select>
          <label className="ml-auto flex cursor-pointer items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={showEmpty} onChange={(e) => setShowEmpty(e.target.checked)}
              className="size-4 cursor-pointer accent-[#e8622c]" />
            Show empty lots
          </label>
        </div>

        {data === null && !error ? (
          <div className="space-y-3 border-t border-slate-200 px-5 py-6">
            {[0, 1, 2].map((i) => <div key={i} className="h-12 animate-pulse rounded-lg bg-slate-100" />)}
          </div>
        ) : error && data === null ? (
          <div className="border-t border-slate-200">
            <EmptyState title="Could not load inventory">
              <p>{error}</p>
              <Button className="mt-3" size="sm" onClick={() => void reload()}>Try again</Button>
            </EmptyState>
          </div>
        ) : lots.length === 0 ? (
          <div className="border-t border-slate-200">
            <EmptyState title={filtersOn ? 'No lots match these filters' : 'No lots on hand'} />
          </div>
        ) : (
          <InventoryTable lots={lots} sort={sort} onSort={onSort} />
        )}

        {lots.length > 0 && (
          <div className="border-t border-slate-200 px-5 py-3 text-[13px] text-slate-500">
            {lots.length} of {items.length} lots
          </div>
        )}
      </section>
    </div>
  )
}
