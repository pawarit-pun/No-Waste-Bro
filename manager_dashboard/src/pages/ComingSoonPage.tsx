export function ComingSoonPage({ title }: { title: string }) {
  return (
    <div className="px-8 py-7">
      <h1 className="text-3xl font-bold tracking-tight text-slate-900">{title}</h1>
      <div className="mt-6 rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center text-slate-500">
        This page is coming next.
      </div>
    </div>
  )
}
