import { apiRequest, ApiError } from '../api/client'
import { FaultServiceError, type FaultEvent, type FaultExplanation, type FaultListResult, type FaultService, type FaultStatus } from './types'

interface ApiFault extends FaultEvent { device?: string }

function handleError(error: unknown): never {
  if (error instanceof ApiError && (error.status === 401 || error.status === 403)) throw new FaultServiceError('Your session is no longer authorized. Please sign in again.')
  throw new FaultServiceError(error instanceof Error ? error.message : 'Fault data could not be loaded.')
}

const apiService: FaultService = {
  async list(): Promise<FaultListResult> {
    try { return { faults: await apiRequest<ApiFault[]>('/faults/') } } catch (error) { return handleError(error) }
  },
  async get(faultId) {
    try { return await apiRequest<FaultEvent>(`/faults/${faultId}/`) } catch (error) { return handleError(error) }
  },
  async acknowledge(faultId) {
    try { return await apiRequest<FaultEvent>(`/faults/${faultId}/acknowledge/`, { method: 'POST' }) } catch (error) { return handleError(error) }
  },
  async updateStatus(faultId, status: FaultStatus) {
    try { return await apiRequest<FaultEvent>(`/faults/${faultId}/status/`, { method: 'PATCH', body: JSON.stringify({ status }) }) } catch (error) { return handleError(error) }
  },
  async resolve(faultId) {
    try { return await apiRequest<FaultEvent>(`/faults/${faultId}/resolve/`, { method: 'POST' }) } catch (error) { return handleError(error) }
  },
  async explain(faultId) {
    try { return await apiRequest<FaultExplanation>(`/faults/${faultId}/explain/`, { method: 'POST' }) } catch (error) { return handleError(error) }
  },
}

export function getFaultService(): FaultService { return apiService }
