import { useLocation } from 'react-router-dom'
import { managerRoleLabel } from '../../lib/labels'
import { useSession } from '../../lib/session'
import { StaffAvatar } from '../StaffAvatar'
import { useAgent } from '../agent/AgentProvider'
import { NotificationBell } from '../agent/NotificationBell'
import { LogOutIcon, SparklesIcon } from '../ui/icons'
import { NAV_ITEMS } from './nav'

export function Header() {
  const { manager, clear } = useSession()
  const { pathname } = useLocation()
  const page = NAV_ITEMS.find((n) => pathname.startsWith(n.path))
  const agent = useAgent()

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-8">
      <p className="text-[15px] text-slate-500">
        {page?.crumb}
        <span className="mx-2 text-slate-300">/</span>
        <span className="font-semibold text-slate-900">{page?.label}</span>
      </p>

      {manager && (
        <div className="flex items-center gap-3">
          <NotificationBell />
          <button type="button" onClick={agent.toggle} aria-pressed={agent.open}
            className={`mr-2 inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm font-semibold transition-colors ${
              agent.open ? 'border-brand bg-brand text-white' : 'border-orange-200 bg-white text-brand hover:bg-orange-50'
            }`}>
            <SparklesIcon className="size-4" />
            ผู้ช่วย AI
          </button>
          <StaffAvatar name={manager.full_name} imageUrl={manager.image_url} size={36} />
          <div className="leading-tight">
            <p className="text-sm font-semibold text-slate-900">{manager.full_name}</p>
            <p className="text-xs text-slate-500">{managerRoleLabel}</p>
          </div>
          <button type="button" onClick={clear} title="Change user" aria-label="Change user"
            className="ml-1 rounded-lg p-2 text-slate-400 hover:bg-orange-50 hover:text-brand">
            <LogOutIcon className="size-[18px]" />
          </button>
        </div>
      )}
    </header>
  )
}
