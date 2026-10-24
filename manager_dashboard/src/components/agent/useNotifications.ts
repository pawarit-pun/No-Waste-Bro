import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage } from '../../lib/api'
import { listNotifications } from '../../lib/agent'
import { useTableChanges } from '../../lib/supabase'
import type { NotificationList } from '../../types/agent'

/** แจ้งเตือนของ agent: โหลดครั้งแรก + โหลดใหม่เมื่อตาราง agent_notifications / agent_proposals เปลี่ยน (Realtime)
 *  และทุก 60 วินาทีเผื่อ Realtime ไม่ได้ตั้งค่า */
export function useNotifications(limit = 30) {
  const [data, setData] = useState<NotificationList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const latest = useRef(0)

  const reload = useCallback(async () => {
    const ticket = ++latest.current
    try {
      const res = await listNotifications(limit)
      if (ticket === latest.current) {
        setData(res)
        setError(null)
      }
    } catch (err) {
      if (ticket === latest.current) setError(errorMessage(err, 'โหลดแจ้งเตือนไม่ได้'))
    }
  }, [limit])

  useEffect(() => {
    void reload()
    const t = setInterval(() => void reload(), 60_000)
    return () => clearInterval(t)
  }, [reload])
  useTableChanges('agent_notifications', () => void reload())
  useTableChanges('agent_proposals', () => void reload())

  return { data, error, reload }
}
