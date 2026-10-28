import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useAuth } from '../auth/useAuth'
import { ActivityIcon, AlertTriangleIcon, BellIcon, ChevronRightIcon, HistoryIcon, LayoutDashboardIcon, MenuIcon, ServerIcon, SettingsIcon, ShieldIcon, XIcon } from '../components/icons'
import { getNotificationService } from '../notifications/service'
import type { FaultNotification } from '../notifications/types'
import type { NavigationItem } from '../types/navigation'

interface AppShellProps { children: ReactNode }
const navigation: NavigationItem[] = [
  { key: 'dashboard', label: 'Dashboard', description: 'Network overview', available: true },
  { key: 'devices', label: 'Devices', description: 'Manage network devices', available: true },
  { key: 'faults', label: 'Faults', description: 'Active and resolved faults', available: true },
  { key: 'monitoring', label: 'Monitoring History', description: 'Historical measurements', available: true },
  { key: 'fault-history', label: 'Fault History', description: 'Historical fault events', available: true },
  { key: 'notifications', label: 'Notifications', description: 'Monitoring alerts', available: true },
  { key: 'settings', label: 'Settings', description: 'System configuration', available: false },
]
const icons = { dashboard: LayoutDashboardIcon, devices: ServerIcon, faults: AlertTriangleIcon, monitoring: HistoryIcon, 'fault-history': HistoryIcon, notifications: BellIcon, settings: SettingsIcon }

function NotificationIndicator() {
  const [notifications, setNotifications] = useState<FaultNotification[]>([])
  const [open, setOpen] = useState(false)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    void getNotificationService().list().then((result) => {
      if (!cancelled) setNotifications(result.notifications)
    }).catch(() => {
      if (!cancelled) setError(true)
    })
    return () => { cancelled = true }
  }, [])

  const unread = notifications.filter((notification) => notification.status === 'unread').length
  const recent = notifications.slice(0, 3)

  return <div className="relative">
    <button type="button" className="relative rounded-xl p-2.5 text-[#8b9dc0] hover:bg-[#0f1424] hover:text-[#d4ff24] transition-colors" aria-label={unread ? `${unread} unread notifications` : 'Notifications'} aria-expanded={open} onClick={() => setOpen((value) => !value)}>
      <BellIcon className="size-5" />
      {unread > 0 && <span className="absolute right-1.5 top-1.5 grid min-w-4 translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-[#1558c9] px-1 text-[9px] font-bold leading-4 text-white" aria-hidden="true">{unread > 9 ? '9+' : unread}</span>}
    </button>
    {open && <div className="absolute right-0 top-12 z-50 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-[#1e2a45] bg-[#0a0d16] shadow-xl shadow-black/60">
      <div className="flex items-center justify-between border-b border-[#1e2a45] px-4 py-3"><div><p className="text-sm font-semibold text-[#f0f4ff]">Notifications</p><p className="text-xs text-[#8b9dc0]">{unread} unread</p></div><a href="/notifications" className="text-xs font-semibold text-[#1558c9] hover:text-[#d4ff24] transition-colors">View all</a></div>
      {error ? <p className="px-4 py-6 text-center text-xs text-[#8b9dc0]">Notifications are unavailable.</p> : recent.length === 0 ? <p className="px-4 py-6 text-center text-xs text-[#8b9dc0]">No detected fault notifications.</p> : <div className="divide-y divide-[#1e2a45]">{recent.map((notification) => <button key={notification.id} type="button" onClick={() => window.location.replace('/notifications')} className="block w-full px-4 py-3 text-left hover:bg-[#0f1424] transition-colors"><div className="flex items-start gap-3"><span className={`mt-1.5 size-2 shrink-0 rounded-full ${notification.status === 'unread' ? 'bg-[#1558c9]' : 'bg-[#1e2a45]'}`} aria-hidden="true" /><div className="min-w-0"><p className="truncate text-xs font-semibold text-[#f0f4ff]">{notification.faultType.replaceAll('_', ' ')}</p><p className="mt-0.5 truncate text-xs text-[#8b9dc0]">{notification.deviceName} · {notification.severity}</p><p className="mt-1 text-[10px] text-[#4a5a80]">{new Date(notification.detectedAt).toLocaleString()}</p></div></div></button>)}</div>}
    </div>}
  </div>
}

