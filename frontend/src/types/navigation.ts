export type NavigationKey =
  | 'dashboard'
  | 'devices'
  | 'faults'
  | 'monitoring'
  | 'fault-history'
  | 'notifications'
  | 'llm'
  | 'settings'

export interface NavigationItem {
  key: NavigationKey
  label: string
  description: string
  available: boolean
}
