import type { ReactNode } from 'react'
import { formatDuration, formatTime, secondsBetween } from '../lib/format'
import { ACTION_ORDER, actionLabels } from '../lib/labels'
import type { PipelineRun, StepInfo, StepName } from '../types/pipeline'
import type { RiskLevel } from '../types/review'
import { CheckIcon, XIcon } from './ui/icons'
import { SeverityBadge } from './ui/SeverityBadge'

// ไทม์ไลน์ 3 ขั้นของ AI pipeline ใช้ร่วมกันในหน้า Agent log (drawer) และหน้า Run demo (live)

export const STEPS: { key: StepName; label: string }[] = [
  { key: 'SCAN', label: 'Risk scan' },
  { key: 'OPTIMIZE', label: 'Optimizer' },
  { key: 'TASKS', label: 'Task writer (LLM)' },
]
const LEVELS: RiskLevel[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']

export type StepState = 'done' | 'failed' | 'running' | 'pending' | 'skipped'

export function stepState(run: PipelineRun, key: StepName, info: StepInfo | undefined): StepState {
  if (info?.status === 'OK') return 'done'
  if (info?.status === 'FAILED') return 'failed'
  if (info?.status === 'RUNNING') return run.status === 'FAILED' ? 'failed' : 'running'
  const order = STEPS.findIndex((s) => s.key === key)
  const stopAt = STEPS.findIndex((s) => s.key === run.stop_after)
  if (order > stopAt || run.status === 'SUCCEEDED' || run.status === 'FAILED') return 'skipped'
  return 'pending'
}

function StepIcon({ state }: { state: StepState }) {
  const base = 'flex size-7 shrink-0 items-center justify-center rounded-full'
  if (state === 'done') return <span className={`${base} bg-emerald-500 text-white`}><CheckIcon className="size-4" /></span>
  if (state === 'failed') return <span className={`${base} bg-red-500 text-white`}><XIcon className="size-4" /></span>
  if (state === 'running') return <span className={`${base} bg-orange-50 ring-2 ring-brand`}><span className="size-2.5 animate-pulse rounded-full bg-brand" /></span>
  return <span className={`${base} bg-slate-100 ring-1 ring-slate-200`} />
}

function Chip({ children }: { children: ReactNode }) {
  return <span className="inline-flex items-center gap-1.5 rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">{children}</span>
}

function StepBody({ step, info, run }: { step: StepName; info: StepInfo | undefined; run: PipelineRun }) {
  const s = info?.summary
  if (!s) return null
  if (step === 'SCAN') {
    return (
      <div className="space-y-2">
        <p className="text-sm text-slate-700">
          {s.lots ?? 0} lots scanned · <span className="font-semibold">{s.at_risk_lots ?? run.at_risk_lots ?? 0}</span> HIGH / CRITICAL sent to the optimizer
        </p>
        {s.levels && (
          <div className="flex flex-wrap gap-1.5">
            {LEVELS.filter((l) => s.levels?.[l]).map((l) => (
              <span key={l} className="inline-flex items-center gap-1"><SeverityBadge severity={l} /><span className="font-mono text-xs text-slate-700">{s.levels?.[l]}</span></span>
            ))}
          </div>
        )}
      </div>
    )
  }
  if (step === 'OPTIMIZE') {
    return (
      <div className="space-y-2">
        <p className="text-sm text-slate-700"><span className="font-semibold">{s.decisions_created ?? run.decisions_created ?? 0}</span> decisions</p>
        {s.actions && (
          <div className="flex flex-wrap gap-1.5">
            {ACTION_ORDER.filter((a) => s.actions?.[a]).map((a) => (
              <Chip key={a}>{actionLabels[a]} <span className="font-mono">{s.actions?.[a]}</span></Chip>
            ))}
          </div>
        )}
      </div>
    )
  }
  const plans = s.plans_queued ?? s.tasks_created ?? run.tasks_created ?? 0
  const failed = s.failed_batches ?? run.failed_batches ?? 0
  return (
    <div className="space-y-2">
      <p className="text-sm text-slate-700"><span className="font-semibold">{plans}</span> plans sent to the review queue</p>
      <div className="flex flex-wrap gap-1.5">
        {s.llm_ok != null && <Chip>LLM text <span className="font-mono">{s.llm_ok}</span></Chip>}
        {s.template_fallback != null && <Chip>Template text <span className="font-mono">{s.template_fallback}</span></Chip>}
        {failed > 0 && <span className="rounded-md bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700">{failed} batch(es) failed</span>}
      </div>
    </div>
  )
}

/** live = true: ขั้นที่กำลังทำแสดงเวลาที่ผ่านไป (ให้หน้าที่เรียกใช้ re-render ทุกวินาที) */
export function RunSteps({ run, live = false }: { run: PipelineRun; live?: boolean }) {
  return (
    <ol className="relative">
      {STEPS.map((step, i) => {
        const info = run.steps[step.key]
        const state = stepState(run, step.key, info)
        const elapsed = state === 'running' && live && info?.started_at ? secondsBetween(info.started_at) : null
        return (
          <li key={step.key} className="relative flex gap-3 pb-5 last:pb-0">
            {i < STEPS.length - 1 && <span className="absolute top-8 bottom-0 left-[13px] w-px bg-slate-200" aria-hidden="true" />}
            <StepIcon state={state} />
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex items-baseline justify-between gap-2">
                <p className={`font-semibold ${state === 'skipped' || state === 'pending' ? 'text-slate-400' : 'text-slate-900'}`}>{step.label}</p>
                <p className="font-mono text-xs text-slate-500">
                  {info?.started_at && formatTime(info.started_at)}
                  {info?.seconds != null && ` · ${formatDuration(info.seconds)}`}
                  {elapsed != null && ` · ${formatDuration(elapsed)}`}
                </p>
              </div>
              {state === 'skipped' && <p className="text-sm text-slate-400">Not run</p>}
              {state === 'pending' && <p className="text-sm text-slate-400">Waiting</p>}
              {state === 'running' && <p className="text-sm text-brand">Running…</p>}
              <div className="mt-1.5"><StepBody step={step.key} info={info} run={run} /></div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
