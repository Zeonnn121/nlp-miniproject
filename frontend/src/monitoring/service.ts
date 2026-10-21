import { apiRequest, ApiError } from '../api/client'
import { MonitoringServiceError, type DeviceMonitoringService, type DeviceMonitoringSnapshot, type HttpMonitoringInput, type MonitoringConfiguration, type MonitoringRecord } from './types'

function fieldMessages(details: unknown): string | null {
  if (!details || typeof details !== 'object') return null
  const messages: string[] = []
  for (const value of Object.values(details as Record<string, unknown>)) {
    if (typeof value === 'string' && value.trim()) messages.push(value)
    else if (Array.isArray(value)) messages.push(...value.filter((entry): entry is string => typeof entry === 'string' && entry.trim() !== ''))
  }
  return messages.length > 0 ? messages.join(' ') : null
}

function handleError(error: unknown): never {
  if (error instanceof ApiError && (error.status === 401 || error.status === 403)) throw new MonitoringServiceError('Your session is no longer authorized. Please sign in again.')
  if (error instanceof ApiError && error.status === 400) throw new MonitoringServiceError(fieldMessages(error.details) ?? error.message, 'MONITORING_NOT_CONFIGURED')
  throw new MonitoringServiceError(error instanceof Error ? error.message : 'Monitoring data could not be loaded.')
}

const apiService: DeviceMonitoringService = {
  async getSnapshot(deviceId): Promise<DeviceMonitoringSnapshot> {
    try { return await apiRequest<DeviceMonitoringSnapshot>(`/devices/${deviceId}/monitoring-snapshot/`) } catch (error) { return handleError(error) }
  },
  async runCheck(deviceId): Promise<MonitoringRecord> {
    try { return await apiRequest<MonitoringRecord>(`/devices/${deviceId}/monitor/`, { method: 'POST', body: JSON.stringify({}) }) } catch (error) { return handleError(error) }
  },
  async updateHttpConfiguration(deviceId, input: HttpMonitoringInput): Promise<MonitoringConfiguration> {
    try { return await apiRequest<MonitoringConfiguration>(`/devices/${deviceId}/monitoring-config/`, { method: 'PATCH', body: JSON.stringify(input) }) } catch (error) { return handleError(error) }
  },
}

export function getMonitoringService(): DeviceMonitoringService { return apiService }
