import type { DeviceStatus } from '../devices/types'

const labels: Record<DeviceStatus, string> = { online: 'Online', offline: 'Offline', unknown: 'Unknown' }

export function DeviceStatusBadge({ status }: { status: DeviceStatus }) {
  const styles: Record<DeviceStatus, string> = {
    online: 'border-[#1a3a1a] bg-[#0a1f0a] text-[#4ade80]',
    offline: 'border-[#3a1a1a] bg-[#1f0a0a] text-[#f87171]',
    unknown: 'border-[#1e2a45] bg-[#0a0d16] text-[#4a5a80]',
  }
  const symbols: Record<DeviceStatus, string> = { online: '✓', offline: '×', unknown: '?' }
  return <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${styles[status]}`}><span aria-hidden="true">{symbols[status]}</span>{labels[status]}</span>
}
