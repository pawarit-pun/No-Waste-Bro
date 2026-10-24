import type {
  AgentAnswer, AgentContext, AgentProposal, AgentTurn, AutoApproveParams, AutoApprovePolicy, NotificationList, UndoAutoResult,
} from '../types/agent'
import { ApiError, apiGet, apiPost, apiPut } from './api'

// agent ตอบภายใน ~25 วินาที (API Gateway ตัดที่ 29) เผื่อเครือข่ายอีกนิด
const ASK_TIMEOUT_MS = 35_000

/** ถาม Manager Agent: POST /agent/ask (ยกเลิกได้ด้วย signal, หมดเวลา = ApiError 504) */
export async function askAgent(
  question: string,
  history: AgentTurn[],
  context: AgentContext,
  signal?: AbortSignal,
): Promise<AgentAnswer> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort('timeout'), ASK_TIMEOUT_MS)
  const onAbort = () => ctrl.abort('cancel')
  signal?.addEventListener('abort', onAbort)
  try {
    return await apiPost<AgentAnswer>('/agent/ask', { question, history, context }, { signal: ctrl.signal })
  } catch (err) {
    if (ctrl.signal.aborted && ctrl.signal.reason === 'timeout') throw new ApiError('timeout', 504)
    throw err
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', onAbort)
  }
}

/** ปลุก Lambda ของ agent ตอนเปิดแผงแชท (ไม่รอผล ล้มก็ไม่เป็นไร) */
export function warmUpAgent(): void {
  apiPost('/agent/warmup', {}).catch(() => undefined)
}

/** ข้อความ error ภาษาไทยสำหรับแผงแชท */
export function agentErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 504) return 'ผู้ช่วยตอบไม่ทันเวลา ลองถามใหม่อีกครั้ง หรือถามให้สั้นลง'
    if (err.status === 503) return 'ยังไม่ได้เปิดใช้ผู้ช่วย AI บน server นี้ (AGENT_FUNCTION_NAME ว่าง)'
    if (err.status === 0) return 'เชื่อมต่อ server ไม่ได้ ตรวจสอบอินเทอร์เน็ตแล้วลองใหม่'
    if (err.status === 422 || err.status === 400) return 'คำถามไม่ถูกรูปแบบ (ว่างหรือยาวเกิน 1,000 ตัวอักษร)'
    return `ผู้ช่วยทำงานไม่สำเร็จ (${err.status}) ลองใหม่อีกครั้ง`
  }
  return 'ผู้ช่วยทำงานไม่สำเร็จ ลองใหม่อีกครั้ง'
}

// ---------- Phase 2 ----------

export const listNotifications = (limit = 30) => apiGet<NotificationList>(`/agent/notifications?limit=${limit}`)
export const markNotificationRead = (id: string) => apiPost<{ updated: number }>(`/agent/notifications/${id}/read`, {})
export const markAllNotificationsRead = () => apiPost<{ updated: number }>('/agent/notifications/read-all', {})
export const executeProposal = (id: string, staffId: string) =>
  apiPost<AgentProposal>(`/agent/proposals/${id}/execute`, { staff_id: staffId })
export const dismissProposal = (id: string, staffId: string) =>
  apiPost<AgentProposal>(`/agent/proposals/${id}/dismiss`, { staff_id: staffId })
/** สั่ง agent ตรวจงานค้างตอนนี้ (ไม่รอผล แจ้งเตือนขึ้นในกระดิ่งภายในไม่กี่วินาที) */
export const watchNow = () => apiPost<{ started: boolean }>('/agent/watch', {})

// ---------- Phase 3 ----------

/** ทำรายงานประจำวันตอนนี้ (ไม่รอผล) morning = Morning brief ของ pipeline รอบล่าสุดที่สำเร็จ, evening = Evening summary */
export const runDailyReport = (kind: 'morning' | 'evening') => apiPost<{ started: boolean }>(`/agent/daily/${kind}`, {})

// ---------- Phase 4: Auto-approve ----------

export const getAutoApprovePolicy = () => apiGet<AutoApprovePolicy>('/agent/policies/auto-approve')
export const saveAutoApprovePolicy = (managerId: string, enabled: boolean, params: AutoApproveParams) =>
  apiPut<AutoApprovePolicy>('/agent/policies/auto-approve', { manager_id: managerId, enabled, params })
/** ย้อนการอนุมัติของ agent (ทั้งชุดของ lot นั้น) ภายใน undo_minutes ถ้า staff ยังไม่เริ่มงาน */
export const undoAutoApprove = (reviewId: string, staffId: string) =>
  apiPost<UndoAutoResult>(`/pending-tasks/${reviewId}/undo-auto`, { staff_id: staffId })
