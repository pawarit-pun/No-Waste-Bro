import type { ButtonHTMLAttributes } from 'react'

type Variant = 'primary' | 'outline' | 'neutral' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-brand text-white hover:bg-[#d4551f] disabled:bg-brand/50',
  outline: 'border border-slate-300 bg-white text-slate-800 hover:border-brand hover:text-brand disabled:text-slate-400',
  neutral: 'border border-slate-900 bg-white text-slate-900 hover:bg-slate-900 hover:text-white disabled:border-slate-300 disabled:text-slate-400',
  ghost: 'text-slate-600 hover:bg-slate-100 disabled:text-slate-300',
  danger: 'border border-red-300 bg-white text-red-700 hover:bg-red-50 disabled:text-red-300',
}

const SIZES: Record<Size, string> = {
  sm: 'h-9 px-3.5 text-sm',
  md: 'h-10 px-4 text-sm',
}

export function Button({
  variant = 'outline',
  size = 'md',
  className = '',
  type = 'button',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...props}
    />
  )
}
