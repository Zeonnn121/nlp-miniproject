import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { ActivityIcon, ChevronRightIcon, GlobeIcon, HistoryIcon, RefreshIcon, ServerIcon, SettingsIcon, ShieldIcon } from '../components/icons'
import { DeviceStatusBadge } from '../components/DeviceStatusBadge'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { LatencyTrendChart, PacketLossTrendChart, HttpResponseTrendChart } from '../components/TrendCharts'
import { getMonitoringService } from '../monitoring/service'
import { MonitoringServiceError, type DeviceMonitoringSnapshot, type MonitoringConfiguration } from '../monitoring/types'

function goToDevices() { window.location.assign('/devices') }
function formatTimestamp(value: string | null): string { if (!value) return 'Not available'; return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) }
function formatMilliseconds(value: number | null | undefined): string { return value === null || value === undefined ? 'Not available' : `${Math.round(value * 100) / 100} ms` }

function MetricCard({ label, value, detail }: { label: string; value: string; detail?: string }) { return <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-sm text-slate-500">{label}</p><p className="mt-2 text-2xl font-semibold tracking-tight">{value}</p>{detail && <p className="mt-1 text-xs text-slate-500">{detail}</p>}</article> }

function TrendPanel({ title, caption, children }: { title: string; caption: string; children: ReactNode }) {
  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Trend</p><h2 className="mt-1 text-lg font-semibold">{title}</h2></div><HistoryIcon className="size-5 text-slate-500" /></div><div className="mt-5">{children}</div><p className="mt-3 text-xs text-slate-500">{caption}</p></section>
}

function httpState(snapshot: DeviceMonitoringSnapshot): { label: string; tone: string; detail: string } {
  const configuration = snapshot.configuration
  if (!configuration.httpMonitoringEnabled) return { label: 'Not configured', tone: 'text-slate-500', detail: 'No HTTP endpoint is being probed for this device.' }
  const latest = snapshot.latest
  if (!latest || latest.httpOk === null) return { label: 'Awaiting check', tone: 'text-slate-500', detail: configuration.httpUrl }
  if (latest.httpOk) return { label: 'Healthy', tone: 'text-emerald-600', detail: `${configuration.httpUrl} responded with HTTP ${latest.httpStatusCode ?? '—'} in ${formatMilliseconds(latest.httpResponseTimeMs)}.` }
  return { label: 'Failing', tone: 'text-rose-600', detail: latest.httpError || `${configuration.httpUrl} returned an unacceptable response.` }
}

function HttpEndpointPanel({ deviceId, configuration, onSaved }: { deviceId: string; configuration: MonitoringConfiguration; onSaved: (next: MonitoringConfiguration) => void }) {
  const [enabled, setEnabled] = useState(configuration.httpMonitoringEnabled)
  const [url, setUrl] = useState(configuration.httpUrl)
  const [timeout, setTimeoutSeconds] = useState(String(configuration.httpTimeoutSeconds ?? 5))
  const [expectedStatus, setExpectedStatus] = useState(configuration.httpExpectedStatus === null ? '' : String(configuration.httpExpectedStatus))
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (enabled && !url.trim()) { setError('Enter the URL to probe before enabling HTTP monitoring.'); return }
    const parsedTimeout = Number(timeout)
    if (!Number.isFinite(parsedTimeout) || parsedTimeout < 0.1 || parsedTimeout > 30) { setError('Timeout must be between 0.1 and 30 seconds.'); return }
    const parsedStatus = expectedStatus.trim() === '' ? null : Number(expectedStatus)
    if (parsedStatus !== null && (!Number.isInteger(parsedStatus) || parsedStatus < 100 || parsedStatus > 599)) { setError('Expected status must be an integer between 100 and 599, or left blank.'); return }

    setSaving(true); setError(''); setMessage('')
    try {
      const next = await getMonitoringService().updateHttpConfiguration(deviceId, {
        httpMonitoringEnabled: enabled,
        httpUrl: url.trim(),
        httpTimeoutSeconds: parsedTimeout,
        httpExpectedStatus: parsedStatus,
      })
      onSaved(next)
      setMessage('HTTP endpoint settings saved. Run a monitoring check to collect a fresh result.')
    } catch (reason: unknown) {
      setError(reason instanceof MonitoringServiceError ? reason.message : 'Unable to save the HTTP endpoint settings.')
    } finally { setSaving(false) }
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start gap-3">
        <GlobeIcon className="mt-0.5 size-5 text-slate-500" />
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">HTTP endpoint</p>
          <h2 className="mt-1 text-lg font-semibold">Endpoint monitoring</h2>
        </div>
      </div>
      <p className="mt-3 text-xs text-slate-500">HTTP probing runs alongside ICMP. ICMP shows whether the host answers; the endpoint check shows whether the service answers, and how quickly.</p>
      <form className="mt-4 space-y-4" onSubmit={submit}>
        <label className="flex items-start gap-3 rounded-xl border border-slate-100 p-3">
          <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} className="mt-1 size-4 accent-slate-900" />
          <span>
            <span className="block text-sm font-medium">Probe this endpoint</span>
            <span className="block text-xs text-slate-500">Record status code and response time on every monitoring check.</span>
          </span>
        </label>
        <label className="block">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Endpoint URL</span>
          <input type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/health" disabled={!enabled} className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm disabled:bg-slate-50 disabled:text-slate-400" />
        </label>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Timeout (seconds)</span>
            <input type="number" step="0.1" min="0.1" max="30" value={timeout} onChange={(event) => setTimeoutSeconds(event.target.value)} disabled={!enabled} className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm disabled:bg-slate-50 disabled:text-slate-400" />
          </label>
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Expected status</span>
            <input type="number" min="100" max="599" value={expectedStatus} onChange={(event) => setExpectedStatus(event.target.value)} placeholder="Any 2xx/3xx" disabled={!enabled} className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm disabled:bg-slate-50 disabled:text-slate-400" />
            <span className="mt-1 block text-xs text-slate-500">Leave blank to accept any 2xx or 3xx response.</span>
          </label>
        </div>
        {error && <p className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</p>}
        {message && <p className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{message}</p>}
        <button type="submit" disabled={saving} className="inline-flex items-center justify-center rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm disabled:cursor-not-allowed disabled:opacity-60">{saving ? 'Saving…' : 'Save endpoint settings'}</button>
      </form>
    </section>
  )
}

