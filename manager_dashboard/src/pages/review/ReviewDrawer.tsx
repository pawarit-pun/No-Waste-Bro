import { useEffect, useState, type ReactNode } from 'react'
import { AskAgentButton } from '../../components/agent/AskAgentButton'
import { Button } from '../../components/ui/Button'
import { Drawer } from '../../components/ui/Drawer'
import { CheckIcon, MapPinIcon } from '../../components/ui/icons'
import { SeverityBadge } from '../../components/ui/SeverityBadge'
import { apiGet, errorMessage } from '../../lib/api'
import { formatDay, formatImpact, formatTime } from '../../lib/format'
import { actionDetail, actionHeadline, actionLabels } from '../../lib/labels'
import type { Alternative, ReviewItem } from '../../types/review'
import { deadlineState, type ReviewGroup } from './groups'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mt-4">
      <p className="mb-1.5 text-[11px] font-bold tracking-[0.08em] text-slate-400 uppercase">{title}</p>
      {children}
    </div>
  )
}

function AlternativeRow({ alt }: { alt: Alternative }) {
  if (alt.option) {
    return (
      <li className="flex gap-2 text-sm">
        <span className="text-slate-400">✕</span>
        <span className="text-slate-600">
          <span className="font-mono text-xs text-slate-800">{alt.option}</span>
          {alt.rejected_because?.length ? <span className="text-slate-500"> — ruled out: {alt.rejected_because.join(' · ')}</span> : null}
        </span>
      </li>
    )
  }
  const title = `${alt.action_type ? actionLabels[alt.action_type] : 'Option'}${alt.discount_pct != null ? ` −${alt.discount_pct}%` : ''}${alt.partner_id ? ` · ${alt.partner_id}` : ''}`
  return (
    <li className="flex items-start justify-between gap-3 text-sm">
      <span className="text-slate-700">
        <span className="font-medium">{title}</span>
        {alt.note && <span className="block text-xs text-slate-500">{alt.note}</span>}
      </span>
      {alt.expected_profit_impact != null && (
        <span className={`font-mono text-sm ${alt.expected_profit_impact < 0 ? 'text-red-600' : 'text-slate-700'}`}>
          {formatImpact(alt.expected_profit_impact)}
        </span>
      )}
    </li>
  )
}

