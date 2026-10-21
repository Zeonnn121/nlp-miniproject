import { useEffect, useMemo, useState } from 'react'
import { AlertTriangleIcon, ChevronRightIcon, RefreshIcon, SearchIcon, ServerIcon } from '../components/icons'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { getFaultService } from '../faults/service'
import { FaultServiceError, type FaultEvent, type FaultExplanation, type FaultSeverity, type FaultStatus, type FaultType } from '../faults/types'

const severityLabels: Record<FaultSeverity, string> = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' }
const statusLabels: Record<FaultStatus, string> = { active: 'Active', acknowledged: 'Acknowledged', resolved: 'Resolved' }
const typeLabels: Record<FaultType, string> = {
  DEVICE_UNREACHABLE: 'Device unreachable', HIGH_LATENCY: 'High latency', HIGH_PACKET_LOSS: 'High packet loss',
  HIGH_CPU_USAGE: 'High CPU usage', HIGH_MEMORY_USAGE: 'High memory usage', INTERFACE_FAILURE: 'Interface failure', CONNECTIVITY_FAILURE: 'Connectivity failure',
}

function SeverityBadge({ severity }: { severity: FaultSeverity }) {
  const symbols: Record<FaultSeverity, string> = { critical: '!!', high: '!', medium: '•', low: '·' }
  return <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 px-2.5 py-1 text-xs font-semibold"><span aria-hidden="true">{symbols[severity]}</span>{severityLabels[severity]}</span>
}

