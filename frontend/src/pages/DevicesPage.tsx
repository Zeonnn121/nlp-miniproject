import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { AlertTriangleIcon, PlusIcon, RefreshIcon, SearchIcon, ServerIcon, XIcon } from '../components/icons'
import { DeviceStatusBadge } from '../components/DeviceStatusBadge'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { getDeviceService, isValidIp } from '../devices/service'
import { DeviceServiceError, type Device, type DeviceRegistrationInput, type DeviceType, type MonitoringState } from '../devices/types'
import { getMonitoringService } from '../monitoring/service'

const typeLabels: Record<DeviceType, string> = { router: 'Router', switch: 'Switch', server: 'Server', 'access-point': 'Access Point', firewall: 'Firewall', other: 'Other' }
const typeOptions = Object.entries(typeLabels) as [DeviceType, string][]
const initialForm: DeviceRegistrationInput = { name: '', ipAddress: '', type: '', monitoring: true }
const pageSize = 5

const inputClass = 'mt-1 w-full rounded-xl border border-[#1e2a45] px-3 py-2.5 text-sm text-[#f0f4ff] outline-none focus:border-[#1558c9] transition-colors'
const inputStyle = { background: '#030407' }

function DeviceForm({ device, onClose, onSaved }: { device: Device | null; onClose: () => void; onSaved: (device: Device) => void }) {
  const [form, setForm] = useState<DeviceRegistrationInput>(device ? { name: device.name, ipAddress: device.ipAddress, type: device.type, monitoring: device.monitoring === 'enabled' } : initialForm)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const validate = () => {
    const next: Record<string, string> = {}
    if (!form.name.trim()) next.name = 'Device name is required.'
    if (!form.ipAddress.trim()) next.ipAddress = 'IP address is required.'
    else if (!isValidIp(form.ipAddress)) next.ipAddress = 'Enter a valid IPv4 address.'
    if (!form.type) next.type = 'Device type is required.'
    setErrors(next)
    return Object.keys(next).length === 0
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError('')
    if (!validate()) return
    setSaving(true)
    try {
      const service = getDeviceService()
      const saved = device ? await service.update(device.id, form) : await service.create(form)
      onSaved(saved)
    } catch (reason: unknown) { setError(reason instanceof DeviceServiceError ? reason.message : 'Unable to save the device.') }
    finally { setSaving(false) }
  }
  return <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4" style={{ background: 'rgba(0,0,0,0.7)' }} role="dialog" aria-modal="true" aria-labelledby="device-form-title">
    <form onSubmit={submit} className="max-h-[95vh] w-full overflow-y-auto rounded-t-2xl border border-[#1e2a45] p-5 shadow-xl sm:max-w-lg sm:rounded-2xl sm:p-6" style={{ background: '#0a0d16' }}>
      <div className="flex items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#4a5a80]">Device management</p><h2 id="device-form-title" className="mt-1 text-xl font-semibold text-[#f0f4ff]">{device ? 'Edit device' : 'Register device'}</h2><p className="mt-1 text-sm text-[#8b9dc0]">Configure device details and monitoring state.</p></div><button type="button" onClick={onClose} className="rounded-lg p-2 text-[#8b9dc0] hover:bg-[#0f1424]" aria-label="Close form"><XIcon className="size-5" /></button></div>
      {error && <div className="mt-5"><ErrorState description={error} /></div>}
      <div className="mt-6 space-y-4">
        <label className="block text-sm font-medium text-[#8b9dc0]">Device name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={inputClass} style={inputStyle} aria-invalid={Boolean(errors.name)} />{errors.name && <span className="mt-1 block text-xs text-[#f87171]">{errors.name}</span>}</label>
        <label className="block text-sm font-medium text-[#8b9dc0]">IP address<input value={form.ipAddress} onChange={(e) => setForm({ ...form, ipAddress: e.target.value })} className={`${inputClass} font-mono`} style={inputStyle} inputMode="decimal" placeholder="192.168.1.1" aria-invalid={Boolean(errors.ipAddress)} />{errors.ipAddress && <span className="mt-1 block text-xs text-[#f87171]">{errors.ipAddress}</span>}</label>
        <label className="block text-sm font-medium text-[#8b9dc0]">Device type<select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as DeviceType })} className={inputClass} style={inputStyle} aria-invalid={Boolean(errors.type)}><option value="">Select device type</option>{typeOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>{errors.type && <span className="mt-1 block text-xs text-[#f87171]">{errors.type}</span>}</label>
        <fieldset><legend className="text-sm font-medium text-[#8b9dc0]">Monitoring configuration</legend><div className="mt-2 grid gap-2 sm:grid-cols-2"><label className="rounded-xl border border-[#1e2a45] p-3 text-sm text-[#8b9dc0]"><input type="radio" name="monitoring" checked={form.monitoring === true} onChange={() => setForm({ ...form, monitoring: true })} /> <span className="ml-1">Enable monitoring</span></label><label className="rounded-xl border border-[#1e2a45] p-3 text-sm text-[#8b9dc0]"><input type="radio" name="monitoring" checked={form.monitoring === false} onChange={() => setForm({ ...form, monitoring: false })} /> <span className="ml-1">Disable monitoring</span></label></div>{errors.monitoring && <span className="mt-1 block text-xs text-[#f87171]">{errors.monitoring}</span>}</fieldset>
      </div>
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"><button type="button" onClick={onClose} className="rounded-xl border border-[#1e2a45] px-4 py-2.5 text-sm font-semibold text-[#8b9dc0] hover:bg-[#0f1424]">Cancel</button><button type="submit" disabled={saving} className="rounded-xl px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60" style={{ background: 'linear-gradient(135deg, #1558c9, #0d3fa0)' }}>{saving ? 'Saving…' : device ? 'Save changes' : 'Register device'}</button></div>
    </form>
  </div>
}

export function DevicesPage() {
  const [devices, setDevices] = useState<Device[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<'all' | Device['status']>('all')
  const [monitoring, setMonitoring] = useState<'all' | MonitoringState>('all')
  const [sort, setSort] = useState<'name' | 'status' | 'type'>('name')
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<Device | null | undefined>(undefined)
  const [actionError, setActionError] = useState('')
  const [checkingId, setCheckingId] = useState<string | null>(null)

  const load = async () => {
    setLoading(true); setError(''); setActionError('')
    try { setDevices(await getDeviceService().list()) } catch (reason: unknown) { setError(reason instanceof DeviceServiceError ? reason.message : 'Unable to load devices.') }
    finally { setLoading(false) }
  }

  useEffect(() => {
    let active = true
    getDeviceService().list()
      .then((result) => { if (active) setDevices(result) })
      .catch((reason: unknown) => {
        if (!active) return
        setError(reason instanceof DeviceServiceError ? reason.message : 'Unable to load devices.')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return devices.filter((device) => (!q || [device.name, device.ipAddress, typeLabels[device.type]].some((value) => value.toLowerCase().includes(q))) && (status === 'all' || device.status === status) && (monitoring === 'all' || device.monitoring === monitoring)).sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name) : sort === 'type' ? typeLabels[a.type].localeCompare(typeLabels[b.type]) : a.status.localeCompare(b.status))
  }, [devices, query, status, monitoring, sort])
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const currentPage = Math.min(page, totalPages)
  const visible = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize)
  const toggleMonitoring = async (device: Device) => {
    setActionError('')
    try { const updated = await getDeviceService().setMonitoring(device.id, device.monitoring !== 'enabled'); setDevices((current) => current.map((item) => item.id === updated.id ? updated : item)) }
    catch (reason: unknown) { setActionError(reason instanceof DeviceServiceError ? reason.message : 'Unable to change monitoring state.') }
  }
  const runCheck = async (device: Device) => {
    setActionError(''); setCheckingId(device.id)
    try {
      await getMonitoringService().runCheck(device.id)
      const updatedDevices = await getDeviceService().list()
      setDevices(updatedDevices)
    } catch (reason: unknown) {
      setActionError(reason instanceof Error ? reason.message : 'Unable to run the monitoring check.')
    } finally {
      setCheckingId(null)
    }
  }
  const saved = (device: Device) => { setDevices((current) => current.some((item) => item.id === device.id) ? current.map((item) => item.id === device.id ? device : item) : [device, ...current]); setEditing(undefined) }

  const filterSelectClass = 'rounded-xl border border-[#1e2a45] px-3 py-2.5 text-sm text-[#8b9dc0] outline-none focus:border-[#1558c9]'
  const filterSelectStyle = { background: '#030407' }

  return <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 lg:py-10">
    <section className="mb-8 flex flex-col justify-between gap-4 md:flex-row md:items-end"><div><p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#4a5a80]">Devices</p><h1 className="text-2xl font-semibold tracking-tight text-[#f0f4ff] sm:text-3xl">Network devices</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-[#8b9dc0]">Register devices, manage monitoring configuration, and review current status.</p></div><button type="button" onClick={() => setEditing(null)} className="inline-flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white sm:w-auto" style={{ background: 'linear-gradient(135deg, #1558c9, #0d3fa0)' }}><PlusIcon className="size-4" />Register device</button></section>
    <section className="rounded-2xl border border-[#1e2a45] p-4 shadow-sm" style={{ background: '#0a0d16' }} aria-label="Device filters"><div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_repeat(3,auto)_auto]"><label className="relative"><span className="sr-only">Search devices</span><SearchIcon className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#4a5a80]" /><input value={query} onChange={(e) => { setQuery(e.target.value); setPage(1) }} placeholder="Search by name, IP, or type" className="w-full rounded-xl border border-[#1e2a45] py-2.5 pl-9 pr-3 text-sm text-[#f0f4ff] outline-none focus:border-[#1558c9]" style={{ background: '#030407' }} /></label><select value={status} onChange={(e) => { setStatus(e.target.value as typeof status); setPage(1) }} className={filterSelectClass} style={filterSelectStyle}><option value="all">All statuses</option><option value="online">Online</option><option value="offline">Offline</option><option value="unknown">Unknown</option></select><select value={monitoring} onChange={(e) => { setMonitoring(e.target.value as typeof monitoring); setPage(1) }} className={filterSelectClass} style={filterSelectStyle}><option value="all">All monitoring</option><option value="enabled">Monitoring enabled</option><option value="disabled">Monitoring disabled</option></select><select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} className={filterSelectClass} style={filterSelectStyle}><option value="name">Sort: Name</option><option value="status">Sort: Status</option><option value="type">Sort: Type</option></select><button type="button" onClick={() => void load()} className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#1e2a45] px-3 py-2.5 text-sm font-semibold text-[#8b9dc0] hover:bg-[#0f1424] hover:text-[#f0f4ff] transition-colors"><RefreshIcon className="size-4" />Refresh</button></div></section>
    {actionError && <div className="mt-4"><ErrorState description={actionError} /></div>}
    <section className="mt-6 overflow-hidden rounded-2xl border border-[#1e2a45] shadow-sm" style={{ background: '#0a0d16' }}>{loading ? <LoadingState /> : error ? <div className="p-5"><ErrorState description={error} /></div> : devices.length === 0 ? <div className="p-5"><EmptyState title="No devices registered" description="Register your first network device to begin managing monitoring." icon={<ServerIcon className="size-5" />} action={<button type="button" onClick={() => setEditing(null)} className="rounded-xl px-4 py-2 text-sm font-semibold text-white" style={{ background: 'linear-gradient(135deg, #1558c9, #0d3fa0)' }}>Register device</button>} /></div> : visible.length === 0 ? <div className="p-5"><EmptyState title="No matching devices" description="Try changing the search or filters." icon={<SearchIcon className="size-5" />} /></div> : <>
      <div className="overflow-x-auto"><table className="w-full min-w-[900px] text-left text-sm"><thead className="border-b border-[#1e2a45] text-xs font-semibold uppercase tracking-wide text-[#4a5a80]" style={{ background: '#0f1424' }}><tr><th className="px-5 py-3">Device</th><th className="px-5 py-3">IP address</th><th className="px-5 py-3">Type</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Monitoring</th><th className="px-5 py-3 text-right">Actions</th></tr></thead><tbody className="divide-y divide-[#1e2a45]">{visible.map((device) => <tr key={device.id} className="hover:bg-[#0f1424] transition-colors"><td className="px-5 py-4"><p className="font-semibold text-[#f0f4ff]">{device.name}</p><p className="mt-1 text-xs text-[#4a5a80]">Updated {device.updatedAt}</p></td><td className="px-5 py-4 font-mono text-xs text-[#8b9dc0]">{device.ipAddress}</td><td className="px-5 py-4 text-[#8b9dc0]">{typeLabels[device.type]}</td><td className="px-5 py-4"><DeviceStatusBadge status={device.status} /></td><td className="px-5 py-4"><button type="button" onClick={() => void toggleMonitoring(device)} className="rounded-lg border border-[#1e2a45] px-2.5 py-1.5 text-xs font-semibold text-[#8b9dc0] hover:border-[#1558c9] hover:text-[#1558c9] transition-colors" aria-label={`${device.monitoring === 'enabled' ? 'Disable' : 'Enable'} monitoring for ${device.name}`}>{device.monitoring === 'enabled' ? 'Enabled' : 'Disabled'}</button></td><td className="px-5 py-4 text-right"><div className="flex justify-end gap-1"><button type="button" onClick={() => void runCheck(device)} disabled={checkingId !== null} className="rounded-lg px-3 py-1.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60" style={{ background: '#1558c9' }}>{checkingId === device.id ? 'Checking…' : 'Run check'}</button><button type="button" onClick={() => setEditing(device)} className="rounded-lg px-3 py-1.5 text-xs font-semibold text-[#8b9dc0] hover:bg-[#0f1424] hover:text-[#f0f4ff] transition-colors">Edit</button></div></td></tr>)}</tbody></table></div>
      <div className="flex flex-col gap-3 border-t border-[#1e2a45] px-5 py-4 text-xs text-[#4a5a80] sm:flex-row sm:items-center sm:justify-between"><span>Showing {(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, filtered.length)} of {filtered.length}</span><div className="flex items-center gap-2"><button type="button" disabled={currentPage === 1} onClick={() => setPage((value) => value - 1)} className="rounded-lg border border-[#1e2a45] px-3 py-1.5 font-semibold text-[#8b9dc0] disabled:opacity-40 hover:border-[#1558c9] hover:text-[#1558c9] transition-colors">Previous</button><span>Page {currentPage} of {totalPages}</span><button type="button" disabled={currentPage === totalPages} onClick={() => setPage((value) => value + 1)} className="rounded-lg border border-[#1e2a45] px-3 py-1.5 font-semibold text-[#8b9dc0] disabled:opacity-40 hover:border-[#1558c9] hover:text-[#1558c9] transition-colors">Next</button></div></div>
    </>}</section>
    <p className="mt-4 flex items-start gap-2 text-xs text-[#4a5a80]"><AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />Deletion is intentionally unavailable until the Django/DRF contract explicitly supports device deletion.</p>
    {editing !== undefined && <DeviceForm device={editing} onClose={() => setEditing(undefined)} onSaved={saved} />}
  </div>
}
