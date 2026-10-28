import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: string
  description: string
  icon?: ReactNode
  action?: ReactNode
}

export function EmptyState({ title, description, icon, action }: EmptyStateProps) {
  return (
    <div className="rounded-2xl border border-dashed border-[#1e2a45] px-6 py-10 text-center" style={{ background: '#0a0d16' }}>
      {icon && <div className="mx-auto mb-4 grid size-10 place-items-center rounded-xl text-[#4a5a80]" style={{ background: '#0f1424' }}>{icon}</div>}
      <h3 className="text-sm font-semibold text-[#f0f4ff]">{title}</h3>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[#8b9dc0]">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}
