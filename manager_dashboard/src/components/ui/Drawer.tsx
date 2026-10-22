import { useEffect, type ReactNode } from 'react'
import { XIcon } from './icons'

/** แผงเลื่อนจากขวา ปิดด้วยปุ่ม X, กด Esc หรือคลิกพื้นหลัง */
export function Drawer({ open, onClose, title, subtitle, footer, children }: {
  open: boolean
  onClose: () => void
  title: ReactNode
  subtitle?: ReactNode
  footer?: ReactNode
  children: ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    // right = ความกว้างแผงผู้ช่วย AI (AppShell ตั้ง --agent-panel-w) ให้ drawer เปิดข้างแผงแชท
    <div className="fixed inset-y-0 left-0 z-40 flex justify-end" style={{ right: 'var(--agent-panel-w, 0px)' }}>
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} aria-hidden="true" />
      <aside role="dialog" aria-modal="true"
        className="relative flex h-full w-full max-w-[600px] flex-col bg-white shadow-2xl">
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-5">
          <div className="min-w-0">{title}{subtitle && <div className="mt-1">{subtitle}</div>}</div>
          <button type="button" onClick={onClose} aria-label="Close"
            className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900">
            <XIcon />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
        {footer && <footer className="border-t border-slate-200 bg-slate-50 px-6 py-4">{footer}</footer>}
      </aside>
    </div>
  )
}
