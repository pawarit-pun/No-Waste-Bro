import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react'
import type { AgentPage } from '../../types/agent'
import { SendIcon, SparklesIcon, TrashIcon, XIcon } from '../ui/icons'
import { AgentMessage } from './AgentMessage'
import { useAgent } from './AgentProvider'

export const AGENT_PANEL_WIDTH = 400

const SUGGESTIONS: Partial<Record<AgentPage, string[]>> & { default: string[] } = {
  default: ['วันนี้มีอะไรด่วนบ้าง', 'lot ไหนเสี่ยงที่สุดตอนนี้', 'งานไหนเลยกำหนดแล้วบ้าง'],
  inventory: ['lot ไหนหมดอายุวันนี้บ้าง', 'สรุป lot CRITICAL ให้หน่อย', 'ถ้ายอดขายลดลง 20% แผนจะเปลี่ยนยังไง'],
  review: ['แผนรอบนี้ดีกว่าขายปกติแล้วฝังกลบแค่ไหน', 'ถ้าไม่ลดราคาเลยจะเป็นยังไง', 'ถ้าฟาร์มอาหารสัตว์ไม่มารับจะเป็นยังไง'],
  'pipeline-runs': ['pipeline รอบล่าสุดเป็นยังไงบ้าง', 'แผนวันนี้มีงานอะไรบ้าง'],
  overview: ['สรุปแผนวันนี้ให้หน่อย', 'วันนี้ทำไปเท่าไรแล้ว', 'วันนี้มีอะไรด่วนบ้าง'],
  kitchen: ['งานครัววันนี้มีอะไรบ้าง', 'ถ้าครัวเดลี่ใช้ไม่ได้วันนี้ แผนจะเปลี่ยนยังไง', 'ทำไม AI ส่งวัตถุดิบเข้าครัว'],
}

const lotSuggestions = (lot: string) => [`ทำไม ${lot} ถึงได้แผนนี้`, `ถ้า ${lot} ไม่ลดราคาจะเป็นยังไง`, `${lot} มีงานค้างไหม`]

/** แผงแชทผู้ช่วย AI ชิดขวา (ไม่บังเนื้อหา: หน้าเว็บหดลงเท่าความกว้างแผง) เปิดได้จากทุกหน้า */
export function AgentPanel() {
  const { open, setOpen, messages, pending, page, lotId, setLotId, ask, retry, cancel, clear } = useAgent()
  const [draft, setDraft] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, pending])

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  useEffect(() => {
    if (!pending) return
    setElapsed(0)
    const t = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [pending])

  if (!open) return null

  const submit = (text = draft) => {
    if (!text.trim() || pending) return
    ask(text)
    setDraft('')
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  const suggestions = lotId ? lotSuggestions(lotId) : (page && SUGGESTIONS[page]) || SUGGESTIONS.default
  const last = messages[messages.length - 1]

  return (
    <aside
      aria-label="ผู้ช่วย AI"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation()
          setOpen(false)
        }
      }}
      style={{ width: AGENT_PANEL_WIDTH }}
      className="flex h-full shrink-0 flex-col border-l border-slate-200 bg-slate-50"
    >
      <header className="flex h-16 shrink-0 items-center justify-between gap-2 border-b border-slate-200 bg-white px-4">
        <div className="flex items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-lg bg-orange-50 text-brand">
            <SparklesIcon className="size-[18px]" />
          </span>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-slate-900">ผู้ช่วย AI</p>
            <p className="text-[11px] text-slate-500">อ่านข้อมูลอย่างเดียว · ตอบจากข้อมูลจริงของร้าน</p>
          </div>
        </div>
        <div className="flex items-center">
          {messages.length > 0 && (
            <button type="button" onClick={clear} title="ล้างบทสนทนา" aria-label="ล้างบทสนทนา"
              className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
              <TrashIcon className="size-4" />
            </button>
          )}
          <button type="button" onClick={() => setOpen(false)} title="ปิด (Esc)" aria-label="ปิด"
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <XIcon className="size-[18px]" />
          </button>
        </div>
      </header>

      <div ref={listRef} className="flex-1 space-y-4 overflow-y-auto px-4 py-4" aria-live="polite">
        {messages.length === 0 && (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-4 text-sm text-slate-600">
            <p className="font-semibold text-slate-800">ถามเรื่องร้านได้เลยครับ</p>
            <p className="mt-1 text-[13px] leading-relaxed">
              เช่น lot ไหนเสี่ยง ทำไม AI เลือกวิธีนี้ หรือ "ถ้า..." เพื่อจำลองสถานการณ์ ผู้ช่วยจะไม่อนุมัติหรือแก้ข้อมูลให้
            </p>
          </div>
        )}
        {messages.map((m) => (
          <AgentMessage key={m.id} msg={m} onRetry={m === last && m.error && !pending ? retry : undefined} />
        ))}
        {pending && (
          <div className="flex items-center gap-2 text-[13px] text-slate-500">
            <span className="flex gap-1" aria-hidden="true">
              {[0, 150, 300].map((d) => (
                <span key={d} className="size-1.5 animate-bounce rounded-full bg-brand" style={{ animationDelay: `${d}ms` }} />
              ))}
            </span>
            {elapsed < 4 ? 'กำลังค้นข้อมูล…' : elapsed < 12 ? `กำลังคำนวณ… ${elapsed} วินาที` : `ใช้เวลานานกว่าปกติ… ${elapsed} วินาที`}
            <button type="button" onClick={cancel} className="ml-auto text-[12px] font-semibold text-slate-500 hover:text-slate-800">ยกเลิก</button>
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-slate-200 bg-white px-4 pt-3 pb-4">
        {!pending && (messages.length === 0 || lotId) && (
          <div className="mb-2.5 flex flex-wrap gap-1.5">
            {suggestions.map((s) => (
              <button key={s} type="button" onClick={() => submit(s)}
                className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[12px] text-slate-700 hover:border-brand hover:text-brand">
                {s}
              </button>
            ))}
          </div>
        )}
        {lotId && (
          <p className="mb-2 flex items-center gap-1.5 text-[12px] text-slate-500">
            กำลังคุยเรื่อง <span className="font-mono font-semibold text-slate-800">{lotId}</span>
            <button type="button" onClick={() => setLotId(null)} aria-label="เลิกเลือก lot" className="rounded p-0.5 hover:bg-slate-100">
              <XIcon className="size-3" />
            </button>
          </p>
        )}
        <div className="flex items-end gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 focus-within:border-brand">
          <textarea
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            maxLength={1000}
            placeholder="พิมพ์คำถาม… (Enter ส่ง, Shift+Enter ขึ้นบรรทัด)"
            className="max-h-32 min-h-6 flex-1 resize-none bg-transparent text-sm outline-none placeholder:text-slate-400"
            style={{ fieldSizing: 'content' } as CSSProperties}
          />
          <button type="button" onClick={() => submit()} disabled={!draft.trim() || pending} aria-label="ส่ง"
            className="rounded-lg bg-brand p-1.5 text-white hover:bg-[#d4551f] disabled:bg-slate-200 disabled:text-slate-400">
            <SendIcon className="size-4" />
          </button>
        </div>
      </div>
    </aside>
  )
}
