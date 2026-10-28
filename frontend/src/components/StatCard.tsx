import type { ComponentType, SVGProps } from 'react'

type Icon = ComponentType<SVGProps<SVGSVGElement>>

interface StatCardProps {
  label: string
  value: number
  description: string
  icon: Icon
  tone?: 'neutral' | 'positive' | 'warning' | 'danger'
}

const toneClasses = {
  neutral: 'bg-[#0f1424] text-[#8b9dc0]',
  positive: 'bg-[#0a1f0a] text-[#4ade80]',
  warning: 'bg-[#1f1a0a] text-[#facc15]',
  danger: 'bg-[#1f0a0a] text-[#f87171]',
}

export function StatCard({ label, value, description, icon: Icon, tone = 'neutral' }: StatCardProps) {
  return (
    <article className="rounded-2xl border border-[#1e2a45] p-5 shadow-sm" style={{ background: '#0a0d16' }}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#4a5a80]">{label}</p>
          <p className="mt-3 text-3xl font-semibold tracking-tight text-[#f0f4ff]" aria-label={`${label}: ${value}`}>{value}</p>
        </div>
        <div className={`grid size-10 shrink-0 place-items-center rounded-xl ${toneClasses[tone]}`}>
          <Icon className="size-5" />
        </div>
      </div>
      <p className="mt-3 text-xs leading-5 text-[#4a5a80]">{description}</p>
    </article>
  )
}
