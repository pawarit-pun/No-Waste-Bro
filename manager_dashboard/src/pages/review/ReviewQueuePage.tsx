import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/EmptyState'
import { Select } from '../../components/ui/Select'
import { Tabs } from '../../components/ui/Tabs'
import { Toast, type ToastMessage } from '../../components/ui/Toast'
import { errorMessage } from '../../lib/api'
import { formatImpact, systemNow } from '../../lib/format'
import { ACTION_ORDER, SEVERITY_ORDER, actionLabels } from '../../lib/labels'
import { useSession } from '../../lib/session'
import type { ActionType, ReviewStatus, Severity } from '../../types/review'
import { groupReviews, sortGroups, type ReviewGroup, type SortKey } from './groups'
import { ReviewDrawer } from './ReviewDrawer'
import { ReviewTable } from './ReviewTable'
import { useReviewQueue } from './useReviewQueue'

const TABS: ReviewStatus[] = ['WAITING', 'APPROVED', 'REJECTED']
const isTab = (v: string | null): v is ReviewStatus => !!v && (TABS as string[]).includes(v)

export function ReviewQueuePage() {
  const { manager } = useSession()
  const [params, setParams] = useSearchParams()
  const tab: ReviewStatus = isTab(params.get('tab')) ? (params.get('tab') as ReviewStatus) : 'WAITING'
  const { data, error, loading, reload, approve, reject } = useReviewQueue(tab, manager?.staff_id)

  const [severity, setSeverity] = useState<Severity | 'ALL'>('ALL')
  const [action, setAction] = useState<ActionType | 'ALL'>('ALL')
  const [sort, setSort] = useState<SortKey>('oldest')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [bulkBusy, setBulkBusy] = useState(false)
  const [toast, setToast] = useState<ToastMessage | null>(null)
  const [tick, setTick] = useState(0)

  // เวลา "ตอนนี้" ของระบบขยับทุกนาที (ใช้เทียบ deadline)
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 60_000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    setSelected(new Set())
    setOpenKey(null)
  }, [tab])

  const referenceDate = data?.reference_date ?? ''
  const now = useMemo(() => (referenceDate ? systemNow(referenceDate) : new Date()), [referenceDate, tick])

  const allGroups = useMemo(() => groupReviews(data?.items ?? []), [data])
  const groups = useMemo(() => {
    const filtered = allGroups.filter((g) =>
      (severity === 'ALL' || g.severity === severity) &&
      (action === 'ALL' || g.items.some((i) => i.decision?.action_type === action)))
    return sortGroups(filtered, sort)
  }, [allGroups, severity, action, sort])

  // ตัดรายการที่เลือกไว้แต่หายไปแล้ว (มีคนอนุมัติ/ปฏิเสธไปก่อน)
  useEffect(() => {
    setSelected((prev) => {
      const keys = new Set(allGroups.map((g) => g.key))
      const next = new Set([...prev].filter((k) => keys.has(k)))
      return next.size === prev.size ? prev : next
    })
  }, [allGroups])

  const openGroup: ReviewGroup | null = allGroups.find((g) => g.key === openKey) ?? null
  const notify = (tone: ToastMessage['tone'], text: string) => setToast({ id: Date.now(), tone, text })
  const dismissToast = useCallback(() => setToast(null), [])

  const toggle = (key: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  const toggleAll = () =>
    setSelected((prev) => (groups.every((g) => prev.has(g.key)) ? new Set() : new Set(groups.map((g) => g.key))))

  const selectedGroups = allGroups.filter((g) => selected.has(g.key))
  const selectedIds = selectedGroups.flatMap((g) => g.items.map((i) => i.review_id))

  const handleApprove = async (ids: string[], note?: string) => {
    const res = await approve(ids, note)
    notify('success', `Approved ${res.approved} plan(s). ${res.tasks.length} task(s) sent to staff.`)
  }
  const handleReject = async (ids: string[], note: string) => {
    const res = await reject(ids, note)
    notify('success', `Rejected ${res.rejected} plan(s).` +
      (res.lots_reset.length ? ` ${res.lots_reset.join(', ')} will be planned again on the next run.` : ''))
  }
  const approveSelected = async () => {
    setBulkBusy(true)
    try {
      await handleApprove(selectedIds)
      setSelected(new Set())
    } catch (err) {
      notify('error', errorMessage(err))
    } finally {
      setBulkBusy(false)
    }
  }

  const counts = data?.counts
  const totalPlans = groups.reduce((n, g) => n + g.items.length, 0)
  const totalImpact = groups.reduce((n, g) => n + g.impact, 0)
  const filtersOn = severity !== 'ALL' || action !== 'ALL'

  return (
    <div className="px-8 py-7">
      <h1 className="text-3xl font-bold tracking-tight text-slate-900">Review queue</h1>
      <p className="mt-1 text-[15px] text-slate-600">Every AI plan waits here. Nothing reaches staff until you approve.</p>

      <div className="mt-6">
        <Tabs
          value={tab}
          onChange={(id) => setParams(id === 'WAITING' ? {} : { tab: id })}
          items={[
            { id: 'WAITING', label: 'Waiting', count: counts?.waiting },
            { id: 'APPROVED', label: 'Approved today', count: counts?.approved },
            { id: 'REJECTED', label: 'Rejected today', count: counts?.rejected },
          ]}
        />
      </div>

      <section className="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 px-5 py-3.5">
          <Select label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value as Severity | 'ALL')}>
            <option value="ALL">All</option>
            {SEVERITY_ORDER.map((s) => <option key={s} value={s}>{s.charAt(0) + s.slice(1).toLowerCase()}</option>)}
          </Select>
          <Select label="Action" value={action} onChange={(e) => setAction(e.target.value as ActionType | 'ALL')}>
            <option value="ALL">All actions</option>
            {ACTION_ORDER.map((a) => <option key={a} value={a}>{actionLabels[a]}</option>)}
          </Select>
          <div className="ml-auto flex items-center gap-2">
            {tab === 'WAITING' && selectedIds.length > 0 && (
              <Button variant="primary" size="sm" disabled={bulkBusy} onClick={approveSelected}>
                {bulkBusy ? 'Approving…' : `Approve selected (${selectedIds.length} plan${selectedIds.length > 1 ? 's' : ''})`}
              </Button>
            )}
            <Select label="Sort" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} className="border-transparent">
              <option value="oldest">Oldest first</option>
              <option value="deadline">Deadline soonest</option>
              <option value="severity">Severity</option>
            </Select>
          </div>
        </div>

        {loading && !data ? (
          <div className="space-y-3 border-t border-slate-200 px-5 py-6">
            {[0, 1, 2].map((i) => <div key={i} className="h-12 animate-pulse rounded-lg bg-slate-100" />)}
          </div>
        ) : error && !data ? (
          <div className="border-t border-slate-200">
            <EmptyState title="Could not load the review queue">
              <p>{error}</p>
              <Button className="mt-3" size="sm" onClick={() => void reload()}>Try again</Button>
            </EmptyState>
          </div>
        ) : groups.length === 0 ? (
          <div className="border-t border-slate-200">
            <EmptyState title={filtersOn ? 'No plans match these filters' : tab === 'WAITING' ? 'Nothing waiting for review' : `No plans ${tab === 'APPROVED' ? 'approved' : 'rejected'} today`}>
              {tab === 'WAITING' && !filtersOn && 'New plans appear here as soon as the AI pipeline finishes a run.'}
            </EmptyState>
          </div>
        ) : (
          <ReviewTable
            tab={tab}
            groups={groups}
            referenceDate={referenceDate}
            now={now}
            selected={selected}
            onToggle={toggle}
            onToggleAll={toggleAll}
            onReview={(g) => setOpenKey(g.key)}
          />
        )}

        {groups.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 px-5 py-3 text-[13px] text-slate-500">
            <p>
              {tab === 'WAITING'
                ? <>{totalPlans} of {counts?.waiting ?? totalPlans} waiting · <span className={`font-mono ${totalImpact < 0 ? 'text-red-600' : 'text-slate-700'}`}>{formatImpact(totalImpact)}</span> expected if all approved</>
                : <>{totalPlans} plan(s) · <span className="font-mono">{formatImpact(totalImpact)}</span> expected impact</>}
            </p>
            {tab === 'WAITING' && <p>Deadline = latest time staff can still act before the lot loses value</p>}
          </div>
        )}
      </section>

      <ReviewDrawer
        group={openGroup}
        now={now}
        onClose={() => setOpenKey(null)}
        onApprove={handleApprove}
        onReject={handleReject}
      />
      <Toast toast={toast} onDismiss={dismissToast} />
    </div>
  )
}
