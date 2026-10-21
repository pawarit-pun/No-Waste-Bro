export interface TabItem<T extends string> {
  id: T
  label: string
  count?: number
}

export function Tabs<T extends string>({ items, value, onChange }: { items: TabItem<T>[]; value: T; onChange: (id: T) => void }) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-slate-200">
      {items.map((t) => {
        const active = t.id === value
        return (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => onChange(t.id)}
            className={`-mb-px border-b-2 px-3.5 py-2.5 text-[15px] font-semibold transition-colors ${
              active ? 'border-brand text-slate-900' : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            {t.label}
            {t.count != null && <span className={`ml-1.5 ${active ? 'text-brand' : 'text-slate-400'}`}>{t.count}</span>}
          </button>
        )
      })}
    </div>
  )
}
