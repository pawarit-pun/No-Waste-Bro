import { useCallback, useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { getAutoApprovePolicy, saveAutoApprovePolicy } from '../../lib/agent'
import { errorMessage } from '../../lib/api'
import { formatThb } from '../../lib/format'
import { actionLabels } from '../../lib/labels'
import { useTableChanges } from '../../lib/supabase'
import type { AutoAction, AutoApproveParams, AutoApprovePolicy } from '../../types/agent'

const NUMBER_FIELDS: { key: Exclude<keyof AutoApproveParams, 'actions'>; label: string; unit: string; min: number; max: number }[] = [
  { key: 'max_discount_pct', label: 'Max discount', unit: '%', min: 0, max: 90 },
  { key: 'max_value_thb', label: 'Max value per plan', unit: '฿', min: 0, max: 100000 },
  { key: 'min_minutes_before_deadline', label: 'Min. time before deadline', unit: 'min', min: 0, max: 720 },
  { key: 'daily_limit', label: 'Plans per day', unit: 'plans', min: 1, max: 500 },
  { key: 'undo_minutes', label: 'Undo window', unit: 'min', min: 1, max: 120 },
]

function summary(p: AutoApprovePolicy) {
  const a = p.params
  const acts = a.actions.map((x) => actionLabels[x]).join(', ')
  return `${acts}${a.actions.includes('MARKDOWN') ? ` up to ${a.max_discount_pct}% off` : ''} · up to ${formatThb(a.max_value_thb)} per plan · only when no option is better · undo within ${a.undo_minutes} min`
}

/** แถบ Auto-approve บนหน้า Review queue: เปิด/ปิด ตั้งกติกา และดูจำนวนที่ AI อนุมัติวันนี้ */
export function AutoApprovePanel({ managerId, managerName }: { managerId?: string; managerName?: string }) {
  const [policy, setPolicy] = useState<AutoApprovePolicy | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<AutoApproveParams | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setPolicy(await getAutoApprovePolicy())
      setLoadError(null)
    } catch (err) {
      setLoadError(errorMessage(err, 'Could not load the auto-approve settings.'))
    }
  }, [])
  useEffect(() => { void load() }, [load])
  useTableChanges('agent_policies', load)
  useTableChanges('pending_tasks', load)

  const save = async (enabled: boolean, params: AutoApproveParams) => {
    if (!managerId) return
    setBusy(true)
    setError(null)
    try {
      setPolicy(await saveAutoApprovePolicy(managerId, enabled, params))
      setEditing(false)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (loadError && !policy) {
    return (
      <p className="mt-4 rounded-xl border border-dashed border-slate-300 px-4 py-3 text-[13px] text-slate-500">
        AI auto-approve is not available: {loadError} (run <span className="font-mono">server/scripts/auto_approve.sql</span> and deploy the server).
      </p>
    )
  }
  if (!policy) return <div className="mt-4 h-16 animate-pulse rounded-xl bg-slate-100" />

  const on = policy.enabled
  const owner = policy.owner?.full_name ?? policy.owner_staff_id
  const toggleAction = (a: AutoAction) =>
    setDraft((d) => d && { ...d, actions: d.actions.includes(a) ? d.actions.filter((x) => x !== a) : [...d.actions, a] })

  return (
    <section className="mt-4 rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-slate-900">
            AI auto-approve
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${on ? 'bg-brand text-white' : 'bg-slate-200 text-slate-600'}`}>
              {on ? 'ON' : 'OFF'}
            </span>
            {on && (
              <span className="text-[12px] font-medium text-slate-600">
                Today: {policy.today.approved} plan(s) in {policy.today.lots} lot(s) · {policy.today.remaining} left
              </span>
            )}
          </p>
          <p className="truncate text-[12px] text-slate-500" title={on ? summary(policy) : undefined}>
            {on
              ? `${summary(policy)} · recorded as approved by ${owner}`
              : 'Off. When on, the AI approves low-risk plans by itself after each pipeline run and each hourly check. You can undo.'}
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={() => { setDraft({ ...policy.params }); setEditing((v) => !v); setError(null) }}>
            {editing ? 'Close' : 'Settings'}
          </Button>
          <Button size="sm" variant={on ? 'outline' : 'primary'} disabled={busy || !managerId}
            onClick={() => void save(!on, policy.params)}>
            {busy ? 'Saving…' : on ? 'Turn off' : 'Turn on'}
          </Button>
        </div>
      </div>
      {error && !editing && <p className="mt-2 text-sm text-red-600">{error}</p>}

      {editing && draft && (
        <div className="mt-3 border-t border-slate-200 pt-3">
          <p className="text-[12px] font-semibold text-slate-600">Actions the AI may approve</p>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {policy.allowed_actions.map((a) => (
              <label key={a} className={`inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-[13px] ${draft.actions.includes(a) ? 'border-violet-400 bg-white text-violet-800' : 'border-slate-200 bg-white text-slate-600'}`}>
                <input type="checkbox" className="size-3.5 accent-violet-600" checked={draft.actions.includes(a)} onChange={() => toggleAction(a)} />
                {actionLabels[a]}
              </label>
            ))}
          </div>
          <p className="mt-1 text-[11px] text-slate-400">Kitchen, landfill and discard always need you: they use kitchen hours or cannot be undone.</p>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-5">
            {NUMBER_FIELDS.map((f) => (
              <label key={f.key} className="text-[12px] text-slate-600">
                {f.label}
                <span className="mt-1 flex items-center rounded-lg border border-slate-300 bg-white px-2 focus-within:border-brand">
                  <input type="number" min={f.min} max={f.max} value={draft[f.key]}
                    onChange={(e) => setDraft((d) => d && { ...d, [f.key]: Number(e.target.value) })}
                    className="h-8 w-full bg-transparent font-mono text-sm text-slate-900 outline-none" />
                  <span className="text-[11px] text-slate-400">{f.unit}</span>
                </span>
              </label>
            ))}
          </div>
          <p className="mt-3 text-[12px] text-slate-500">
            Every plan of a lot must pass, the optimizer must have no better option, the plan text must come from the LLM (not a
            template) and the lot must not be expired. Saving makes {managerName ?? 'you'} the owner: approvals are recorded under your name.
          </p>
          {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
          <div className="mt-3 flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
            <Button size="sm" variant="primary" disabled={busy || !managerId || (on && draft.actions.length === 0)}
              onClick={() => void save(on, draft)}>
              {busy ? 'Saving…' : 'Save settings'}
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}