export function AppShell({ children }: AppShellProps) {
  const [mobileOpen, setMobileOpen] = useState(false)
  const { session, logout } = useAuth()
  const handleLogout = async () => { await logout(); window.location.replace('/login') }
  const username = session?.user.username ?? 'Administrator'
  const initials = username.slice(0, 2).toUpperCase()
  const currentPath = window.location.pathname
  const routes: Record<string, string> = { dashboard: '/', devices: '/devices', faults: '/faults', monitoring: '/monitoring-history', 'fault-history': '/fault-history', notifications: '/notifications' }
  return <div className="min-h-screen text-[#e2e8f0]" style={{ background: '#030407' }}>
    {mobileOpen && <button className="fixed inset-0 z-40 bg-black/60 lg:hidden" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
    <aside className={`fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-[#1e2a45] transition-transform lg:translate-x-0 ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}`} style={{ background: '#030407' }}>
      <div className="flex h-20 items-center justify-between border-b border-[#1e2a45] px-6"><div className="flex items-center gap-3"><div className="grid size-10 place-items-center rounded-xl shadow-sm" style={{ background: 'linear-gradient(135deg, #1558c9, #0d3fa0)' }}><ActivityIcon className="size-5 text-white" /></div><div><p className="text-sm font-semibold tracking-tight text-[#f0f4ff]">NetWatch</p><p className="text-xs text-[#4a5a80]">Network Monitoring</p></div></div><button className="rounded-lg p-2 text-[#8b9dc0] hover:bg-[#0f1424] lg:hidden" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><XIcon className="size-5" /></button></div>
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-5" aria-label="Main navigation"><p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#4a5a80]">Workspace</p>{navigation.map((item) => { const Icon = icons[item.key]; const active = routes[item.key] === currentPath; return <button key={item.key} type="button" disabled={!item.available} title={item.available ? item.description : `${item.label} will be implemented in a later phase`} className={`group flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition-all ${active ? 'text-[#030407] shadow-sm font-semibold' : item.available ? 'text-[#8b9dc0] hover:bg-[#0f1424] hover:text-[#f0f4ff]' : 'cursor-not-allowed text-[#2a3a5a]'}`} style={active ? { background: 'linear-gradient(135deg, #1558c9, #0d3fa0)' } : {}} onClick={() => { if (item.available) { window.location.replace(routes[item.key]); setMobileOpen(false) } }}><Icon className={`size-[18px] shrink-0 ${active ? 'text-white' : ''}`} /><span className="min-w-0 flex-1"><span className={`block text-sm font-medium ${active ? 'text-white' : ''}`}>{item.label}</span>{!item.available && <span className="mt-0.5 block text-[10px] text-[#2a3a5a]">Coming soon</span>}</span>{active && <ChevronRightIcon className="size-4 text-white opacity-80" />}</button> })}</nav>
      <div className="border-t border-[#1e2a45] p-4"><div className="flex items-center gap-3 rounded-xl p-3" style={{ background: '#0a0d16' }}><div className="grid size-9 place-items-center rounded-lg text-[#8b9dc0] ring-1 ring-[#1e2a45]" style={{ background: '#030407' }}><ShieldIcon className="size-4" /></div><div className="min-w-0 flex-1"><p className="truncate text-xs font-semibold text-[#f0f4ff]">{username}</p><p className="truncate text-[11px] text-[#4a5a80]">Administrator</p></div><button type="button" onClick={handleLogout} className="rounded-lg px-2 py-1.5 text-[11px] font-medium text-[#8b9dc0] hover:bg-[#0f1424] hover:text-[#d4ff24] transition-colors" aria-label="Sign out">Sign out</button></div></div>
    </aside>
    <div className="lg:pl-72"><header className="sticky top-0 z-30 flex h-20 items-center justify-between border-b border-[#1e2a45] px-4 backdrop-blur sm:px-6 lg:px-8" style={{ background: 'rgba(3,4,7,0.92)' }}><div className="flex items-center gap-3"><button className="rounded-xl p-2 text-[#8b9dc0] hover:bg-[#0f1424] lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><MenuIcon className="size-5" /></button><div><p className="text-sm font-semibold text-[#f0f4ff]">Network Operations</p><p className="hidden text-xs text-[#4a5a80] sm:block">Centralized monitoring and fault visibility</p></div></div><div className="flex items-center gap-2"><div className="hidden items-center gap-2 rounded-full border border-[#1e2a45] px-3 py-1.5 text-xs font-medium text-[#8b9dc0] sm:flex"><span className="size-1.5 rounded-full bg-[#d4ff24]" /> System ready</div><NotificationIndicator /><div className="ml-1 grid size-9 place-items-center rounded-full text-xs font-semibold text-[#030407]" style={{ background: '#d4ff24' }} aria-label={`${username} profile`}>{initials}</div></div></header><main className="min-h-[calc(100vh-5rem)]">{children}</main></div>
  </div>
}
