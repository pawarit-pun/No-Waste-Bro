import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import { useEffect, useRef } from 'react'

// ใช้เฉพาะ Realtime และนับจำนวนแบบเบาๆ (anon อ่านได้แค่ pending_tasks, ai_recommended_tasks, pipeline_runs,
// agent_runs, agent_notifications, agent_proposals, daily_reports)
// ข้อมูลหลักทั้งหมดดึงผ่าน FastAPI
const url = import.meta.env.VITE_SUPABASE_URL
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

export const supabase: SupabaseClient | null = url && key ? createClient(url, key) : null

/** เรียก onChange เมื่อตารางมีการเปลี่ยนแปลง (ใช้ event เป็นแค่สัญญาณให้ดึงข้อมูลใหม่ หน่วง 400ms กันยิงถี่) */
export function useTableChanges(table: string, onChange: () => void) {
  const callback = useRef(onChange)
  useEffect(() => {
    callback.current = onChange
  })

  useEffect(() => {
    const client = supabase
    if (!client) return
    let timer: ReturnType<typeof setTimeout> | undefined
    const channel = client
      .channel(`${table}-${Math.random().toString(36).slice(2)}`)
      .on('postgres_changes', { event: '*', schema: 'public', table }, () => {
        clearTimeout(timer)
        timer = setTimeout(() => callback.current(), 400)
      })
      .subscribe()
    return () => {
      clearTimeout(timer)
      void client.removeChannel(channel)
    }
  }, [table])
}
