import type { FaultSeverity } from '../dashboard/types'

interface FaultSeverityBadgeProps {
  severity: FaultSeverity
}

const config: Record<FaultSeverity, { label: string; symbol: string; classes: string }> = {
  critical: { label: 'Critical', symbol: '!', classes: 'border-[#3a1a1a] bg-[#1f0a0a] text-[#f87171]' },
  high: { label: 'High', symbol: '↑', classes: 'border-[#3a2a1a] bg-[#1f1a0a] text-[#fb923c]' },
  medium: { label: 'Medium', symbol: '•', classes: 'border-[#3a3a1a] bg-[#1f1f0a] text-[#facc15]' },
  low: { label: 'Low', symbol: '↓', classes: 'border-[#1e2a45] bg-[#0a0d16] text-[#4a5a80]' },
}

export function FaultSeverityBadge({ severity }: FaultSeverityBadgeProps) {
  const item = config[severity]
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${item.classes}`}>
      <span aria-hidden="true" className="font-bold">{item.symbol}</span>
      <span>{item.label}</span>
    </span>
  )
}
