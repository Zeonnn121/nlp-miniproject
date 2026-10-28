import type { DeviceStatus } from '../dashboard/types'

interface StatusBadgeProps {
  status: DeviceStatus
}

const config: Record<DeviceStatus, { label: string; symbol: string; classes: string }> = {
  online: { label: 'Online', symbol: '✓', classes: 'border-[#1a3a1a] bg-[#0a1f0a] text-[#4ade80]' },
  offline: { label: 'Offline', symbol: '×', classes: 'border-[#3a1a1a] bg-[#1f0a0a] text-[#f87171]' },
  unknown: { label: 'Unknown', symbol: '?', classes: 'border-[#1e2a45] bg-[#0a0d16] text-[#4a5a80]' },
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const item = config[status]
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${item.classes}`}>
      <span aria-hidden="true" className="font-bold">{item.symbol}</span>
      <span>{item.label}</span>
    </span>
  )
}
