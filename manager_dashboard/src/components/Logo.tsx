/** โลโก้ใบไม้ในกรอบ: variant "brand" = กรอบส้มใบไม้ขาว, "inverse" = กรอบขาวใบไม้ส้ม (ใช้บนพื้นส้ม) */
export function LogoMark({ className = 'size-10', variant = 'brand' }: { className?: string; variant?: 'brand' | 'inverse' }) {
  const colors = variant === 'inverse' ? 'bg-white text-brand' : 'bg-brand text-white'
  return (
    <div className={`flex shrink-0 items-center justify-center rounded-xl ${colors} ${className}`}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"
        strokeLinejoin="round" className="size-1/2" aria-hidden="true">
        <path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10Z" />
        <path d="M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12" />
      </svg>
    </div>
  )
}

/** โลโก้ + ชื่อระบบ: tone "onBrand" = วางบนพื้นส้ม, "onLight" = วางบนพื้นขาว */
export function Logo({ tone = 'onBrand' }: { tone?: 'onBrand' | 'onLight' }) {
  const onBrand = tone === 'onBrand'
  return (
    <div className="flex items-center gap-3">
      <LogoMark variant={onBrand ? 'inverse' : 'brand'} />
      <div className="leading-tight">
        <p className={`text-lg font-bold ${onBrand ? 'text-white' : 'text-slate-900'}`}>No Waste Bro</p>
        <p className={`text-sm ${onBrand ? 'text-white/75' : 'text-slate-500'}`}>Food-loss control console</p>
      </div>
    </div>
  )
}
