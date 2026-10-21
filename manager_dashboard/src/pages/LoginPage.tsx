import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { LogoMark, Logo } from '../components/Logo'
import { StaffAvatar } from '../components/StaffAvatar'
import { ApiError, apiGet } from '../lib/api'
import { STORE_LABEL, staffSubtitle } from '../lib/labels'
import { useSession } from '../lib/session'
import type { Staff } from '../types/staff'

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; managers: Staff[] }

/** หน้า "Who's on shift?" เลือกชื่อผู้จัดการแล้วเข้า dashboard (ไม่มี login จริง) */
export function LoginPage() {
  const { select } = useSession()
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [reloadKey, setReloadKey] = useState(0)
  const retry = useCallback(() => setReloadKey((k) => k + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    setState({ status: 'loading' })
    apiGet<Staff[]>('/staff?role=MANAGER', { signal: controller.signal })
      .then((managers) => setState({ status: 'ready', managers }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setState({ status: 'error', message: err instanceof ApiError ? err.message : 'Could not load managers.' })
      })
    return () => controller.abort()
  }, [reloadKey])

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      {/* ฝั่งซ้าย: แบรนด์ */}
      <aside className="hidden flex-col bg-gradient-to-br from-brand to-brand-dark px-16 py-10 lg:flex">
        <Logo tone="onBrand" />
        <div className="flex flex-1 flex-col justify-center">
          <h1 className="max-w-lg text-5xl font-bold leading-[1.05] tracking-tight text-white">
            Every lot checked. Every decision on record.
          </h1>
          <p className="mt-6 max-w-md text-lg leading-relaxed text-white/85">
            Review the agent's plans, track recovery, and audit every run from scan to staff task.
          </p>
        </div>
      </aside>

      {/* ฝั่งขวา: เลือกผู้จัดการ */}
      <main className="relative flex items-center bg-white justify-center overflow-hidden px-4 py-12 sm:px-8">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -top-[170px] -right-[150px] size-[480px] rounded-full"
          style={{
            background:
              'radial-gradient(circle, rgb(232 98 44 / 0.9) 0%, rgb(244 169 127 / 0.5) 45%, rgb(255 255 255 / 0) 100%)',
          }}
        />

        <div className="relative w-full max-w-[420px]">
          <div className="mb-10 lg:hidden">
            <div className="flex items-center gap-3">
              <LogoMark className="size-9" />
              <span className="text-lg font-bold">No Waste Bro</span>
            </div>
          </div>

          <h2 className="text-4xl font-extrabold tracking-tight">Who's on shift?</h2>
          <p className="mt-3 text-[15px] leading-snug text-slate-500">
            Tap your name to open the dashboard.
            <br />
            {STORE_LABEL}
          </p>

          <p className="mt-11 mb-3 text-[13px] font-semibold tracking-wide text-brand">MANAGERS</p>
          <div className="overflow-hidden rounded-3xl bg-white shadow-sm ring-1 ring-brand-tint">
            {state.status === 'loading' && <ListSkeleton />}

            {state.status === 'error' && (
              <CardMessage message={state.message}>
                <button
                  type="button"
                  onClick={retry}
                  className="mt-3 rounded-lg border border-brand px-4 py-1.5 text-sm font-medium text-brand hover:bg-orange-50"
                >
                  Try again
                </button>
              </CardMessage>
            )}

            {state.status === 'ready' && state.managers.length === 0 && (
              <CardMessage message="No managers on this shift yet." />
            )}

            {state.status === 'ready' &&
              state.managers.map((m, i) => (
                <button
                  key={m.staff_id}
                  type="button"
                  onClick={() => select(m)}
                  className="group relative flex w-full items-center gap-4 px-5 py-4 text-left transition-colors hover:bg-orange-50 focus-visible:bg-orange-50 focus-visible:outline-none"
                >
                  {i > 0 && <span className="absolute top-0 right-0 left-[92px] h-px bg-brand-tint" />}
                  <StaffAvatar name={m.full_name} imageUrl={m.image_url} size={56} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-lg font-bold">{m.full_name}</span>
                    <span className="block truncate text-[15px] text-slate-500">
                      {staffSubtitle(m.responsible_categories, m.role)}
                    </span>
                  </span>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"
                    className="size-5 text-brand transition-transform group-hover:translate-x-0.5">
                    <path d="m9 18 6-6-6-6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              ))}
          </div>
        </div>
      </main>
    </div>
  )
}

function ListSkeleton() {
  return (
    <div className="flex animate-pulse items-center gap-4 px-5 py-4">
      <div className="size-14 rounded-full bg-slate-200" />
      <div className="flex-1 space-y-2">
        <div className="h-4 w-40 rounded bg-slate-200" />
        <div className="h-3 w-24 rounded bg-slate-200" />
      </div>
    </div>
  )
}

function CardMessage({ message, children }: { message: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center p-6 text-center">
      <p className="text-slate-500">{message}</p>
      {children}
    </div>
  )
}
