import { useEffect, useMemo, useState } from 'react'
import { AlertTriangleIcon, HistoryIcon, RefreshIcon } from '../components/icons'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { getDeviceService } from '../devices/service'
import type { Device } from '../devices/types'
import { getFaultHistoryService } from '../history/service'
import { HistoryServiceError } from '../history/types'
import type { FaultEvent, FaultSeverity, FaultStatus, FaultType } from '../faults/types'

const severities: FaultSeverity[] = ['critical', 'high', 'medium', 'low']
const statuses: FaultStatus[] = ['active', 'acknowledged', 'resolved']
const faultTypes: FaultType[] = ['DEVICE_UNREACHABLE', 'HIGH_LATENCY', 'HIGH_PACKET_LOSS', 'HIGH_CPU_USAGE', 'HIGH_MEMORY_USAGE', 'INTERFACE_FAILURE', 'CONNECTIVITY_FAILURE']

function formatFaultType(value: FaultType) { return value.replaceAll('_', ' ').toLowerCase().replace(/\b\w/g, (character) => character.toUpperCase()) }
function formatTimestamp(value: string) { return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) }

function SeverityBadge({ value }: { value: FaultSeverity }) {
  const symbol = value === 'critical' ? '!!' : value === 'high' ? '!' : value === 'medium' ? '•' : '·'
  const colors: Record<FaultSeverity, string> = {
    critical: 'border-[#3a1a1a] text-[#f87171]',
    high: 'border-[#3a2a1a] text-[#fb923c]',
    medium: 'border-[#3a3a1a] text-[#facc15]',
    low: 'border-[#1e2a45] text-[#4a5a80]',
  }
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold capitalize ${colors[value]}`}><span aria-hidden="true">{symbol}</span>{value}</span>
}

function StatusBadge({ value }: { value: FaultStatus }) {
  const symbol = value === 'resolved' ? '✓' : value === 'acknowledged' ? '◷' : '!'
  const colors: Record<FaultStatus, string> = {
    active: 'border-[#3a1a1a] text-[#f87171]',
    acknowledged: 'border-[#3a3a1a] text-[#facc15]',
    resolved: 'border-[#1a3a1a] text-[#4ade80]',
  }
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold capitalize ${colors[value]}`}><span aria-hidden="true">{symbol}</span>{value}</span>
}

