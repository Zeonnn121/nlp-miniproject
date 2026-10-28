import { useEffect, useMemo, useState } from 'react'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { HistoryIcon, RefreshIcon } from '../components/icons'
import { getDeviceService } from '../devices/service'
import type { Device } from '../devices/types'
import { getMonitoringHistoryService } from '../history/service'
import { HistoryServiceError, type HistoricalMonitoringRecord } from '../history/types'

function formatTimestamp(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function LatencyChart({ records }: { records: HistoricalMonitoringRecord[] }) {
  const points = records.filter((record) => record.latencyMs !== null).slice(-40)
  if (points.length < 2) return <div className="rounded-xl border border-dashed border-[#1e2a45] p-6 text-sm text-[#8b9dc0]">Not enough historical latency measurements to draw a chart.</div>
  const max = Math.max(...points.map((point) => point.latencyMs ?? 0), 1)
  const plotted = points.map((point, index) => ({ x: 24 + index * (252 / Math.max(points.length - 1, 1)), y: 178 - ((point.latencyMs ?? 0) / max) * 140 }))
  return <div className="overflow-x-auto rounded-xl border border-[#1e2a45] p-3" style={{ background: '#030407' }}><svg viewBox="0 0 300 210" className="h-56 min-w-[520px] w-full" role="img" aria-label="Historical latency chart"><line x1="24" y1="178" x2="276" y2="178" stroke="#1e2a45" /><polyline points={plotted.map((point) => `${point.x},${point.y}`).join(' ')} fill="none" stroke="#1558c9" strokeWidth="3" />{plotted.map((point) => <circle key={`${point.x}-${point.y}`} cx={point.x} cy={point.y} r="3.5" fill="#d4ff24" />)}</svg></div>
}

export function MonitoringHistoryPage() {
  const [devices, setDevices] = useState<Device[]>([])
  const [records, setRecords] = useState<HistoricalMonitoringRecord[]>([])
  const [deviceId, setDeviceId] = useState('all')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true); setError('')
    try {
      const [deviceList, result] = await Promise.all([getDeviceService().list(), getMonitoringHistoryService().list()])
      setDevices(deviceList); setRecords(result.records)
    } catch (reason: unknown) {
      setError(reason instanceof HistoryServiceError ? reason.message : 'Unable to load monitoring history.')
    } finally { setLoading(false) }
  }

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      setError('')
      try {
        const [deviceList, result] = await Promise.all([getDeviceService().list(), getMonitoringHistoryService().list()])
        if (!cancelled) { setDevices(deviceList); setRecords(result.records) }
      } catch (reason: unknown) {
        if (!cancelled) setError(reason instanceof HistoryServiceError ? reason.message : 'Unable to load monitoring history.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void run()
    return () => { cancelled = true }
  }, [])

  const filtered = useMemo(() => records.filter((record) => {
    const timestamp = new Date(record.timestamp).getTime()
    const afterFrom = !from || timestamp >= new Date(from).getTime()
    const beforeTo = !to || timestamp <= new Date(to).getTime()
    return (deviceId === 'all' || record.deviceId === deviceId) && afterFrom && beforeTo
  }), [records, deviceId, from, to])

  const inputClass = 'mt-2 block w-full rounded-xl border border-[#1e2a45] px-3 py-2.5 text-sm text-[#8b9dc0] outline-none focus:border-[#1558c9]'
  const inputStyle = { background: '#030407' }

  if (loading) return <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8"><LoadingState /></div>
  if (error) return <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8"><ErrorState description={error} /></div>

  return <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 lg:py-10">
    <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-start md:justify-between"><div className="flex items-start gap-3"><HistoryIcon className="mt-1 size-7 text-[#1558c9]" /><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#4a5a80]">Historical monitoring</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-[#f0f4ff] sm:text-3xl">Monitoring History</h1><p className="mt-1 text-sm text-[#8b9dc0]">Review recorded latency, packet loss, and reachability measurements.</p></div></div><button type="button" onClick={() => void load()} className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#1e2a45] px-4 py-2.5 text-sm font-semibold text-[#8b9dc0] shadow-sm hover:bg-[#0f1424] hover:text-[#f0f4ff] transition-colors" style={{ background: '#0a0d16' }}><RefreshIcon className="size-4" />Refresh</button></div>
    {import.meta.env.VITE_MONITORING_ADAPTER === 'mock' && <div className="mb-6 rounded-xl border border-[#3a3a1a] px-4 py-3 text-sm text-[#facc15]" style={{ background: '#1a1a0a' }}>Development monitoring adapter: historical records shown here reuse the existing monitoring fixture data for UI testing, not fabricated live history.</div>}
    <section className="mb-6 grid gap-4 rounded-2xl border border-[#1e2a45] p-5 shadow-sm md:grid-cols-3" style={{ background: '#0a0d16' }}><label className="text-sm font-medium text-[#8b9dc0]">Device<select value={deviceId} onChange={(event) => setDeviceId(event.target.value)} className={inputClass} style={inputStyle}><option value="all">All devices</option>{devices.map((device) => <option key={device.id} value={device.id}>{device.name}</option>)}</select></label><label className="text-sm font-medium text-[#8b9dc0]">From<input type="datetime-local" value={from} onChange={(event) => setFrom(event.target.value)} className={inputClass} style={inputStyle} /></label><label className="text-sm font-medium text-[#8b9dc0]">To<input type="datetime-local" value={to} onChange={(event) => setTo(event.target.value)} className={inputClass} style={inputStyle} /></label></section>
    {filtered.length === 0 ? <div className="rounded-2xl border border-dashed border-[#1e2a45] p-10 text-center text-sm text-[#8b9dc0]" style={{ background: '#0a0d16' }}>No historical monitoring records match the selected filters.</div> : <><section className="mb-6 rounded-2xl border border-[#1e2a45] p-5 shadow-sm" style={{ background: '#0a0d16' }}><div className="mb-4"><p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#4a5a80]">Trend</p><h2 className="mt-1 text-lg font-semibold text-[#f0f4ff]">Latency over time</h2></div><LatencyChart records={filtered} /></section><section className="overflow-hidden rounded-2xl border border-[#1e2a45] shadow-sm" style={{ background: '#0a0d16' }}><div className="overflow-x-auto"><table className="min-w-[720px] w-full text-left text-sm"><thead className="border-b border-[#1e2a45]" style={{ background: '#0f1424' }}><tr><th className="px-5 py-3 font-semibold text-[#4a5a80]">Timestamp</th><th className="px-5 py-3 font-semibold text-[#4a5a80]">Device</th><th className="px-5 py-3 font-semibold text-[#4a5a80]">Latency</th><th className="px-5 py-3 font-semibold text-[#4a5a80]">Packet loss</th><th className="px-5 py-3 font-semibold text-[#4a5a80]">Reachability</th></tr></thead><tbody className="divide-y divide-[#1e2a45]">{filtered.slice().sort((a, b) => b.timestamp.localeCompare(a.timestamp)).map((record) => <tr key={record.id} className="hover:bg-[#0f1424] transition-colors"><td className="px-5 py-4 whitespace-nowrap text-[#8b9dc0]">{formatTimestamp(record.timestamp)}</td><td className="px-5 py-4 font-medium text-[#f0f4ff]">{record.deviceName}</td><td className="px-5 py-4 text-[#8b9dc0]">{record.latencyMs === null ? 'Not available' : `${record.latencyMs} ms`}</td><td className="px-5 py-4 text-[#8b9dc0]">{record.packetLossPercent === null ? 'Not available' : `${record.packetLossPercent}%`}</td><td className="px-5 py-4 text-[#8b9dc0]">{record.reachable === null ? 'Not available' : record.reachable ? 'Reachable' : 'Unreachable'}</td></tr>)}</tbody></table></div></section></>}
  </div>
}