function SnapshotContent({ snapshot, deviceId, onConfigurationSaved }: { snapshot: DeviceMonitoringSnapshot; deviceId: string; onConfigurationSaved: (next: MonitoringConfiguration) => void }) {
  const latest = snapshot.latest; const availability = latest?.reachable === null || latest?.reachable === undefined ? 'Not available' : latest.reachable ? 'Reachable' : 'Unreachable'; const latency = latest?.latencyMs === null || latest?.latencyMs === undefined ? 'Not available' : `${latest.latencyMs} ms`; const loss = latest?.packetLossPercent === null || latest?.packetLossPercent === undefined ? 'Not available' : `${latest.packetLossPercent}%`
  const http = httpState(snapshot)
  const hasHttpData = snapshot.configuration.httpMonitoringEnabled
  return <><div className="grid gap-4 md:grid-cols-3"><MetricCard label="Availability / reachability" value={availability} detail="Latest monitoring result" /><MetricCard label="Latency" value={latency} detail="Latest measured round-trip latency" /><MetricCard label="Packet loss" value={loss} detail="Latest measured packet loss" /></div>
  <div className="mt-6 grid gap-6 lg:grid-cols-2">
    <TrendPanel title="Latency" caption="Measured round-trip time for the most recent monitoring checks.">
      <LatencyTrendChart records={snapshot.history} />
    </TrendPanel>
    <TrendPanel title="Packet loss" caption="Percentage of probes that did not return, per monitoring check.">
      <PacketLossTrendChart records={snapshot.history} />
    </TrendPanel>
  </div>
  {hasHttpData && <div className="mt-6"><TrendPanel title="HTTP response time" caption="Time taken by the configured endpoint to respond. Failing checks are omitted from this series."><HttpResponseTrendChart records={snapshot.history} /></TrendPanel></div>}
  <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(300px,1fr)]">
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">SNMP</p><h2 className="mt-1 text-lg font-semibold">Supported metrics</h2></div><ActivityIcon className="size-5 text-slate-500" /></div>
      <div className="mt-5 space-y-3">{snapshot.snmpMetrics.length === 0 ? <p className="text-sm text-slate-500">No SNMP metrics are available for this device.</p> : snapshot.snmpMetrics.map((metric) => <div key={metric.name} className="flex items-center justify-between gap-4 rounded-xl border border-slate-100 p-3"><div><p className="text-sm font-medium">{metric.name}</p><p className="text-xs text-slate-500">{metric.available ? 'Available' : 'Not available from current monitoring data'}</p></div><span className="text-sm font-semibold">{metric.value === null ? '—' : `${metric.value}${metric.unit ? ` ${metric.unit}` : ''}`}</span></div>)}</div>
    </section>
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start gap-3"><GlobeIcon className="mt-0.5 size-5 text-slate-500" /><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">HTTP endpoint</p><h2 className="mt-1 text-lg font-semibold">Endpoint status</h2></div></div>
      <dl className="mt-5 space-y-4">
        <div><dt className="text-xs text-slate-500">State</dt><dd className={`mt-1 text-sm font-semibold ${http.tone}`}>{http.label}</dd></div>
        <div><dt className="text-xs text-slate-500">Detail</dt><dd className="mt-1 break-words text-sm">{http.detail}</dd></div>
        <div><dt className="text-xs text-slate-500">Last status code</dt><dd className="mt-1 text-sm font-medium">{latest?.httpStatusCode ?? 'Not available'}</dd></div>
        <div><dt className="text-xs text-slate-500">Response time</dt><dd className="mt-1 text-sm font-medium">{formatMilliseconds(latest?.httpResponseTimeMs)}</dd></div>
      </dl>
    </section>
  </div>
  <div className="mt-6 grid gap-6 lg:grid-cols-2">
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start gap-3"><ShieldIcon className="mt-0.5 size-5 text-slate-500" /><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Latest result</p><h2 className="mt-1 text-lg font-semibold">Most recent measurement</h2></div></div>
      <dl className="mt-5 grid gap-4 sm:grid-cols-2">
        <div><dt className="text-xs text-slate-500">Timestamp</dt><dd className="mt-1 text-sm font-medium">{formatTimestamp(latest?.timestamp ?? null)}</dd></div>
        <div><dt className="text-xs text-slate-500">Reachability</dt><dd className="mt-1 text-sm font-medium">{availability}</dd></div>
        <div><dt className="text-xs text-slate-500">Latency</dt><dd className="mt-1 text-sm font-medium">{latency}</dd></div>
        <div><dt className="text-xs text-slate-500">Packet loss</dt><dd className="mt-1 text-sm font-medium">{loss}</dd></div>
        <div><dt className="text-xs text-slate-500">HTTP response</dt><dd className="mt-1 text-sm font-medium">{latest?.httpOk === null || latest?.httpOk === undefined ? 'Not probed' : latest.httpOk ? 'Succeeded' : 'Failed'}</dd></div>
        <div><dt className="text-xs text-slate-500">HTTP error</dt><dd className="mt-1 break-words text-sm font-medium">{latest?.httpError || 'None'}</dd></div>
      </dl>
    </section>
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start gap-3"><SettingsIcon className="mt-0.5 size-5 text-slate-500" /><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Configuration</p><h2 className="mt-1 text-lg font-semibold">Monitoring configuration</h2></div></div>
      <dl className="mt-5 grid gap-4 sm:grid-cols-2">
        <div><dt className="text-xs text-slate-500">Monitoring</dt><dd className="mt-1 text-sm font-medium">{snapshot.configuration.enabled ? 'Enabled' : 'Disabled'}</dd></div>
        <div><dt className="text-xs text-slate-500">Polling interval</dt><dd className="mt-1 text-sm font-medium">{snapshot.configuration.intervalSeconds === null ? 'Not configured' : `${snapshot.configuration.intervalSeconds} seconds`}</dd></div>
        <div><dt className="text-xs text-slate-500">SNMP</dt><dd className="mt-1 text-sm font-medium">{snapshot.configuration.snmpEnabled ? snapshot.configuration.snmpVersion ?? 'Enabled' : 'Not enabled'}</dd></div>
        <div><dt className="text-xs text-slate-500">Available SNMP metrics</dt><dd className="mt-1 text-sm font-medium">{snapshot.configuration.availableMetrics.length || 'None reported'}</dd></div>
        <div><dt className="text-xs text-slate-500">HTTP endpoint</dt><dd className="mt-1 text-sm font-medium">{snapshot.configuration.httpMonitoringEnabled ? 'Enabled' : 'Not enabled'}</dd></div>
        <div><dt className="text-xs text-slate-500">HTTP timeout</dt><dd className="mt-1 text-sm font-medium">{snapshot.configuration.httpTimeoutSeconds === null ? 'Not configured' : `${snapshot.configuration.httpTimeoutSeconds} seconds`}</dd></div>
      </dl>
    </section>
  </div>
  <div className="mt-6"><HttpEndpointPanel key={deviceId} deviceId={deviceId} configuration={snapshot.configuration} onSaved={onConfigurationSaved} /></div>
  </>
}

