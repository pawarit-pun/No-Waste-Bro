import type { JSX } from 'react'
import { NavLink } from 'react-router-dom'
import { formatTime } from '../../lib/format'
import { STORE_LABEL } from '../../lib/labels'
import { LogoMark } from '../Logo'
import { AlertIcon, GridIcon, ListIcon, ShieldIcon } from '../ui/icons'
import { NAV_ITEMS, SECTIONS, type NavItem } from './nav'
import { useSidebarStatus, type PipelineStatus } from './useSidebarStatus'

const ICONS: Record<NavItem['icon'], (p: { className?: string }) => JSX.Element> = {
  grid: GridIcon,
  alert: AlertIcon,
  shield: ShieldIcon,
  list: ListIcon,
}

export function Sidebar() {
  const { waiting, pipeline } = useSidebarStatus()

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="flex items-center gap-3 border-b border-slate-200 px-5 py-4">
        <LogoMark className="size-10" />
        <div className="leading-tight">
          <p className="font-bold text-slate-900">No Waste Bro</p>
          <p className="text-[13px] text-slate-500">{STORE_LABEL}</p>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-5">
        {SECTIONS.map((section) => (
          <div key={section} className="mb-5">
            <p className="mb-1.5 px-3 text-[11px] font-bold tracking-[0.08em] text-slate-400">{section}</p>
            {NAV_ITEMS.filter((n) => n.section === section).map((item) => {
              const Icon = ICONS[item.icon]
              const badge = item.path === '/review-queue' && waiting ? waiting : null
              return (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    `relative mb-0.5 flex items-center gap-3 rounded-lg px-3 py-2.5 text-[15px] font-semibold transition-colors ${
                      isActive ? 'bg-orange-50 text-brand' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      {isActive && <span className="absolute top-2 bottom-2 -left-3 w-1 rounded-r bg-brand" />}
                      <Icon className="size-[18px]" />
                      <span className="flex-1">{item.label}</span>
                      {badge != null && (
                        <span className="min-w-6 rounded-md bg-brand px-1.5 py-0.5 text-center text-xs font-bold text-white">
                          {badge}
                        </span>
                      )}
                    </>
                  )}
                </NavLink>
              )
            })}
          </div>
        ))}
      </nav>

      <PipelineCard pipeline={pipeline} />
    </aside>
  )
}

const STATUS_STYLE: Record<PipelineStatus['status'], { dot: string; label: string }> = {
  QUEUED: { dot: 'bg-amber-400', label: 'Agent queued' },
  RUNNING: { dot: 'bg-brand animate-pulse', label: 'Agent running' },
  SUCCEEDED: { dot: 'bg-emerald-500', label: 'Last run succeeded' },
  FAILED: { dot: 'bg-red-500', label: 'Last run failed' },
}

function PipelineCard({ pipeline }: { pipeline: PipelineStatus | null }) {
  if (!pipeline) {
    return (
      <div className="border-t border-slate-200 px-5 py-4 text-[13px] text-slate-500">No agent runs yet</div>
    )
  }
  const s = STATUS_STYLE[pipeline.status]
  const when = pipeline.finished_at ?? pipeline.requested_at
  return (
    <div className="border-t border-slate-200 px-5 py-4">
      <p className="flex items-center gap-2 text-[13px] font-semibold text-slate-900">
        <span className={`size-2 rounded-full ${s.dot}`} />
        {s.label}
      </p>
      <p className="mt-1 text-[13px] text-slate-500">
        {pipeline.status === 'RUNNING' && pipeline.current_step
          ? `Step ${pipeline.current_step} · started ${formatTime(pipeline.requested_at)}`
          : `Last run ${formatTime(when)}`}
      </p>
    </div>
  )
}
