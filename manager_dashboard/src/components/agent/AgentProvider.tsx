import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { agentErrorText, askAgent, warmUpAgent } from '../../lib/agent'
import type { AgentPage, AgentTurn, ChatMessage } from '../../types/agent'

// บทสนทนาอยู่ได้จนปิดแท็บ (sessionStorage) เก็บล่าสุด 10 รอบถาม-ตอบ
const STORAGE_KEY = 'nwb.agent.chat'
const OPEN_KEY = 'nwb.agent.open'
const MAX_TURNS = 10

const PAGE_BY_PATH: [string, AgentPage][] = [
  ['/overview', 'overview'], ['/inventory', 'inventory'], ['/risk-monitor', 'risk-monitor'],
  ['/review-queue', 'review'], ['/run-demo', 'run-demo'], ['/pipeline-runs', 'pipeline-runs'],
]

function readJson<T>(storage: () => Storage, key: string, fallback: T): T {
  try {
    const raw = storage().getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function writeJson(storage: () => Storage, key: string, value: unknown) {
  try {
    storage().setItem(key, JSON.stringify(value))
  } catch {
    // storage ใช้ไม่ได้ (private mode / เต็ม) → จำแค่ในหน่วยความจำ
  }
}

const session = () => window.sessionStorage

/** บทสนทนาก่อนหน้าที่ส่งให้ agent: เฉพาะคู่ถาม-ตอบที่สำเร็จ ล่าสุด MAX_TURNS รอบ */
function historyFor(messages: ChatMessage[]): AgentTurn[] {
  const turns: AgentTurn[] = []
  for (let i = 0; i < messages.length - 1; i++) {
    const q = messages[i]
    const a = messages[i + 1]
    if (q.role === 'user' && a.role === 'assistant' && !a.error) {
      turns.push({ role: 'user', text: q.text }, { role: 'assistant', text: a.text })
      i++
    }
  }
  return turns.slice(-MAX_TURNS * 2)
}

interface AgentValue {
  open: boolean
  setOpen: (open: boolean) => void
  toggle: () => void
  messages: ChatMessage[]
  pending: boolean
  page: AgentPage | undefined
  lotId: string | null
  setLotId: (lotId: string | null) => void
  /** ส่งคำถาม (lotId = เปลี่ยน lot ที่กำลังคุยถึงก่อนส่ง) */
  ask: (question: string, lotId?: string | null) => void
  /** เปิดแผงแล้วถามเรื่อง lot นี้ทันที (ปุ่ม "ถาม AI") */
  askAbout: (lotId: string, question: string) => void
  retry: () => void
  cancel: () => void
  clear: () => void
}

const AgentContext = createContext<AgentValue | null>(null)

export function AgentProvider({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const page = PAGE_BY_PATH.find(([p]) => pathname.startsWith(p))?.[1]
  const [open, setOpenState] = useState<boolean>(() => readJson(session, OPEN_KEY, false))
  const [messages, setMessages] = useState<ChatMessage[]>(() => readJson<ChatMessage[]>(session, STORAGE_KEY, []))
  const [pending, setPending] = useState(false)
  const [lotId, setLotId] = useState<string | null>(null)
  const inflight = useRef<AbortController | null>(null)
  const warmed = useRef(false)
  const messagesRef = useRef(messages)
  messagesRef.current = messages

  useEffect(() => writeJson(session, STORAGE_KEY, messages.slice(-MAX_TURNS * 2)), [messages])
  useEffect(() => writeJson(session, OPEN_KEY, open), [open])
  useEffect(() => {
    if (open && !warmed.current) {
      warmed.current = true
      warmUpAgent()
    }
  }, [open])
  useEffect(() => () => inflight.current?.abort(), [])

  const setOpen = useCallback((v: boolean) => setOpenState(v), [])
  const toggle = useCallback(() => setOpenState((v) => !v), [])

  const send = useCallback((question: string, lot: string | null) => {
    const text = question.trim()
    if (!text || inflight.current) return
    const history = historyFor(messagesRef.current)
    const now = new Date().toISOString()
    const userMsg: ChatMessage = { id: `u-${Date.now()}`, role: 'user', text, at: now, lotId: lot ?? undefined }
    setMessages((m) => [...m, userMsg])
    setPending(true)
    const ctrl = new AbortController()
    inflight.current = ctrl
    askAgent(text, history, { page, lot_id: lot ?? undefined }, ctrl.signal)
      .then(({ answer, ...meta }) => {
        if (ctrl.signal.aborted) return
        setMessages((m) => [...m, { id: `a-${Date.now()}`, role: 'assistant', text: answer, at: new Date().toISOString(), answer: meta }])
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return
        setMessages((m) => [...m, { id: `e-${Date.now()}`, role: 'assistant', text: agentErrorText(err), at: new Date().toISOString(), error: true }])
      })
      .finally(() => {
        if (inflight.current === ctrl) {
          inflight.current = null
          setPending(false)
        }
      })
  }, [page])

  const ask = useCallback((question: string, lot?: string | null) => {
    const next = lot === undefined ? lotId : lot
    if (lot !== undefined) setLotId(lot)
    send(question, next)
  }, [lotId, send])

  const askAbout = useCallback((lot: string, question: string) => {
    setOpenState(true)
    setLotId(lot)
    send(question, lot)
  }, [send])

  const retry = useCallback(() => {
    const msgs = messagesRef.current
    const last = msgs[msgs.length - 1]
    const q = msgs[msgs.length - 2]
    if (!last?.error || q?.role !== 'user') return
    setMessages(msgs.slice(0, -2))
    messagesRef.current = msgs.slice(0, -2)
    send(q.text, q.lotId ?? null)
  }, [send])

  const cancel = useCallback(() => {
    inflight.current?.abort()
    inflight.current = null
    setPending(false)
    setMessages((m) => (m[m.length - 1]?.role === 'user' ? m.slice(0, -1) : m))
  }, [])

  const clear = useCallback(() => {
    inflight.current?.abort()
    inflight.current = null
    setPending(false)
    setMessages([])
    setLotId(null)
  }, [])

  const value = useMemo(
    () => ({ open, setOpen, toggle, messages, pending, page, lotId, setLotId, ask, askAbout, retry, cancel, clear }),
    [open, setOpen, toggle, messages, pending, page, lotId, ask, askAbout, retry, cancel, clear],
  )
  return <AgentContext.Provider value={value}>{children}</AgentContext.Provider>
}

export function useAgent() {
  const ctx = useContext(AgentContext)
  if (!ctx) throw new Error('useAgent must be used inside <AgentProvider>')
  return ctx
}
