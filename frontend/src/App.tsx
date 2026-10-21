import { lazy, Suspense } from 'react'
import { AuthProvider } from './auth/AuthProvider'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { LoadingState } from './components/LoadingState'
import { AppShell } from './layouts/AppShell'
import { DashboardPage } from './pages/DashboardPage'
import { DevicesPage } from './pages/DevicesPage'
import { FaultHistoryPage } from './pages/FaultHistoryPage'
import { FaultsPage } from './pages/FaultsPage'
import { LoginPage } from './pages/LoginPage'
import { MonitoringHistoryPage } from './pages/MonitoringHistoryPage'
import { NotificationsPage } from './pages/NotificationsPage'

// Charting is only needed on the device detail view, so keep it out of the
// initial bundle.
const DeviceDetailsPage = lazy(() =>
  import('./pages/DeviceDetailsPage').then((module) => ({ default: module.DeviceDetailsPage })),
)

function AppContent() {
  const path = window.location.pathname
  if (path === '/login') return <LoginPage />
  const deviceDetailsMatch = path.match(/^\/devices\/([^/]+)$/)
  const page = path === '/devices'
    ? <DevicesPage />
    : path === '/faults'
      ? <FaultsPage />
      : path === '/monitoring-history'
        ? <MonitoringHistoryPage />
        : path === '/fault-history'
          ? <FaultHistoryPage />
          : path === '/notifications'
            ? <NotificationsPage />
            : deviceDetailsMatch
              ? <Suspense fallback={<div className="mx-auto max-w-7xl px-4 py-8"><LoadingState /></div>}>
                  <DeviceDetailsPage deviceId={decodeURIComponent(deviceDetailsMatch[1])} />
                </Suspense>
              : <DashboardPage />
  return <ProtectedRoute><AppShell>{page}</AppShell></ProtectedRoute>
}

function App() {
  return <AuthProvider><AppContent /></AuthProvider>
}

export default App