function PlanCard({ item, alternatives }: { item: ReviewItem; alternatives: Alternative[] | undefined }) {
  const d = item.decision
  const model = item.model_used === 'TEMPLATE' ? 'Template text' : item.model_used?.split('.').pop()
  return (
    <article className="rounded-xl border border-slate-200 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-slate-900">{d ? actionHeadline(d, item.product?.unit_of_measure) : '—'}</p>
          {actionDetail(item) && <p className="text-sm text-slate-500">{actionDetail(item)}</p>}
        </div>
        {d?.expected_profit_impact != null && (
          <span className={`font-mono font-semibold ${d.expected_profit_impact < 0 ? 'text-red-600' : 'text-slate-900'}`}>
            {formatImpact(d.expected_profit_impact)}
          </span>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] font-semibold">
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">Priority P{item.priority}</span>
        {model && (
          <span className={`rounded px-1.5 py-0.5 ${item.model_used === 'TEMPLATE' ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-600'}`}>
            {model}
          </span>
        )}
        {item.review_deadline && (
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">
            Due {formatDay(item.review_deadline)} {formatTime(item.review_deadline)}
          </span>
        )}
      </div>

      <Section title="Why the AI chose this">
        <p className="text-sm leading-relaxed text-slate-700">{item.ai_reasoning ?? '—'}</p>
      </Section>

      <Section title="What staff will see">
        {item.staff_instructions && <p className="text-sm font-medium text-slate-800">{item.staff_instructions}</p>}
        {item.instruction_steps?.length ? (
          <ol className="mt-2 space-y-1.5">
            {item.instruction_steps.map((s, i) => (
              <li key={i} className="flex gap-2.5 text-sm">
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-orange-50 text-[11px] font-bold text-brand">{i + 1}</span>
                <span><span className="font-semibold text-slate-800">{s.title}</span> <span className="text-slate-600">{s.detail}</span></span>
              </li>
            ))}
          </ol>
        ) : null}
      </Section>

      <Section title="Other options the optimizer considered">
        {alternatives === undefined ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : alternatives.length === 0 ? (
          <p className="text-sm text-slate-500">No other options recorded.</p>
        ) : (
          <ul className="space-y-1.5">{alternatives.map((a, i) => <AlternativeRow key={i} alt={a} />)}</ul>
        )}
      </Section>
    </article>
  )
}

export function ReviewDrawer({ group, now, onClose, onApprove, onReject }: {
  group: ReviewGroup | null
  now: Date
  onClose: () => void
  onApprove: (ids: string[], note?: string) => Promise<void>
  onReject: (ids: string[], note: string) => Promise<void>
}) {
  const [alternatives, setAlternatives] = useState<Record<string, Alternative[]>>({})
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const key = group?.key
  useEffect(() => {
    setNote('')
    setError(null)
    setAlternatives({})
    if (!group) return
    let cancelled = false
    void Promise.all(
      group.items.map((i) =>
        apiGet<ReviewItem>(`/pending-tasks/${i.review_id}`)
          .then((detail) => [i.review_id, detail.decision?.alternatives ?? []] as const)
          .catch(() => [i.review_id, []] as const),
      ),
    ).then((pairs) => {
      if (!cancelled) setAlternatives(Object.fromEntries(pairs))
    })
    return () => { cancelled = true }
  }, [key])

  if (!group) return null
  const first = group.items[0]
  const ids = group.items.map((i) => i.review_id)
  const waiting = group.status === 'WAITING'
  const lot = first.lot
  const a = first.assessment
  const overdue = deadlineState(group.deadline, now) === 'overdue'

  const run = async (kind: 'approve' | 'reject') => {
    if (kind === 'reject' && !note.trim()) {
      setError('Add a reason before rejecting.')
      return
    }
    setBusy(kind)
    setError(null)
    try {
      if (kind === 'approve') await onApprove(ids, note.trim() || undefined)
      else await onReject(ids, note.trim())
      onClose()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Drawer
      open
      onClose={onClose}
      title={
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-lg font-bold text-slate-900">{group.lotId}</span>
            <SeverityBadge severity={group.severity} />
          </div>
          <p className="text-[15px] text-slate-700">{group.productName}</p>
          <div className="mt-2">
            <AskAgentButton lotId={group.lotId} label="ถาม AI เรื่อง lot นี้"
              question={`ทำไม ${group.lotId} ถึงได้แผนนี้ มีทางเลือกอื่นไหม`} />
          </div>
        </div>
      }
      subtitle={
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-slate-500">
          {lot && (
            <span className="inline-flex items-center gap-1">
              <MapPinIcon className="size-3.5" />{[lot.location_aisle, lot.location_shelf].filter(Boolean).join(' / ') || '—'}
            </span>
          )}
          {lot && <span>Expires {formatDay(`${lot.expiration_date}T12:00:00+07:00`)}</span>}
          {lot && <span>{lot.current_quantity} on hand</span>}
          {a && <span>Risk {Math.round(a.risk_score)} · ~{Math.round(a.predicted_leftover_units)} left at expiry</span>}
        </div>
      }
      footer={
        waiting ? (
          <div>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              maxLength={500}
              placeholder="Note (optional to approve, required to reject)"
              className="w-full resize-none rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand"
            />
            {overdue && <p className="mt-1 text-xs font-semibold text-red-600">The deadline has passed. Consider rejecting so the lot is planned again.</p>}
            {error && <p className="mt-1 text-sm text-red-600">{error}</p>}
            <div className="mt-3 flex items-center justify-between gap-3">
              <p className="text-sm text-slate-500">
                Total <span className={`font-mono font-semibold ${group.impact < 0 ? 'text-red-600' : 'text-slate-900'}`}>{formatImpact(group.impact)}</span>
              </p>
              <div className="flex gap-2">
                <Button variant="danger" disabled={!!busy} onClick={() => run('reject')}>
                  {busy === 'reject' ? 'Rejecting…' : 'Reject'}
                </Button>
                <Button variant="primary" disabled={!!busy} onClick={() => run('approve')}>
                  <CheckIcon className="size-4" />
                  {busy === 'approve' ? 'Approving…' : `Approve ${ids.length > 1 ? `${ids.length} plans` : 'plan'}`}
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <p className="text-sm text-slate-600">
            {group.status === 'APPROVED' ? 'Approved' : 'Rejected'} by{' '}
            <span className="font-semibold">{first.reviewer?.full_name ?? first.reviewed_by}</span>
            {first.reviewed_at && <> at {formatTime(first.reviewed_at)}</>}
            {first.review_note && <span className="block text-slate-500">“{first.review_note}”</span>}
          </p>
        )
      }
    >
      <div className="space-y-4">
        {group.items.map((item) => (
          <PlanCard key={item.review_id} item={item} alternatives={alternatives[item.review_id]} />
        ))}
      </div>
    </Drawer>
  )
}
