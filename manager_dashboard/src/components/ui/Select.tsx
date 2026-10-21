import type { SelectHTMLAttributes } from 'react'

/** select ที่มีป้ายนำหน้าในกรอบเดียว เช่น "Severity  All" */
export function Select({ label, className = '', children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  return (
    <label className={`flex h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white pl-3 pr-2 text-sm focus-within:border-brand ${className}`}>
      <span className="text-slate-500">{label}</span>
      <select className="cursor-pointer bg-transparent pr-1 font-semibold text-slate-900 outline-none" {...props}>
        {children}
      </select>
    </label>
  )
}
