interface ErrorStateProps {
  title?: string
  description: string
}

export function ErrorState({ title = 'Monitoring data unavailable', description }: ErrorStateProps) {
  return (
    <div className="rounded-2xl border border-[#3a1a1a] px-6 py-10 text-center" style={{ background: '#1a0a0a' }} role="alert">
      <div className="mx-auto mb-4 grid size-10 place-items-center rounded-full border border-[#3a1a1a] text-[#f87171]" style={{ background: '#1f0a0a' }} aria-hidden="true">!</div>
      <h3 className="text-sm font-semibold text-[#f87171]">{title}</h3>
      <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-[#fca5a5]">{description}</p>
    </div>
  )
}
