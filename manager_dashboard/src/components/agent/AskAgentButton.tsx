import { SparklesIcon } from '../ui/icons'
import { useAgent } from './AgentProvider'

/** ปุ่ม "ถาม AI": เปิดแผงแชทแล้วถามทันที (มี lotId = คุยเรื่อง lot นั้น, ไม่มี = คำถามทั่วไป เช่น เรื่องครัว) */
export function AskAgentButton({ lotId, question, label = 'ถาม AI', compact = false }: {
  lotId?: string
  question: string
  label?: string
  compact?: boolean
}) {
  const { askAbout, ask, setOpen, pending } = useAgent()
  return (
    <button
      type="button"
      disabled={pending}
      onClick={(e) => {
        e.stopPropagation()
        if (lotId) askAbout(lotId, question)
        else {
          setOpen(true)
          ask(question, null)
        }
      }}
      title={`${label}: ${question}`}
      className={`inline-flex items-center gap-1 rounded-md font-semibold text-brand hover:bg-orange-50 disabled:cursor-wait disabled:opacity-50 ${
        compact ? 'px-1.5 py-0.5 text-[11px]' : 'border border-orange-200 px-2.5 py-1 text-[13px]'
      }`}
    >
      <SparklesIcon className={compact ? 'size-3' : 'size-3.5'} />
      {label}
    </button>
  )
}
