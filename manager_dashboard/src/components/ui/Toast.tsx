import { useEffect } from 'react'
import { XIcon } from './icons'

export interface ToastMessage {
  id: number
  tone: 'success' | 'error'
  text: string
}

/** แจ้งผลชั่วคราวมุมขวาล่าง (หายเองหลัง 5 วินาที) */
export function Toast({ toast, onDismiss }: { toast: ToastMessage | null; onDismiss: () => void }) {
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(onDismiss, 5000)
    return () => clearTimeout(t)
  }, [toast, onDismiss])

  if (!toast) return null
  const tone = toast.tone === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-red-200 bg-red-50 text-red-800'
  return (
    <div role="status" className={`fixed right-6 bottom-6 z-50 flex max-w-md items-start gap-3 rounded-xl border px-4 py-3 text-sm shadow-lg ${tone}`}>
      <p className="flex-1">{toast.text}</p>
      <button type="button" onClick={onDismiss} aria-label="Dismiss" className="opacity-60 hover:opacity-100">
        <XIcon className="size-4" />
      </button>
    </div>
  )
}
