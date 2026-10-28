import { useEffect, useMemo, useState } from 'react'
import { ActivityIcon, AlertTriangleIcon, HistoryIcon, ServerIcon } from '../components/icons'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { FaultSeverityBadge } from '../components/FaultSeverityBadge'
import { LoadingState } from '../components/LoadingState'
import { StatCard } from '../components/StatCard'
import { StatusBadge } from '../components/StatusBadge'
import { DashboardError, type DashboardData, type DeviceHealthItem } from '../dashboard/types'
import { getDashboardData } from '../dashboard/service'

function DeviceHealthRow({ device }: { device: DeviceHealthItem }) {
  return (
    <li className="flex flex-col gap-3 border-b border-[#1e2a45] py-4 last:border-b-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="truncate text-sm font-semibold text-[#f0f4ff]">{device.name}</p>
          <StatusBadge status={device.status} />
        </div>
        <p className="mt-1 text-xs text-[#4a5a80]">{device.type} · {device.address}</p>
      </div>
      <div className="grid grid-cols-3 gap-4 text-right text-xs">
        <div><p className="text-[#4a5a80]">Availability</p><p className="mt-1 font-semibold text-[#8b9dc0]">{device.availability !== undefined ? `${device.availability}%` : '—'}</p></div>
        <div><p className="text-[#4a5a80]">Latency</p><p className="mt-1 font-semibold text-[#8b9dc0]">{device.latencyMs !== undefined ? `${device.latencyMs} ms` : '—'}</p></div>
        <div><p className="text-[#4a5a80]">Loss</p><p className="mt-1 font-semibold text-[#8b9dc0]">{device.packetLossPercent !== undefined ? `${device.packetLossPercent}%` : '—'}</p></div>
      </div>
    </li>
  )
}

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState<DashboardError | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let active = true
    getDashboardData()
      .then((result) => { if (active) setData(result) })
      .catch((reason: unknown) => {
        if (!active) return
        setError(reason instanceof DashboardError ? reason : new DashboardError('An unexpected dashboard error occurred.'))
      })
      .finally(() => { if (active) setIsLoading(false) })
    return () => { active = false }
  }, [])

  const healthCounts = useMemo(() => {
    const devices = data?.deviceHealth ?? []
    return {
      online: devices.filter((device) => device.status === 'online').length,
      offline: devices.filter((device) => device.status === 'offline').length,
      unknown: devices.filter((device) => device.status === 'unknown').length,
    }
  }, [data])

  const isPartial = Boolean(data && (
    data.deviceHealth.length < data.summary.totalDevices ||
    data.activeFaults.length < data.summary.activeFaults
  ))

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 lg:py-10">
      <section className="mb-8">
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#4a5a80]">Dashboard</p>
        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-[#f0f4ff] sm:text-3xl">Network overview</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[#8b9dc0]">Centralized visibility into device availability, network health, and active faults.</p>
          </div>
          <div className="inline-flex w-fit items-center gap-2 rounded-full border border-[#1e2a45] px-3 py-2 text-xs font-medium text-[#8b9dc0] shadow-sm" style={{ background: '#0a0d16' }}>
            <ActivityIcon className="size-3.5" /> Monitoring dashboard
          </div>
        </div>
      </section>

      {isLoading && <LoadingState />}
      {!isLoading && error && <ErrorState description={error.message} />}

      {!isLoading && !error && data && (
        <>
          {isPartial && (
            <div className="mb-5 rounded-xl border border-[#3a3a1a] px-4 py-3 text-sm text-[#facc15]" style={{ background: '#1a1a0a' }} role="status">
              <span className="font-semibold">Partial monitoring data.</span> Some device or fault records are not available yet; the dashboard is showing only the data returned by the current adapter.
            </div>
          )}

          <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Network summary">
            <StatCard label="Total Devices" value={data.summary.totalDevices} description="Devices configured for monitoring" icon={ServerIcon} />
            <StatCard label="Online" value={data.summary.onlineDevices} description="Devices currently reporting as reachable" icon={ActivityIcon} tone="positive" />
            <StatCard label="Offline" value={data.summary.offlineDevices} description="Devices currently reporting as unreachable" icon={ServerIcon} tone="danger" />
            <StatCard label="Active Faults" value={data.summary.activeFaults} description="Fault events requiring attention" icon={AlertTriangleIcon} tone="warning" />
          </section>

          <section className="mt-6 grid gap-6 xl:grid-cols-[1.45fr_1fr]">
            <article className="rounded-2xl border border-[#1e2a45] p-5 shadow-sm sm:p-6" style={{ background: '#0a0d16' }}>
              <div className="flex items-start justify-between gap-4">
                <div><h2 className="text-sm font-semibold text-[#f0f4ff]">Device health</h2><p className="mt-1 text-xs text-[#4a5a80]">Current availability and connectivity status.</p></div>
                <ServerIcon className="size-5 text-[#4a5a80]" />
              </div>
              {data.deviceHealth.length === 0 ? (
                <div className="mt-5"><EmptyState title="No device health data" description="No monitored device status records are available for this dashboard yet." icon={<ServerIcon className="size-5" />} /></div>
              ) : (
                <ul className="mt-3">{data.deviceHealth.map((device) => <DeviceHealthRow key={device.id} device={device} />)}</ul>
              )}
            </article>

            <article className="rounded-2xl border border-[#1e2a45] p-5 shadow-sm sm:p-6" style={{ background: '#0a0d16' }}>
              <div className="flex items-start justify-between gap-4">
                <div><h2 className="text-sm font-semibold text-[#f0f4ff]">Health status overview</h2><p className="mt-1 text-xs text-[#4a5a80]">Distribution of returned device states.</p></div>
                <ActivityIcon className="size-5 text-[#4a5a80]" />
              </div>
              {data.summary.totalDevices === 0 ? (
                <div className="mt-5"><EmptyState title="No monitored devices" description="Add devices through the device management workflow to begin monitoring network health." /></div>
              ) : (
                <div className="mt-6">
                  <div className="flex h-3 overflow-hidden rounded-full" style={{ background: '#1e2a45' }} aria-label="Device health distribution">
                    <div className="h-full" style={{ background: '#d4ff24', width: `${Math.min(100, (healthCounts.online / data.summary.totalDevices) * 100)}%` }} />
                    <div className="h-full bg-[#f87171]" style={{ width: `${Math.min(100, (healthCounts.offline / data.summary.totalDevices) * 100)}%` }} />
                  </div>
                  <div className="mt-5 space-y-3 text-sm">
                    <div className="flex items-center justify-between"><span className="flex items-center gap-2"><span className="grid size-5 place-items-center rounded-full text-xs font-bold text-[#030407]" style={{ background: '#d4ff24' }}>✓</span><span className="text-[#8b9dc0]">Online</span></span><strong className="text-[#f0f4ff]">{data.summary.onlineDevices}</strong></div>
                    <div className="flex items-center justify-between"><span className="flex items-center gap-2"><span className="grid size-5 place-items-center rounded-full bg-[#1f0a0a] text-xs font-bold text-[#f87171]">×</span><span className="text-[#8b9dc0]">Offline</span></span><strong className="text-[#f0f4ff]">{data.summary.offlineDevices}</strong></div>
                    <div className="flex items-center justify-between"><span className="flex items-center gap-2"><span className="grid size-5 place-items-center rounded-full text-xs font-bold text-[#4a5a80]" style={{ background: '#0f1424' }}>?</span><span className="text-[#8b9dc0]">Unknown / not returned</span></span><strong className="text-[#f0f4ff]">{Math.max(0, data.summary.totalDevices - data.summary.onlineDevices - data.summary.offlineDevices)}</strong></div>
                  </div>
                </div>
              )}
            </article>
          </section>

          <section className="mt-6 grid gap-6 xl:grid-cols-[1fr_1.45fr]">
            <article className="rounded-2xl border border-[#1e2a45] p-5 shadow-sm sm:p-6" style={{ background: '#0a0d16' }}>
              <div className="flex items-start justify-between gap-4"><div><h2 className="text-sm font-semibold text-[#f0f4ff]">Active faults</h2><p className="mt-1 text-xs text-[#4a5a80]">Faults requiring administrator attention.</p></div><AlertTriangleIcon className="size-5 text-[#4a5a80]" /></div>
              {data.activeFaults.length === 0 ? (
                <div className="mt-5"><EmptyState title="No active faults" description="There are no active fault records in the data returned by the monitoring service." /></div>
              ) : (
                <ul className="mt-3 divide-y divide-[#1e2a45]">
                  {data.activeFaults.map((fault) => (
                    <li key={fault.id} className="py-4 first:pt-2 last:pb-0">
                      <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="text-sm font-semibold text-[#f0f4ff]">{fault.title}</p><p className="mt-1 text-xs text-[#4a5a80]">{fault.deviceName} · {fault.detectedAt}</p></div><FaultSeverityBadge severity={fault.severity} /></div>
                    </li>
                  ))}
                </ul>
              )}
            </article>

            <article className="rounded-2xl border border-[#1e2a45] p-5 shadow-sm sm:p-6" style={{ background: '#0a0d16' }}>
              <div className="flex items-start justify-between gap-4"><div><h2 className="text-sm font-semibold text-[#f0f4ff]">Monitoring snapshot</h2><p className="mt-1 text-xs text-[#4a5a80]">Recent availability, latency, and packet-loss measurements when supplied.</p></div><HistoryIcon className="size-5 text-[#4a5a80]" /></div>
              {!data.monitoringTrend?.length ? (
                <div className="mt-5"><EmptyState title="No historical measurements" description="Historical monitoring trends will appear here when measurement data is available." /></div>
              ) : (
                <div className="mt-5" role="img" aria-label="Recent monitoring availability trend">
                  <div className="flex h-40 items-end gap-2 border-b border-l border-[#1e2a45] px-2 pb-0">
                    {data.monitoringTrend.map((point) => (
                      <div key={point.label} className="flex min-w-0 flex-1 flex-col items-center justify-end gap-2" title={`${point.label}: ${point.availabilityPercent ?? '—'}% availability`}>
                        <div className="w-full max-w-10 rounded-t-md" style={{ background: '#1558c9', height: `${Math.max(8, Math.min(100, point.availabilityPercent ?? 0))}%` }} />
                        <span className="text-[10px] text-[#4a5a80]">{point.label}</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-3 text-xs text-[#4a5a80]">Bars represent returned availability percentages. Detailed historical analytics can consume the same typed trend contract later.</p>
                </div>
              )}
            </article>
          </section>
        </>
      )}
    </div>
  )
}
