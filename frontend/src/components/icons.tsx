import type { ReactNode, SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>
type IconWithChildrenProps = IconProps & { children: ReactNode }

const Icon = ({ children, ...props }: IconWithChildrenProps) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
    {children}
  </svg>
)

export const ActivityIcon = (props: IconProps) => <Icon {...props}><path d="M3 12h4l2.2-6 4.6 12L16 12h5" /></Icon>
export const LayoutDashboardIcon = (props: IconProps) => <Icon {...props}><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></Icon>
export const ServerIcon = (props: IconProps) => <Icon {...props}><rect x="3" y="4" width="18" height="6" rx="1.5" /><rect x="3" y="14" width="18" height="6" rx="1.5" /><path d="M7 7h.01M7 17h.01M11 7h7M11 17h7" /></Icon>
export const AlertTriangleIcon = (props: IconProps) => <Icon {...props}><path d="m10.3 3.8-8 14A2 2 0 0 0 4 20.8h16a2 2 0 0 0 1.7-3l-8-14a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4M12 17h.01" /></Icon>
export const HistoryIcon = (props: IconProps) => <Icon {...props}><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5M12 7v5l3 2" /></Icon>
export const CpuIcon = (props: IconProps) => <Icon {...props}><rect x="7" y="7" width="10" height="10" rx="1.5" /><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4" /></Icon>
export const BellIcon = (props: IconProps) => <Icon {...props}><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" /></Icon>
export const SettingsIcon = (props: IconProps) => <Icon {...props}><path d="M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Z" /><path d="m19.4 15 .1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.8 1.8 0 0 0-3.1 1.3v.2a2 2 0 1 1-4 0v-.2a1.8 1.8 0 0 0-3.1-1.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.8 1.8 0 0 0-1.3-3.1h-.2a2 2 0 1 1 0-4h.2a1.8 1.8 0 0 0 1.3-3.1l-.1-.1A2 2 0 1 1 6.4 2l.1.1a1.8 1.8 0 0 0 3.1-1.3V.6a2 2 0 1 1 4 0v.2a1.8 1.8 0 0 0 3.1 1.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.8 1.8 0 0 0 1.3 3.1Z" /></Icon>
export const MenuIcon = (props: IconProps) => <Icon {...props}><path d="M4 6h16M4 12h16M4 18h16" /></Icon>
export const XIcon = (props: IconProps) => <Icon {...props}><path d="m6 6 12 12M18 6 6 18" /></Icon>
export const ChevronRightIcon = (props: IconProps) => <Icon {...props}><path d="m9 18 6-6-6-6" /></Icon>
export const ShieldIcon = (props: IconProps) => <Icon {...props}><path d="M12 3 20 6v5c0 5-3.4 8.5-8 10-4.6-1.5-8-5-8-10V6l8-3Z" /><path d="m9 12 2 2 4-4" /></Icon>
export const PlusIcon = (props: IconProps) => <Icon {...props}><path d="M12 5v14M5 12h14" /></Icon>
export const RefreshIcon = (props: IconProps) => <Icon {...props}><path d="M20 11a8 8 0 0 0-14.8-4L3 10" /><path d="M3 5v5h5M4 13a8 8 0 0 0 14.8 4L21 14" /><path d="M21 19v-5h-5" /></Icon>
export const SearchIcon = (props: IconProps) => <Icon {...props}><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></Icon>
export const GlobeIcon = (props: IconProps) => <Icon {...props}><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9S14.5 18.3 12 21c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3Z" /></Icon>
