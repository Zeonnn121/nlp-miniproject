import { useCallback, useEffect, useMemo, useState } from 'react'
import { BellIcon, RefreshIcon } from '../components/icons'
import { getNotificationService } from '../notifications/service'
import type { FaultNotification, NotificationSeverity } from '../notifications/types'

const severityLabel: Record<NotificationSeverity, string> = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' }
const faultTypeLabel = (value: string) => value.replaceAll('_', ' ').toLowerCase().replace(/(^| )\S/g, (letter) => letter.toUpperCase())

function SeverityBadge({ severity }: { severity: NotificationSeverity }) {
  const symbol = severity === 'critical' ? '!!' : severity === 'high' ? '!' : severity === 'medium' ? '•' : '·'
  const colors: Record<NotificationSeverity, string> = {
    critical: 'border-[#3a1a1a] text-[#f87171]',
    high: 'border-[#3a2a1a] text-[#fb923c]',
    medium: 'border-[#3a3a1a] text-[#facc15]',
    low: 'border-[#1e2a45] text-[#4a5a80]',
  }
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold ${colors[severity]}`}><span aria-hidden="true">{symbol}</span>{severityLabel[severity]}</span>
}

export function NotificationsPage() {
  const service = useMemo(() => getNotificationService(), [])
  const [notifications, setNotifications] = useState<FaultNotification[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [selected, setSelected] = useState<FaultNotification | null>(null)

  const load = useCallback(async (refresh = false) => {
    if (refresh) setLoading(true)
    setError(null)
    try {
      const result = await service.list()
      setNotifications(result.notifications)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Notifications could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [service])

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      try {
        const result = await service.list()
        if (!cancelled) setNotifications(result.notifications)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Notifications could not be loaded.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void run()
    return () => { cancelled = true }
  }, [service])

  const unreadCount = notifications.filter((notification) => notification.status === 'unread').length
  const mockEnabled = import.meta.env.VITE_NOTIFICATIONS_ADAPTER === 'mock'

  const markRead = async (notification: FaultNotification) => {
    setActionError(null)
    try {
      const updated = await service.markAsRead(notification.id)
      setNotifications((items) => items.map((item) => item.id === updated.id ? updated : item))
      setSelected(updated)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'The notification could not be marked as read.')
    }
  }

  return <section className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
    <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
      <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#4a5a80]">Notifications</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-[#f0f4ff]">Detected fault alerts</h1><p className="mt-1 max-w-2xl text-sm text-[#8b9dc0]">Review fault notifications generated from the monitoring system. External email, SMS, and push delivery are not assumed here.</p></div>
      <button type="button" onClick={() => void load(true)} disabled={loading} className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#1e2a45] px-4 py-2.5 text-sm font-medium text-[#8b9dc0] shadow-sm hover:bg-[#0f1424] hover:text-[#f0f4ff] disabled:cursor-not-allowed disabled:opacity-60 transition-colors" style={{ background: '#0a0d16' }}><RefreshIcon className="size-4" />Refresh</button>
    </div>

    {mockEnabled && <div className="rounded-xl border border-[#3a3a1a] px-4 py-3 text-xs text-[#facc15]" style={{ background: '#1a1a0a' }}>Development adapter active: notifications are derived from existing fault fixtures and are not live backend notifications.</div>}
    {actionError && <div role="alert" className="rounded-xl border border-[#3a1a1a] px-4 py-3 text-sm text-[#f87171]" style={{ background: '#1a0a0a' }}>{actionError}</div>}

    <div className="grid gap-4 sm:grid-cols-2"><div className="rounded-2xl border border-[#1e2a45] p-5 shadow-sm" style={{ background: '#0a0d16' }}><p className="text-sm text-[#8b9dc0]">Total notifications</p><p className="mt-2 text-2xl font-semibold text-[#f0f4ff]">{loading ? '—' : notifications.length}</p></div><div className="rounded-2xl border border-[#1e2a45] p-5 shadow-sm" style={{ background: '#0a0d16' }}><p className="text-sm text-[#8b9dc0]">Unread</p><p className="mt-2 text-2xl font-semibold text-[#f0f4ff]">{loading ? '—' : unreadCount}</p></div></div>

    {loading ? <div className="rounded-2xl border border-[#1e2a45] p-10 text-center text-sm text-[#8b9dc0]" style={{ background: '#0a0d16' }}>Loading notifications…</div> : error ? <div role="alert" className="rounded-2xl border border-[#3a1a1a] p-8 text-center" style={{ background: '#1a0a0a' }}><p className="text-sm font-semibold text-[#f87171]">Notifications unavailable</p><p className="mt-1 text-sm text-[#fca5a5]">{error}</p><button type="button" onClick={() => void load(true)} className="mt-4 rounded-xl px-4 py-2 text-sm font-medium text-white" style={{ background: '#1558c9' }}>Try again</button></div> : notifications.length === 0 ? <div className="rounded-2xl border border-[#1e2a45] p-10 text-center" style={{ background: '#0a0d16' }}><BellIcon className="mx-auto size-8 text-[#4a5a80]" /><p className="mt-3 text-sm font-semibold text-[#f0f4ff]">No notifications</p><p className="mt-1 text-sm text-[#8b9dc0]">There are no detected fault notifications to review.</p></div> : <div className="overflow-hidden rounded-2xl border border-[#1e2a45] shadow-sm" style={{ background: '#0a0d16' }}><div className="overflow-x-auto"><table className="min-w-[760px] w-full text-left"><thead className="border-b border-[#1e2a45]" style={{ background: '#0f1424' }}><tr>{['Fault', 'Device', 'Severity', 'Detected', 'Status', ''].map((heading) => <th key={heading} className="px-5 py-3 text-xs font-semibold uppercase tracking-wide text-[#4a5a80]">{heading}</th>)}</tr></thead><tbody className="divide-y divide-[#1e2a45]">{notifications.map((notification) => <tr key={notification.id} className={notification.status === 'unread' ? 'bg-[#0d1020]' : ''}><td className="px-5 py-4"><p className="text-sm font-semibold text-[#f0f4ff]">{faultTypeLabel(notification.faultType)}</p><p className="mt-0.5 text-xs text-[#4a5a80]">{notification.description ?? 'Detected network fault'}</p></td><td className="px-5 py-4 text-sm text-[#8b9dc0]">{notification.deviceName}</td><td className="px-5 py-4"><SeverityBadge severity={notification.severity} /></td><td className="px-5 py-4 text-sm text-[#4a5a80]">{new Date(notification.detectedAt).toLocaleString()}</td><td className="px-5 py-4 text-sm font-medium text-[#8b9dc0]">{notification.status === 'unread' ? 'Unread' : 'Read'}</td><td className="px-5 py-4 text-right"><button type="button" onClick={() => setSelected(notification)} className="rounded-lg px-3 py-2 text-xs font-semibold text-[#8b9dc0] hover:bg-[#0f1424] hover:text-[#1558c9] transition-colors">Details</button></td></tr>)}</tbody></table></div></div>}

    {selected && <div className="fixed inset-0 z-50 grid place-items-center p-4" style={{ background: 'rgba(0,0,0,0.7)' }} role="dialog" aria-modal="true" aria-labelledby="notification-title"><div className="w-full max-w-lg rounded-2xl border border-[#1e2a45] p-6 shadow-xl" style={{ background: '#0a0d16' }}><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wide text-[#4a5a80]">Fault notification</p><h2 id="notification-title" className="mt-1 text-lg font-semibold text-[#f0f4ff]">{faultTypeLabel(selected.faultType)}</h2></div><SeverityBadge severity={selected.severity} /></div><dl className="mt-6 grid gap-4 sm:grid-cols-2"><div><dt className="text-xs text-[#4a5a80]">Affected device</dt><dd className="mt-1 text-sm font-medium text-[#f0f4ff]">{selected.deviceName}</dd></div><div><dt className="text-xs text-[#4a5a80]">Detected</dt><dd className="mt-1 text-sm font-medium text-[#f0f4ff]">{new Date(selected.detectedAt).toLocaleString()}</dd></div><div><dt className="text-xs text-[#4a5a80]">Notification status</dt><dd className="mt-1 text-sm font-medium text-[#f0f4ff]">{selected.status === 'unread' ? 'Unread' : 'Read'}</dd></div></dl><p className="mt-5 rounded-xl p-4 text-sm text-[#8b9dc0]" style={{ background: '#0f1424' }}>{selected.description ?? 'No additional fault description is available.'}</p><div className="mt-6 flex justify-end gap-2"><button type="button" onClick={() => setSelected(null)} className="rounded-xl border border-[#1e2a45] px-4 py-2.5 text-sm font-medium text-[#8b9dc0] hover:bg-[#0f1424]">Close</button>{selected.status === 'unread' && <button type="button" onClick={() => void markRead(selected)} className="rounded-xl px-4 py-2.5 text-sm font-medium text-white" style={{ background: 'linear-gradient(135deg, #1558c9, #0d3fa0)' }}>Mark as read</button>}</div></div></div>}
  </section>
}
