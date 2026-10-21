export type FaultSeverity = 'critical' | 'high' | 'medium' | 'low'
export type FaultStatus = 'active' | 'acknowledged' | 'resolved'

export type FaultType =
  | 'DEVICE_UNREACHABLE'
  | 'HIGH_LATENCY'
  | 'HIGH_PACKET_LOSS'
  | 'HIGH_CPU_USAGE'
  | 'HIGH_MEMORY_USAGE'
  | 'INTERFACE_FAILURE'
  | 'CONNECTIVITY_FAILURE'

export interface FaultEvent {
  id: string
  deviceId: string
  deviceName: string
  faultType: FaultType
  severity: FaultSeverity
  detectedAt: string
  status: FaultStatus
  description?: string
  resolvedAt?: string | null
}

export type FaultExplanationSource = 'llm' | 'fallback'

export interface FaultExplanation {
  explanation: string
  likely_causes: string[]
  recommended_actions: string[]
  source: FaultExplanationSource
}

export interface FaultFilters {
  severity: FaultSeverity | 'all'
  status: FaultStatus | 'all'
  faultType: FaultType | 'all'
  deviceId: string | 'all'
  search: string
}

export interface FaultListResult {
  faults: FaultEvent[]
}

export class FaultServiceError extends Error {
  readonly code: 'FAULTS_NOT_CONFIGURED' | 'FAULTS_API_ERROR' | 'FAULT_NOT_FOUND' | 'FAULT_ACTION_UNSUPPORTED'

  constructor(message: string, code: FaultServiceError['code'] = 'FAULTS_API_ERROR') {
    super(message)
    this.name = 'FaultServiceError'
    this.code = code
  }
}

export interface FaultService {
  list: () => Promise<FaultListResult>
  get: (faultId: string) => Promise<FaultEvent>
  acknowledge: (faultId: string) => Promise<FaultEvent>
  updateStatus: (faultId: string, status: FaultStatus) => Promise<FaultEvent>
  resolve: (faultId: string) => Promise<FaultEvent>
  explain: (faultId: string) => Promise<FaultExplanation>
}

export type FaultScenario = 'populated' | 'empty' | 'partial' | 'error' | 'loading'