export function FaultHistoryPage() {
  const [devices, setDevices] = useState<Device[]>([])
  const [faults, setFaults] = useState<FaultEvent[]>([])
  const [deviceId, setDeviceId] = useState('all'); const [severity, setSeverity] = useState<FaultSeverity | 'all'>('all'); const [status, setStatus] = useState<FaultStatus | 'all'>('all'); const [faultType, setFaultType] = useState<FaultType | 'all'>('all'); const [from, setFrom] = useState(''); const [to, setTo] = useState('')
  const [loading, setLoading] = useState(true); const [error, setError] = useState('')

  const load = async () => { setLoading(true); setError(''); try { const [deviceList, result] = await Promise.all([getDeviceService().list(), getFaultHistoryService().list()]); setDevices(deviceList); setFaults(result.faults) } catch (reason: unknown) { setError(reason instanceof HistoryServiceError ? reason.message : 'Unable to load fault history.') } finally { setLoading(false) } }

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      setError('')
      try {
        const [deviceList, result] = await Promise.all([getDeviceService().list(), getFaultHistoryService().list()])
        if (!cancelled) { setDevices(deviceList); setFaults(result.faults) }
      } catch (reason: unknown) {
        if (!cancelled) setError(reason instanceof HistoryServiceError ? reason.message : 'Unable to load fault history.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void run()
    return () => { cancelled = true }
  }, [])

  const filtered = useMemo(() => faults.filter((fault) => { const timestamp = new Date(fault.detectedAt).getTime(); const afterFrom = !from || timestamp >= new Date(from).getTime(); const beforeTo = !to || timestamp <= new Date(to).getTime(); return (deviceId === 'all' || fault.deviceId === deviceId) && (severity === 'all' || fault.severity === severity) && (status === 'all' || fault.status === status) && (faultType === 'all' || fault.faultType === faultType) && afterFrom && beforeTo }), [faults, deviceId, severity, status, faultType, from, to])

  const selectClass = 'mt-2 block w-full rounded-xl border border-[#1e2a45] px-3 py-2.5 text-sm text-[#8b9dc0] outline-none focus:border-[#1558c9]'
  const selectStyle = { background: '#030407' }

  if (loading) return <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8"><LoadingState /></div>
  if (error) return <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8"><ErrorState description={error} /></div>
  return <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 lg:py-10">
    <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-start md:justify-between"><div className="flex items-start gap-3"><HistoryIcon className="mt-1 size-7 text-[#1558c9]" /><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#4a5a80]">Historical faults</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-[#f0f4ff] sm:text-3xl">Fault History</h1><p className="mt-1 text-sm text-[#8b9dc0]">Review detected faults separately from the current active-fault view.</p></div></div><button type="button" onClick={() => void load()} className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#1e2a45] px-4 py-2.5 text-sm font-semibold text-[#8b9dc0] shadow-sm hover:bg-[#0f1424] hover:text-[#f0f4ff] transition-colors" style={{ background: '#0a0d16' }}><RefreshIcon className="size-4" />Refresh</button></div>
    {import.meta.env.VITE_FAULTS_ADAPTER === 'mock' && <div className="mb-6 rounded-xl border border-[#3a3a1a] px-4 py-3 text-sm text-[#facc15]" style={{ background: '#1a1a0a' }}>Development fault adapter: historical events shown here reuse the existing fault fixtures for UI testing, not fabricated live faults.</div>}
    <section className="mb-6 grid gap-4 rounded-2xl border border-[#1e2a45] p-5 shadow-sm md:grid-cols-3 xl:grid-cols-6" style={{ background: '#0a0d16' }}><label className="text-sm font-medium text-[#8b9dc0]">Device<select value={deviceId} onChange={(event) => setDeviceId(event.target.value)} className={selectClass} style={selectStyle}><option value="all">All devices</option>{devices.map((device) => <option key={device.id} value={device.id}>{device.name}</option>)}</select></label><label className="text-sm font-medium text-[#8b9dc0]">Severity<select value={severity} onChange={(event) => setSeverity(event.target.value as FaultSeverity | 'all')} className={selectClass} style={selectStyle}><option value="all">All</option>{severities.map((value) => <option key={value} value={value}>{value}</option>)}</select></label><label className="text-sm font-medium text-[#8b9dc0]">Status<select value={status} onChange={(event) => setStatus(event.target.value as FaultStatus | 'all')} className={selectClass} style={selectStyle}><option value="all">All</option>{statuses.map((value) => <option key={value} value={value}>{value}</option>)}</select></label><label className="text-sm font-medium text-[#8b9dc0]">Fault type<select value={faultType} onChange={(event) => setFaultType(event.target.value as FaultType | 'all')} className={selectClass} style={selectStyle}><option value="all">All</option>{faultTypes.map((value) => <option key={value} value={value}>{formatFaultType(value)}</option>)}</select></label><label className="text-sm font-medium text-[#8b9dc0]">From<input type="datetime-local" value={from} onChange={(event) => setFrom(event.target.value)} className={selectClass} style={selectStyle} /></label><label className="text-sm font-medium text-[#8b9dc0]">To<input type="datetime-local" value={to} onChange={(event) => setTo(event.target.value)} className={selectClass} style={selectStyle} /></label></section>
    {filtered.length === 0 ? <div className="rounded-2xl border border-dashed border-[#1e2a45] p-10 text-center text-sm text-[#8b9dc0]" style={{ background: '#0a0d16' }}>No fault history records match the selected filters.</div> : <section className="overflow-hidden rounded-2xl border border-[#1e2a45] shadow-sm" style={{ background: '#0a0d16' }}><div className="overflow-x-auto"><table className="min-w-[980px] w-full text-left text-sm"><thead className="border-b border-[#1e2a45]" style={{ background: '#0f1424' }}><tr><th className="px-5 py-3 font-semibold text-[#4a5a80]">Detected</th><th className="px-5 py-3 font-semibold text-[#4a5a80]">Device</th><th className="px-5 py-3 font-semibold text-[#4a5a80]">Fault type</th><th className="px-5 py-3 font-semibold text-[#4a5a80]">Severity</th><th className="px-5 py-3 font-semibold text-[#4a5a80]">Status</th><th className="px-5 py-3 font-semibold text-[#4a5a80]">Resolution</th></tr></thead><tbody className="divide-y divide-[#1e2a45]">{filtered.slice().sort((a, b) => b.detectedAt.localeCompare(a.detectedAt)).map((fault) => <tr key={fault.id} className="hover:bg-[#0f1424] transition-colors"><td className="px-5 py-4 whitespace-nowrap text-[#8b9dc0]">{formatTimestamp(fault.detectedAt)}</td><td className="px-5 py-4 font-medium text-[#f0f4ff]">{fault.deviceName}</td><td className="px-5 py-4"><span className="inline-flex items-center gap-2 text-[#8b9dc0]"><AlertTriangleIcon className="size-4 text-[#4a5a80]" />{formatFaultType(fault.faultType)}</span></td><td className="px-5 py-4"><SeverityBadge value={fault.severity} /></td><td className="px-5 py-4"><StatusBadge value={fault.status} /></td><td className="px-5 py-4 text-[#8b9dc0]">{fault.resolvedAt ? formatTimestamp(fault.resolvedAt) : fault.status === 'resolved' ? 'Resolved, time unavailable' : 'Not resolved'}</td></tr>)}</tbody></table></div></section>}
  </div>
}
