import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import type { Staff } from '../types/staff'

// ไม่มี login จริง: เลือกชื่อผู้จัดการแล้วเข้าได้เลย และจำไว้ใน localStorage (refresh แล้วไม่หลุด)
const STORAGE_KEY = 'nwb.manager'

function readStored(): Staff | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Staff) : null
  } catch {
    return null
  }
}

function writeStored(staff: Staff | null) {
  try {
    if (staff) localStorage.setItem(STORAGE_KEY, JSON.stringify(staff))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // storage ใช้ไม่ได้ (private mode) → จำแค่ในหน่วยความจำ
  }
}

interface SessionValue {
  manager: Staff | null
  select: (staff: Staff) => void
  clear: () => void
}

const SessionContext = createContext<SessionValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [manager, setManager] = useState<Staff | null>(readStored)

  const select = useCallback((staff: Staff) => {
    writeStored(staff)
    setManager(staff)
  }, [])

  const clear = useCallback(() => {
    writeStored(null)
    setManager(null)
  }, [])

  const value = useMemo(() => ({ manager, select, clear }), [manager, select, clear])
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession() {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession must be used inside <SessionProvider>')
  return ctx
}
