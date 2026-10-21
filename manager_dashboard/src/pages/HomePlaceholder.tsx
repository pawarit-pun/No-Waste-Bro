import { Logo } from '../components/Logo'
import { StaffAvatar } from '../components/StaffAvatar'
import { staffSubtitle } from '../lib/labels'
import { useSession } from '../lib/session'

/** หน้าชั่วคราวหลังเลือกผู้จัดการ รอแบบ UI หน้าถัดไป */
export function HomePlaceholder() {
  const { manager, clear } = useSession()
  if (!manager) return null

  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between bg-gradient-to-r from-brand to-brand-dark px-6 py-4">
        <Logo tone="onBrand" />
        <div className="flex items-center gap-3">
          <StaffAvatar name={manager.full_name} imageUrl={manager.image_url} size={36} />
          <div className="hidden leading-tight sm:block">
            <p className="text-sm font-semibold text-white">{manager.full_name}</p>
            <p className="text-xs text-white/75">{staffSubtitle(manager.responsible_categories, manager.role)}</p>
          </div>
          <button
            type="button"
            onClick={clear}
            className="ml-2 rounded-lg border border-white/80 px-3 py-1.5 text-sm text-white hover:bg-white/15"
          >
            Change user
          </button>
        </div>
      </header>
      <main className="p-6">
        <p className="text-slate-500">
          เข้าระบบในชื่อ <span className="font-mono text-slate-700">{manager.staff_id}</span> แล้ว (หน้า dashboard จะทำในขั้นถัดไป)
        </p>
      </main>
    </div>
  )
}
