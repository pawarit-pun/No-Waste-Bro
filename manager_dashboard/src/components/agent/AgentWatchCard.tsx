import { useState } from 'react'
import { Link } from 'react-router-dom'
import { runDailyReport, watchNow } from '../../lib/agent'
import { errorMessage } from '../../lib/api'
import { formatWhen } from '../../lib/format'
import { Button } from '../ui/Button'
import { SearchCheckIcon } from '../ui/icons'
import { useNotifications } from './useNotifications'

const DOT = { CRITICAL: 'bg-red-500', WARNING: 'bg-orange-400', INFO: 'bg-slate-300' } as const

/** การ์ดในหน้า Run demo: สั่ง Manager Agent ตรวจงานค้างตอนนี้ + แสดงแจ้งเตือนล่าสุด */
export function AgentWatchCard() {
  const { data } = useNotifications(5)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null)

  const daily = async (kind: 'morning' | 'evening') => {
    setBusy(true)
    setNote(null)
    try {
      const r = await runDailyReport(kind)
      setNote(r.started
        ? { ok: true, text: `${kind === 'morning' ? 'Morning brief' : 'Evening summary'} started. It appears on the Overview page and in the bell in 5-20 seconds.` }
        : { ok: false, text: 'The Manager Agent is not configured on this server (AGENT_FUNCTION_NAME is empty).' })
    } catch (err) {
      setNote({ ok: false, text: errorMessage(err, 'Could not start the report.') })
    } finally {
      setBusy(false)
    }
  }

  const check = async () => {
    setBusy(true)
    setNote(null)
    try {
      const r = await watchNow()
      setNote(r.started
        ? { ok: true, text: 'Check started. New notifications appear below and in the bell within a few seconds.' }
        : { ok: false, text: 'The Manager Agent is not configured on this server (AGENT_FUNCTION_NAME is empty).' })
    } catch (err) {
      setNote({ ok: false, text: errorMessage(err, 'Could not start the check.') })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white">
      <h2 className="border-b border-slate-200 px-5 py-3.5 font-semibold text-slate-900">Manager Agent</h2>
      <div className="px-5 py-4">
        <p className="text-sm text-slate-600">
          Looks for overdue tasks, plans close to or past their review deadline, and lots stuck in PROCESSING.
          It also runs by itself every hour from 07:00 to 22:00, and right away when a task is rejected, a kitchen is full
          or a pipeline run fails. Things already reported are not reported again.
        </p>
        <Button className="mt-3 w-full" disabled={busy} onClick={() => void check()}>
          <SearchCheckIcon className="size-4" />
          {busy ? 'Starting…' : 'Check now'}
        </Button>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <Button size="sm" disabled={busy} onClick={() => void daily('morning')}>Morning brief now</Button>
          <Button size="sm" disabled={busy} onClick={() => void daily('evening')}>Evening summary now</Button>
        </div>
        <p className="mt-1.5 text-xs text-slate-500">
          Morning brief summarizes the latest successful pipeline run (it also runs by itself when a run finishes, and the agent
          starts the run at 07:30). Evening summary counts what staff really did today (also at 21:30). Results: <Link to="/overview" className="font-semibold text-brand hover:underline">Overview</Link>.
        </p>
        {note && <p className={`mt-2 text-sm ${note.ok ? 'text-slate-600' : 'text-red-600'}`}>{note.text}</p>}

        {data && data.items.length > 0 && (
          <ul className="mt-4 divide-y divide-slate-100 rounded-xl border border-slate-200">
            {data.items.map((n) => (
              <li key={n.notification_id} className="flex items-start gap-2.5 px-3.5 py-2.5">
                <span className={`mt-1.5 size-2 shrink-0 rounded-full ${DOT[n.severity]}`} />
                <div className="min-w-0 flex-1">
                  <p className="flex justify-between gap-2 text-sm">
                    <span className="font-semibold text-slate-900">{n.title}</span>
                    <span className="shrink-0 text-[11px] text-slate-400">{formatWhen(n.created_at)}</span>
                  </p>
                  <p className="text-[13px] text-slate-600">{n.message}</p>
                  {n.proposal?.status === 'PROPOSED' && (
                    <p className="mt-0.5 text-[12px] font-semibold text-brand">Has a proposal: open the bell to confirm</p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