function StatusBadge({ status }: { status: FaultStatus }) {
  return <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 px-2.5 py-1 text-xs font-semibold"><span aria-hidden="true">{status === 'resolved' ? '✓' : status === 'acknowledged' ? '◷' : '!'}</span>{statusLabels[status]}</span>
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

export function FaultsPage() {
  const [faults, setFaults] = useState<FaultEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [search, setSearch] = useState('')
  const [severity, setSeverity] = useState<FaultSeverity | 'all'>('all')
  const [status, setStatus] = useState<FaultStatus | 'all'>('all')
  const [faultType, setFaultType] = useState<FaultType | 'all'>('all')
  const [deviceId, setDeviceId] = useState('all')
  const [selected, setSelected] = useState<FaultEvent | null>(null)

  const load = async () => {
    setLoading(true); setError(''); setActionError('')
    try { setFaults((await getFaultService().list()).faults) }
    catch (reason: unknown) { setError(reason instanceof FaultServiceError ? reason.message : 'Unable to load fault events.') }
    finally { setLoading(false) }
  }

  useEffect(() => {
    let active = true
    getFaultService().list().then((result) => { if (active) setFaults(result.faults) }).catch((reason: unknown) => { if (active) setError(reason instanceof FaultServiceError ? reason.message : 'Unable to load fault events.') }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const devices = useMemo(() => Array.from(new Map(faults.map((fault) => [fault.deviceId, fault.deviceName])).entries()), [faults])
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return faults.filter((fault) => {
      const text = `${fault.deviceName} ${fault.faultType} ${typeLabels[fault.faultType]} ${fault.description ?? ''}`.toLowerCase()
      return (!q || text.includes(q)) && (severity === 'all' || fault.severity === severity) && (status === 'all' || fault.status === status) && (faultType === 'all' || fault.faultType === faultType) && (deviceId === 'all' || fault.deviceId === deviceId)
    }).sort((a, b) => new Date(b.detectedAt).getTime() - new Date(a.detectedAt).getTime())
  }, [faults, search, severity, status, faultType, deviceId])

  const update = async (faultId: string, nextStatus: FaultStatus) => {
    setActionError('')
    try {
      const service = getFaultService()
      const updated = nextStatus === 'acknowledged' ? await service.acknowledge(faultId) : nextStatus === 'resolved' ? await service.resolve(faultId) : await service.updateStatus(faultId, nextStatus)
      setFaults((current) => current.map((fault) => fault.id === updated.id ? updated : fault))
      setSelected(updated)
    } catch (reason: unknown) { setActionError(reason instanceof FaultServiceError ? reason.message : 'Unable to update fault status.') }
  }

  const activeCount = faults.filter((fault) => fault.status !== 'resolved').length
  const resolvedCount = faults.filter((fault) => fault.status === 'resolved').length

  return <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 lg:py-10">
    <section className="mb-8 flex flex-col justify-between gap-4 md:flex-row md:items-end"><div><p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Fault management</p><h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Faults</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">Review detected faults, their severity, affected devices, and current lifecycle status.</p></div><button type="button" onClick={() => void load()} className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold shadow-sm sm:w-auto"><RefreshIcon className="size-4" />Refresh</button></section>
    {import.meta.env.VITE_FAULTS_ADAPTER === 'mock' && <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">Development fault adapter: displayed events are fixture data for UI testing, not faults detected from a live network.</div>}
    <div className="mb-6 grid gap-4 sm:grid-cols-2"><article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-sm text-slate-500">Active / acknowledged</p><p className="mt-2 text-2xl font-semibold">{activeCount}</p></article><article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-sm text-slate-500">Resolved</p><p className="mt-2 text-2xl font-semibold">{resolvedCount}</p></article></div>
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Fault filters"><div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_repeat(4,auto)]"><label className="relative"><span className="sr-only">Search faults</span><SearchIcon className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search device, fault type, or description" className="w-full rounded-xl border border-slate-200 py-2.5 pl-9 pr-3 text-sm" /></label><select value={severity} onChange={(e) => setSeverity(e.target.value as FaultSeverity | 'all')} className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm"><option value="all">All severities</option>{Object.entries(severityLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><select value={status} onChange={(e) => setStatus(e.target.value as FaultStatus | 'all')} className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm"><option value="all">All statuses</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><select value={faultType} onChange={(e) => setFaultType(e.target.value as FaultType | 'all')} className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm"><option value="all">All fault types</option>{Object.entries(typeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><select value={deviceId} onChange={(e) => setDeviceId(e.target.value)} className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm"><option value="all">All devices</option>{devices.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></div></section>
    {actionError && <div className="mt-4"><ErrorState description={actionError} /></div>}
    <section className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">{loading ? <LoadingState /> : error ? <div className="p-5"><ErrorState description={error} /></div> : faults.length === 0 ? <div className="p-5"><EmptyState title="No fault events" description="There are currently no fault events available from the monitoring service." icon={<AlertTriangleIcon className="size-5" />} /></div> : filtered.length === 0 ? <div className="p-5"><EmptyState title="No matching faults" description="Try changing the search or filters." icon={<SearchIcon className="size-5" />} /></div> : <div className="overflow-x-auto"><table className="w-full min-w-[900px] text-left text-sm"><thead className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500"><tr><th className="px-5 py-3">Fault type</th><th className="px-5 py-3">Severity</th><th className="px-5 py-3">Affected device</th><th className="px-5 py-3">Detected</th><th className="px-5 py-3">Status</th><th className="px-5 py-3 text-right">Action</th></tr></thead><tbody className="divide-y divide-slate-100">{filtered.map((fault) => <tr key={fault.id} className="hover:bg-slate-50"><td className="px-5 py-4"><button type="button" onClick={() => setSelected(fault)} className="font-semibold text-left hover:underline">{typeLabels[fault.faultType]}</button></td><td className="px-5 py-4"><SeverityBadge severity={fault.severity} /></td><td className="px-5 py-4"><div className="flex items-center gap-2"><ServerIcon className="size-4 text-slate-500" />{fault.deviceName}</div></td><td className="px-5 py-4 text-xs text-slate-500">{formatDate(fault.detectedAt)}</td><td className="px-5 py-4"><StatusBadge status={fault.status} /></td><td className="px-5 py-4 text-right"><button type="button" onClick={() => setSelected(fault)} className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold hover:bg-slate-100">Details<ChevronRightIcon className="size-3.5" /></button></td></tr>)}</tbody></table></div>}</section>
    {selected && <FaultDetails key={selected.id} fault={selected} onClose={() => setSelected(null)} onUpdate={(nextStatus) => void update(selected.id, nextStatus)} />}
  </div>
}

function FaultDetails({ fault, onClose, onUpdate }: { fault: FaultEvent; onClose: () => void; onUpdate: (status: FaultStatus) => void }) {
  const [explanation, setExplanation] = useState<FaultExplanation | null>(null)
  const [explaining, setExplaining] = useState(false)
  const [explainError, setExplainError] = useState('')

  const explainFault = async () => {
    setExplaining(true)
    setExplainError('')
    setExplanation(null)
    try {
      setExplanation(await getFaultService().explain(fault.id))
    } catch (reason: unknown) {
      setExplainError(reason instanceof FaultServiceError ? reason.message : 'The fault explanation could not be generated. Please try again.')
    } finally {
      setExplaining(false)
    }
  }

  return <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/40 p-0 sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-labelledby="fault-details-title"><div className="max-h-[90vh] w-full overflow-y-auto rounded-t-2xl bg-white p-5 shadow-xl sm:max-w-2xl sm:rounded-2xl sm:p-6"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Fault details</p><h2 id="fault-details-title" className="mt-1 text-xl font-semibold">{typeLabels[fault.faultType]}</h2></div><button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-sm font-semibold text-slate-500 hover:bg-slate-100">Close</button></div><div className="mt-6 grid gap-4 sm:grid-cols-2"><div><p className="text-xs text-slate-500">Severity</p><div className="mt-1"><SeverityBadge severity={fault.severity} /></div></div><div><p className="text-xs text-slate-500">Current status</p><div className="mt-1"><StatusBadge status={fault.status} /></div></div><div><p className="text-xs text-slate-500">Affected device</p><p className="mt-1 text-sm font-semibold">{fault.deviceName}</p><p className="text-xs text-slate-500">{fault.deviceId}</p></div><div><p className="text-xs text-slate-500">Detection time</p><p className="mt-1 text-sm font-semibold">{formatDate(fault.detectedAt)}</p></div></div>{fault.description && <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Description</p><p className="mt-2 text-sm leading-6">{fault.description}</p></div>}
    <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div><p className="text-sm font-semibold">Fault explainer</p><p className="mt-1 text-xs leading-5 text-slate-500">Generate an explanation with likely causes and recommended actions.</p></div>
        <button type="button" onClick={() => void explainFault()} disabled={explaining} className="inline-flex items-center justify-center gap-2 rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">{explaining && <span className="size-4 animate-spin rounded-full border-2 border-white/40 border-t-white" aria-hidden="true" />}{explaining ? 'Explaining…' : explanation ? 'Regenerate explanation' : 'Explain this fault'}</button>
      </div>
      {explainError && <p role="alert" className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{explainError}</p>}
    </div>
    {explaining && <div className="mt-4 flex items-center gap-3 rounded-2xl border border-slate-200 bg-white px-5 py-4" role="status" aria-live="polite"><span className="size-5 animate-spin rounded-full border-2 border-slate-200 border-t-slate-900" aria-hidden="true" /><p className="text-sm font-medium text-slate-700">Analysing fault metrics and generating an explanation…</p></div>}
    {explanation && !explaining && <FaultExplanationCard explanation={explanation} />}
    {fault.resolvedAt && <div className="mt-4"><p className="text-xs text-slate-500">Resolved at</p><p className="mt-1 text-sm font-semibold">{formatDate(fault.resolvedAt)}</p></div>}<div className="mt-6 flex flex-col gap-2 border-t border-slate-200 pt-5 sm:flex-row sm:justify-end">{fault.status === 'active' && <button type="button" onClick={() => onUpdate('acknowledged')} className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold">Acknowledge</button>}{fault.status !== 'resolved' && <button type="button" onClick={() => onUpdate('resolved')} className="rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white">Resolve fault</button>}</div></div></div>
}

function FaultExplanationCard({ explanation }: { explanation: FaultExplanation }) {
  const fromModel = explanation.source === 'llm'
  return <article className="mt-4 rounded-2xl border border-slate-200 bg-white p-5">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-sm font-semibold text-slate-900">Fault explanation</h3>
      <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${fromModel ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
        <span aria-hidden="true">{fromModel ? '✦' : '⚙'}</span>{fromModel ? 'Fine-tuned model' : 'Fallback template'}
      </span>
    </div>
    <div className="mt-4 space-y-5">
      <section><h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Explanation</h4><p className="mt-2 text-sm leading-6 text-slate-700">{explanation.explanation}</p></section>
      <section>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Likely causes</h4>
        {explanation.likely_causes.length > 0 ? <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-sm leading-6 text-slate-700">{explanation.likely_causes.map((cause, index) => <li key={`${index}-${cause}`}>{cause}</li>)}</ol> : <p className="mt-2 text-sm text-slate-500">No likely causes were reported.</p>}
      </section>
      <section>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recommended actions</h4>
        {explanation.recommended_actions.length > 0 ? <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-sm leading-6 text-slate-700">{explanation.recommended_actions.map((action, index) => <li key={`${index}-${action}`}>{action}</li>)}</ol> : <p className="mt-2 text-sm text-slate-500">No recommended actions were reported.</p>}
      </section>
    </div>
  </article>
}

