import mascot from '../assets/logo-mascot.png'

/** โลโก้มาสคอตถังขยะ No Waste Bro ในกรอบขาวมุมมน: variant "inverse" = วางบนพื้นส้ม, "brand" = วางบนพื้นขาว (มีเส้นขอบ) */
export function LogoMark({ className = 'size-10', variant = 'brand' }: { className?: string; variant?: 'brand' | 'inverse' }) {
  const frame = variant === 'inverse' ? 'bg-white' : 'bg-white ring-1 ring-slate-200'
  return (
    <div className={`flex shrink-0 items-center justify-center overflow-hidden rounded-xl ${frame} ${className}`}>
      <img src={mascot} alt="No Waste Bro" className="size-full object-contain" draggable={false} />
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