export function DeviceDetailsPage({ deviceId }: { deviceId: string }) {
  const [snapshot, setSnapshot] = useState<DeviceMonitoringSnapshot | null>(null); const [loading, setLoading] = useState(true); const [checking, setChecking] = useState(false); const [error, setError] = useState(''); const [checkMessage, setCheckMessage] = useState('')
  const load = async () => { setLoading(true); setError(''); try { setSnapshot(await getMonitoringService().getSnapshot(deviceId)) } catch (reason: unknown) { setError(reason instanceof MonitoringServiceError ? reason.message : 'Unable to load device monitoring data.') } finally { setLoading(false) } }
  const runCheck = async () => { setChecking(true); setError(''); setCheckMessage(''); try { await getMonitoringService().runCheck(deviceId); await load(); setCheckMessage('Monitoring check completed. The latest result is shown below.') } catch (reason: unknown) { setError(reason instanceof MonitoringServiceError ? reason.message : 'Unable to run the monitoring check.') } finally { setChecking(false) } }
  const configurationSaved = (next: MonitoringConfiguration) => { setSnapshot((current) => (current ? { ...current, configuration: next } : current)) }
  useEffect(() => { let active = true; getMonitoringService().getSnapshot(deviceId).then((result) => { if (active) setSnapshot(result) }).catch((reason: unknown) => { if (active) setError(reason instanceof MonitoringServiceError ? reason.message : 'Unable to load device monitoring data.') }).finally(() => { if (active) setLoading(false) }); return () => { active = false } }, [deviceId])
  if (loading) return <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8"><LoadingState /></div>
  if (error || !snapshot) return <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8"><button type="button" onClick={goToDevices} className="mb-5 text-sm font-semibold text-slate-600 hover:text-slate-950">← Back to devices</button><ErrorState description={error || 'No monitoring data is available for this device.'} /></div>
  return <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 lg:py-10"><div className="mb-6 flex flex-col gap-4 md:flex-row md:items-start md:justify-between"><div><button type="button" onClick={goToDevices} className="mb-3 inline-flex items-center gap-1 text-sm font-semibold text-slate-500 hover:text-slate-950"><ChevronRightIcon className="size-4 rotate-180" />Devices</button><div className="flex items-start gap-3"><ServerIcon className="mt-1 size-7 text-slate-700" /><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Device details</p><h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">{snapshot.device.name}</h1><p className="mt-1 font-mono text-sm text-slate-500">{snapshot.device.ipAddress}</p></div></div></div><div className="flex flex-wrap gap-2"><button type="button" onClick={() => void runCheck()} disabled={checking} className="inline-flex items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm disabled:cursor-not-allowed disabled:opacity-60"><ActivityIcon className="size-4" />{checking ? 'Checking device...' : 'Run monitoring check'}</button><button type="button" onClick={() => void load()} disabled={checking} className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold shadow-sm disabled:cursor-not-allowed disabled:opacity-60"><RefreshIcon className="size-4" />Refresh data</button></div></div>{checkMessage && <div className="mb-6 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">{checkMessage}</div>}{import.meta.env.VITE_MONITORING_ADAPTER === 'mock' && <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">Development monitoring adapter: displayed measurements are fixture data for UI testing, not live network measurements.</div>}<section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4"><div><p className="text-xs text-slate-500">Device type</p><p className="mt-1 text-sm font-semibold capitalize">{snapshot.device.type.replace('-', ' ')}</p></div><div><p className="text-xs text-slate-500">Current status</p><div className="mt-1"><DeviceStatusBadge status={snapshot.device.status} /></div></div><div><p className="text-xs text-slate-500">Monitoring status</p><p className="mt-1 text-sm font-semibold">{snapshot.configuration.enabled ? 'Enabled' : 'Disabled'}</p></div><div><p className="text-xs text-slate-500">Last measurement</p><p className="mt-1 text-sm font-semibold">{formatTimestamp(snapshot.latest?.timestamp ?? null)}</p></div></div></section><SnapshotContent snapshot={snapshot} deviceId={deviceId} onConfigurationSaved={configurationSaved} /></div>
}
